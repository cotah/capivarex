"""Tests for TwilioService and QuotaService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timezone


# ══════════════════════════════════════════════════════════════════════════════
# TWILIO SERVICE TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestBestNumber:
    """Tests for _best_number helper."""

    def test_no_active_numbers(self):
        from services.integrations.twilio_service import _best_number, PHONE_POOL
        original = [n.copy() for n in PHONE_POOL]
        for n in PHONE_POOL:
            n["active"] = False
        try:
            assert _best_number("US") is None
        finally:
            for i, n in enumerate(original):
                PHONE_POOL[i].update(n)

    def test_regional_match(self):
        from services.integrations.twilio_service import _best_number
        result = _best_number("US")
        assert result is not None
        assert result["country"] == "US"

    def test_default_fallback(self):
        from services.integrations.twilio_service import _best_number
        result = _best_number("ZZ")  # país sem match
        assert result is not None  # cai no fallback

    def test_empty_country_uses_default(self):
        from services.integrations.twilio_service import _best_number
        result = _best_number("")
        assert result is not None


class TestTwilioInit:
    """Tests for TwilioService initialization."""

    def _make_svc(self):
        from services.integrations.twilio_service import TwilioService
        svc = TwilioService.__new__(TwilioService)
        svc.name = "twilio"
        svc._initialized = False
        svc._account_sid = None
        svc._auth_token = None
        svc._webhook_base = None
        svc._db = None
        svc._quota_svc = None
        svc._pool_state = {}
        svc.logger = MagicMock()
        svc._config = {}
        return svc

    @pytest.mark.asyncio
    async def test_initialize_sets_credentials(self):
        svc = self._make_svc()
        env = {
            "TWILIO_ACCOUNT_SID": "ACtest123",
            "TWILIO_AUTH_TOKEN": "token456",
            "TWILIO_WEBHOOK_BASE_URL": "https://example.com",
        }
        with patch("os.getenv", side_effect=lambda k, d=None: env.get(k, d)), \
             patch("services.core.get_service", return_value=None):
            await svc._initialize()
        assert svc._account_sid == "ACtest123"
        assert svc._auth_token == "token456"
        assert svc._webhook_base == "https://example.com"

    @pytest.mark.asyncio
    async def test_initialize_missing_creds_raises(self):
        from services.core import ServiceUnavailableError
        svc = self._make_svc()
        with patch("os.getenv", return_value=None), \
             pytest.raises(ServiceUnavailableError):
            await svc._initialize()

    @pytest.mark.asyncio
    async def test_initialize_with_db_and_quota(self):
        """Initialize with database and quota services available."""
        svc = self._make_svc()
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_quota = MagicMock()
        mock_quota.is_initialized.return_value = True
        env = {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "tok1"}

        def _get_svc(name):
            if name == "database":
                return mock_db
            if name == "quota":
                return mock_quota
            return None

        with patch("os.getenv", side_effect=lambda k, d=None: env.get(k, d)), \
             patch("services.core.get_service", side_effect=_get_svc):
            await svc._initialize()
        assert svc._db is mock_db
        assert svc._quota_svc is mock_quota

    @pytest.mark.asyncio
    async def test_health_check_true(self):
        svc = self._make_svc()
        svc._account_sid = "ACtest"
        svc._auth_token = "token"
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_false(self):
        svc = self._make_svc()
        svc._account_sid = None
        svc._auth_token = None
        assert await svc._health_check() is False


class TestTwilioPoolManagement:
    """Tests for phone number pool acquire/release."""

    def _make_svc(self):
        from services.integrations.twilio_service import TwilioService
        svc = TwilioService.__new__(TwilioService)
        svc.name = "twilio"
        svc._initialized = True
        svc._pool_state = {"us_1": False, "ie_1": False}
        svc.logger = MagicMock()
        svc._config = {}
        return svc

    def test_acquire_returns_number(self):
        svc = self._make_svc()
        result = svc._acquire_number("US")
        assert result is not None
        assert svc._pool_state[result["id"]] is True  # marked in use

    def test_acquire_when_all_in_use(self):
        svc = self._make_svc()
        svc._pool_state["us_1"] = True  # only active number is in use
        result = svc._acquire_number("US")
        assert result is None

    def test_release_number(self):
        svc = self._make_svc()
        svc._pool_state["us_1"] = True
        svc._release_number("us_1")
        assert svc._pool_state["us_1"] is False

    def test_get_pool_status(self):
        svc = self._make_svc()
        status = svc.get_pool_status()
        assert "total_active" in status
        assert "total_pending" in status
        assert "available_now" in status
        assert "numbers" in status
        assert isinstance(status["numbers"], list)

    def test_add_ireland_number(self):
        from services.integrations.twilio_service import PHONE_POOL
        svc = self._make_svc()
        ie_num = next((n for n in PHONE_POOL if n["id"] == "ie_1"), None)
        original_number = ie_num["number"]
        original_active = ie_num["active"]
        try:
            svc.add_ireland_number("+353123456789")
            assert ie_num["number"] == "+353123456789"
            assert ie_num["active"] is True
        finally:
            ie_num["number"] = original_number
            ie_num["active"] = original_active

    @pytest.mark.asyncio
    async def test_number_context_acquires_and_releases(self):
        svc = self._make_svc()
        async with svc.number_context("US") as num:
            assert num is not None
            assert svc._pool_state[num["id"]] is True
        assert svc._pool_state[num["id"]] is False

    @pytest.mark.asyncio
    async def test_number_context_no_available_raises(self):
        from services.core import ServiceUnavailableError
        svc = self._make_svc()
        svc._pool_state["us_1"] = True
        with pytest.raises(ServiceUnavailableError):
            async with svc.number_context("US"):
                pass  # pragma: no cover


class TestTwilioMakeCall:
    """Tests for TwilioService.make_call."""

    def _make_svc(self):
        from services.integrations.twilio_service import TwilioService
        svc = TwilioService.__new__(TwilioService)
        svc.name = "twilio"
        svc._initialized = True
        svc._account_sid = "ACtest123"
        svc._auth_token = "token456"
        svc._webhook_base = ""
        svc._db = None
        svc._quota_svc = None
        svc._pool_state = {"us_1": False, "ie_1": False}
        svc.logger = MagicMock()
        svc._config = {}
        svc.is_initialized = MagicMock(return_value=True)
        return svc

    @pytest.mark.asyncio
    async def test_make_call_with_twiml(self):
        svc = self._make_svc()
        mock_resp = AsyncMock()
        mock_resp.status = 201
        mock_resp.json = AsyncMock(return_value={
            "sid": "CA123", "status": "initiated"
        })

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await svc.make_call("t1", "+351999", "<Response><Say>Hi</Say></Response>")

        assert result["call_sid"] == "CA123"
        assert result["status"] == "initiated"
        assert result["from_number"] == "+14064164577"

    @pytest.mark.asyncio
    async def test_make_call_no_numbers_raises(self):
        from services.core import ServiceUnavailableError
        svc = self._make_svc()
        svc._pool_state["us_1"] = True  # only active number is in use
        with pytest.raises(ServiceUnavailableError):
            await svc.make_call("t1", "+351999", "<Response/>")

    @pytest.mark.asyncio
    async def test_make_call_with_url(self):
        svc = self._make_svc()
        mock_resp = AsyncMock()
        mock_resp.status = 201
        mock_resp.json = AsyncMock(return_value={"sid": "CA456", "status": "queued"})

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await svc.make_call("t1", "+1999", "https://example.com/twiml")
        assert result["call_sid"] == "CA456"


class TestTwilioCallStatus:
    """Tests for get_call_status and hangup_call."""

    def _make_svc(self):
        from services.integrations.twilio_service import TwilioService
        svc = TwilioService.__new__(TwilioService)
        svc.name = "twilio"
        svc._initialized = True
        svc._account_sid = "ACtest"
        svc._auth_token = "token"
        svc.logger = MagicMock()
        svc._config = {}
        svc.is_initialized = MagicMock(return_value=True)
        return svc

    @pytest.mark.asyncio
    async def test_get_call_status(self):
        svc = self._make_svc()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "status": "completed", "duration": "30", "price": "-0.05",
            "price_unit": "USD", "start_time": "2025-01-01", "end_time": "2025-01-01",
        })

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await svc.get_call_status("CA123")
        assert result["status"] == "completed"
        assert result["duration"] == "30"

    @pytest.mark.asyncio
    async def test_hangup_call(self):
        svc = self._make_svc()
        mock_resp = AsyncMock()
        mock_resp.status = 200

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await svc.hangup_call("CA123")
        assert result is True


class TestTwilioTwiml:
    """Tests for TwiML helper methods."""

    def test_twiml_say(self):
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_say("Olá mundo")
        assert "<Say" in xml
        assert "Olá mundo" in xml
        assert "pt-PT" in xml

    def test_twiml_say_custom_voice(self):
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_say("Hello", language="en-US", voice="Polly.Joanna-Neural")
        assert "en-US" in xml
        assert "Polly.Joanna-Neural" in xml

    def test_twiml_restaurant_reservation_pt(self):
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_restaurant_reservation(
            "O Gato Preto", 4, "sábado às 20h", "João", language="pt-PT"
        )
        assert "O Gato Preto" not in xml  # name is in the msg, which goes to Say
        assert "4 pessoas" in xml
        assert "João" in xml
        assert "Polly.Ines-Neural" in xml

    def test_twiml_restaurant_reservation_pt_br(self):
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_restaurant_reservation(
            "Fogo de Chão", 2, "domingo", "Maria", language="pt-BR"
        )
        assert "Polly.Camila-Neural" in xml

    def test_twiml_restaurant_reservation_en(self):
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_restaurant_reservation(
            "The Blue Door", 3, "Saturday at 8pm", "John", language="en-US"
        )
        assert "3 people" in xml
        assert "John" in xml
        assert "Polly.Joanna-Neural" in xml


class TestTwilioLogCall:
    """Tests for _log_call helper."""

    def _make_svc(self):
        from services.integrations.twilio_service import TwilioService
        svc = TwilioService.__new__(TwilioService)
        svc.name = "twilio"
        svc._db = MagicMock()
        svc.logger = MagicMock()
        svc._config = {}
        return svc

    @pytest.mark.asyncio
    async def test_log_call_no_client(self):
        svc = self._make_svc()
        svc._db = None
        await svc._log_call({"call_sid": "CA123"})  # should not raise

    @pytest.mark.asyncio
    async def test_log_call_exception_swallowed(self):
        svc = self._make_svc()
        svc._db.get_client = MagicMock(return_value=None)
        await svc._log_call({"call_sid": "CA123"})  # no crash


class TestUtcnowTwilio:
    """Test _utcnow helper."""

    def test_utcnow_returns_utc(self):
        from services.integrations.twilio_service import _utcnow
        now = _utcnow()
        assert now.tzinfo == timezone.utc


# ══════════════════════════════════════════════════════════════════════════════
# QUOTA SERVICE TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestQuotaPlans:
    """Tests for plan structure."""

    def test_plans_have_required_keys(self):
        from services.business.quota_service import PLANS
        for name, plan in PLANS.items():
            assert "display_name" in plan
            assert "price_eur" in plan
            assert "quotas" in plan
            assert isinstance(plan["quotas"], dict)

    def test_all_plans_have_same_resources(self):
        from services.business.quota_service import PLANS
        keys = None
        for plan in PLANS.values():
            if keys is None:
                keys = set(plan["quotas"].keys())
            else:
                assert set(plan["quotas"].keys()) == keys

    def test_free_plan_is_cheapest(self):
        from services.business.quota_service import PLANS
        assert PLANS["free"]["price_eur"] == 0.0

    def test_everywhere_has_highest_quotas(self):
        from services.business.quota_service import PLANS
        for resource in PLANS["free"]["quotas"]:
            assert PLANS["everywhere"]["quotas"][resource] >= PLANS["free"]["quotas"][resource]


class TestQuotaExceededError:
    """Tests for QuotaExceededError."""

    def test_error_message(self):
        from services.business.quota_service import QuotaExceededError
        err = QuotaExceededError("gpt_tokens", 5000, 5000, "free")
        assert "esgotada" in str(err)
        assert "free" in str(err)

    def test_error_attributes(self):
        from services.business.quota_service import QuotaExceededError
        err = QuotaExceededError("image_gen", 2, 2, "me")
        assert err.resource == "image_gen"
        assert err.used == 2
        assert err.limit == 2
        assert err.plan == "me"


class TestQuotaHelpers:
    """Tests for static/utility methods."""

    def test_usage_dict(self):
        from services.business.quota_service import QuotaService
        d = QuotaService._usage_dict("gpt_tokens", 3000, 5000, "free")
        assert d["used"] == 3000
        assert d["limit"] == 5000
        assert d["remaining"] == 2000
        assert d["percent"] == 60.0
        assert d["exhausted"] is False

    def test_usage_dict_exhausted(self):
        from services.business.quota_service import QuotaService
        d = QuotaService._usage_dict("image_gen", 2, 2, "free")
        assert d["remaining"] == 0
        assert d["exhausted"] is True

    def test_usage_dict_zero_limit(self):
        from services.business.quota_service import QuotaService
        d = QuotaService._usage_dict("video_gen", 0, 0, "free")
        assert d["remaining"] == 0
        assert d["percent"] == 100.0

    def test_progress_bar(self):
        from services.business.quota_service import QuotaService
        bar = QuotaService._progress_bar(50.0, width=8)
        assert "█" in bar
        assert "░" in bar
        assert "50%" in bar

    def test_progress_bar_full(self):
        from services.business.quota_service import QuotaService
        bar = QuotaService._progress_bar(100.0, width=4)
        assert "████" in bar

    def test_next_reset_date(self):
        from services.business.quota_service import QuotaService
        result = QuotaService._next_reset_date()
        assert "1 de" in result
        assert "de 20" in result  # year

    def test_month_start(self):
        from services.business.quota_service import _month_start
        result = _month_start()
        assert result.endswith(":00+00:00") or "T00:00:00" in result

    def test_utcnow(self):
        from services.business.quota_service import _utcnow
        now = _utcnow()
        assert now.tzinfo == timezone.utc


class TestQuotaServiceInit:
    """Tests for QuotaService initialization."""

    def _make_svc(self):
        from services.business.quota_service import QuotaService
        svc = QuotaService.__new__(QuotaService)
        svc.name = "quota"
        svc._initialized = False
        svc._db = None
        svc._redis = None
        svc.logger = MagicMock()
        svc._config = {}
        return svc

    @pytest.mark.asyncio
    async def test_initialize_with_db(self):
        svc = self._make_svc()
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        with patch("services.core.get_service", side_effect=lambda n: mock_db if n == "database" else None):
            await svc._initialize()
        assert svc._db is mock_db

    @pytest.mark.asyncio
    async def test_initialize_redis_failure(self):
        svc = self._make_svc()
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = False
        mock_redis.initialize = AsyncMock(side_effect=Exception("redis down"))

        def _get_service(name):
            if name == "database":
                return mock_db
            if name == "redis":
                return mock_redis
            return None

        with patch("services.core.get_service", side_effect=_get_service):
            await svc._initialize()
        assert svc._redis is None  # fallen back

    @pytest.mark.asyncio
    async def test_health_check(self):
        svc = self._make_svc()
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        svc._db = mock_db
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_no_db(self):
        svc = self._make_svc()
        svc._db = None
        assert await svc._health_check() is False

    def test_get_plan_info(self):
        svc = self._make_svc()
        info = svc.get_plan_info("me")
        assert info["display_name"] == "Me"
        assert info["price_eur"] == 9.99

    def test_get_plan_info_unknown_defaults_free(self):
        svc = self._make_svc()
        info = svc.get_plan_info("nonexistent")
        assert info["display_name"] == "Free"


class TestQuotaCheckAndConsume:
    """Tests for check, consume, check_and_consume."""

    def _make_svc(self):
        from services.business.quota_service import QuotaService
        svc = QuotaService.__new__(QuotaService)
        svc.name = "quota"
        svc._initialized = True
        svc._db = MagicMock()
        svc._db.is_initialized.return_value = True
        svc._redis = None
        svc.logger = MagicMock()
        svc._config = {}
        svc.is_initialized = MagicMock(return_value=True)
        return svc

    @pytest.mark.asyncio
    async def test_check_within_quota(self):
        svc = self._make_svc()
        with patch.object(svc, "get_plan", new=AsyncMock(return_value="me")), \
             patch.object(svc, "get_quota", new=AsyncMock(return_value=50)), \
             patch.object(svc, "_get_used", new=AsyncMock(return_value=10)):
            assert await svc.check("t1", "gpt_tokens", 5) is True

    @pytest.mark.asyncio
    async def test_check_exceeds_quota(self):
        svc = self._make_svc()
        with patch.object(svc, "get_plan", new=AsyncMock(return_value="free")), \
             patch.object(svc, "get_quota", new=AsyncMock(return_value=10)), \
             patch.object(svc, "_get_used", new=AsyncMock(return_value=10)):
            assert await svc.check("t1", "image_gen", 1) is False

    @pytest.mark.asyncio
    async def test_check_zero_limit(self):
        svc = self._make_svc()
        with patch.object(svc, "get_plan", new=AsyncMock(return_value="free")), \
             patch.object(svc, "get_quota", new=AsyncMock(return_value=0)):
            assert await svc.check("t1", "video_gen", 1) is False

    @pytest.mark.asyncio
    async def test_consume(self):
        svc = self._make_svc()
        with patch.object(svc, "get_plan", new=AsyncMock(return_value="me")), \
             patch.object(svc, "_increment_usage", new=AsyncMock()), \
             patch.object(svc, "_log_usage", new=AsyncMock()), \
             patch.object(svc, "_get_used", new=AsyncMock(return_value=11)):
            result = await svc.consume("t1", "image_gen", 1)
        assert result["used"] == 11

    @pytest.mark.asyncio
    async def test_check_and_consume_ok(self):
        svc = self._make_svc()
        with patch.object(svc, "get_plan", new=AsyncMock(return_value="me")), \
             patch.object(svc, "_get_used", new=AsyncMock(return_value=5)), \
             patch.object(svc, "consume", new=AsyncMock(return_value={"used": 6})):
            result = await svc.check_and_consume("t1", "image_gen", 1)
        assert result["used"] == 6

    @pytest.mark.asyncio
    async def test_check_and_consume_zero_limit_raises(self):
        from services.business.quota_service import QuotaExceededError
        svc = self._make_svc()
        with patch.object(svc, "get_plan", new=AsyncMock(return_value="free")), \
             pytest.raises(QuotaExceededError):
            await svc.check_and_consume("t1", "video_gen", 1)

    @pytest.mark.asyncio
    async def test_check_and_consume_exceeded_raises(self):
        from services.business.quota_service import QuotaExceededError
        svc = self._make_svc()
        with patch.object(svc, "get_plan", new=AsyncMock(return_value="free")), \
             patch.object(svc, "_get_used", new=AsyncMock(return_value=2)), \
             pytest.raises(QuotaExceededError):
            await svc.check_and_consume("t1", "image_gen", 1)


class TestQuotaSummary:
    """Tests for get_summary and format_summary_telegram."""

    def _make_svc(self):
        from services.business.quota_service import QuotaService
        svc = QuotaService.__new__(QuotaService)
        svc.name = "quota"
        svc._initialized = True
        svc._db = MagicMock()
        svc._redis = None
        svc.logger = MagicMock()
        svc._config = {}
        svc.is_initialized = MagicMock(return_value=True)
        return svc

    @pytest.mark.asyncio
    async def test_get_summary_structure(self):
        svc = self._make_svc()
        mock_usage = {
            "plan": "free",
            "resources": {
                "gpt_tokens": {"used": 0, "limit": 5000, "remaining": 5000, "percent": 0},
                "image_gen": {"used": 2, "limit": 2, "remaining": 0, "percent": 100},
            },
        }
        with patch.object(svc, "get_usage", new=AsyncMock(return_value=mock_usage)):
            result = await svc.get_summary("t1")
        assert result["plan"] == "free"
        assert "image_gen" in result["exhausted_resources"]
        assert result["upgrade_available"] is True

    @pytest.mark.asyncio
    async def test_format_summary_telegram(self):
        svc = self._make_svc()
        mock_summary = {
            "plan": "free",
            "plan_display": "Free",
            "plan_description": "desc",
            "price_eur": 0.0,
            "resources": {
                "gpt_tokens": {"used": 100, "limit": 5000, "remaining": 4900, "percent": 2.0},
            },
            "exhausted_resources": [],
            "low_resources": [],
            "upgrade_available": True,
            "reset_date": "1 de Março de 2026",
        }
        with patch.object(svc, "get_summary", new=AsyncMock(return_value=mock_summary)):
            text = await svc.format_summary_telegram("t1")
        assert "Free" in text
        assert "Grátis" in text
        assert "upgrade" in text.lower() or "Upgrade" in text


class TestRequiresQuotaDecorator:
    """Tests for the @requires_quota decorator."""

    @pytest.mark.asyncio
    async def test_decorator_calls_check_and_consume(self):
        from services.business.quota_service import requires_quota
        mock_quota = AsyncMock()
        mock_quota.check_and_consume = AsyncMock()

        @requires_quota("google_places")
        async def my_method(self, tenant_id, query):
            return f"result for {query}"

        obj = MagicMock()
        with patch("services.core.get_service", return_value=mock_quota):
            result = await my_method(obj, "t1", "cafes")

        mock_quota.check_and_consume.assert_awaited_once_with("t1", "google_places", 1)
        assert result == "result for cafes"

    @pytest.mark.asyncio
    async def test_decorator_no_quota_service(self):
        from services.business.quota_service import requires_quota

        @requires_quota("maps_reqs", amount=2)
        async def my_method(self, tenant_id, query):
            return "ok"

        obj = MagicMock()
        with patch("services.core.get_service", return_value=None):
            result = await my_method(obj, "t1", "route")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_decorator_quota_exceeded_propagates(self):
        from services.business.quota_service import requires_quota, QuotaExceededError
        mock_quota = AsyncMock()
        mock_quota.check_and_consume = AsyncMock(
            side_effect=QuotaExceededError("maps_reqs", 10, 10, "free")
        )

        @requires_quota("maps_reqs")
        async def my_method(self, tenant_id):
            return "unreachable"  # pragma: no cover

        obj = MagicMock()
        with patch("services.core.get_service", return_value=mock_quota), \
             pytest.raises(QuotaExceededError):
            await my_method(obj, "t1")


class TestCumulativeStockResources:
    """Tests for resource set definitions."""

    def test_cumulative_and_stock_no_overlap(self):
        from services.business.quota_service import CUMULATIVE_RESOURCES, STOCK_RESOURCES
        assert CUMULATIVE_RESOURCES & STOCK_RESOURCES == set()

    def test_all_resources_covered(self):
        from services.business.quota_service import (
            CUMULATIVE_RESOURCES, STOCK_RESOURCES, PLANS
        )
        all_resources = set(PLANS["free"]["quotas"].keys())
        assert all_resources == CUMULATIVE_RESOURCES | STOCK_RESOURCES

    def test_resource_icons_cover_all(self):
        from services.business.quota_service import RESOURCE_ICONS, PLANS
        all_resources = set(PLANS["free"]["quotas"].keys())
        assert all_resources == set(RESOURCE_ICONS.keys())
