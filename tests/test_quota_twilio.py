# -*- coding: utf-8 -*-
"""
tests/test_quota_twilio.py
===========================
Testes unitários para QuotaService e TwilioService.

Cobertura QuotaService:
- Planos Free/Me/Everywhere: todos os 18 recursos presentes e correctos
- Recursos cumulativos vs stock correctamente classificados
- check(): tem/não tem quota, limite zero
- consume(): incrementa e loga
- check_and_consume(): sucesso e QuotaExceededError
- get_summary(): campos e flags correctos
- format_summary_telegram(): categorias, ícones, upgrade
- _progress_bar() e _usage_dict()
- _next_reset_date()
- requires_quota decorator

Cobertura TwilioService:
- Pool: acquire, release, best country, sem números
- add_ireland_number(): activa slot IE
- get_pool_status(): contagens correctas
- make_call(): sucesso, quota excedida, sem números, liberta após erro
- Preferência IE para destinos europeus quando IE activo
- TwiML: say, restaurant_reservation (PT e EN)
- get_call_status(), hangup_call()
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Fixtures ────────────────────────────────────────────────────────────────

ALL_RESOURCES = [
    "gpt_tokens", "image_gen", "video_gen",
    "twilio_mins", "elevenlabs_chars",
    "google_places", "maps_reqs", "search_reqs",
    "weather_reqs", "crypto_reqs", "youtube_reqs",
    "translate_reqs", "tracking_reqs", "perplexity_reqs",
    "smartcar_reqs", "mercado_scans",
    "reminders", "notes",
]

FREE_BLOCKED = ["twilio_mins", "elevenlabs_chars", "video_gen", "smartcar_reqs"]


def _quota_svc(plan="me", used=0):
    from services.business.quota_service import QuotaService
    svc = QuotaService.__new__(QuotaService)
    svc.name = "quota"
    svc.logger = MagicMock()
    svc._initialized = True
    svc._db = MagicMock()
    svc._redis = None
    svc.get_plan = AsyncMock(return_value=plan)
    svc._get_used = AsyncMock(return_value=used)
    svc._increment_usage = AsyncMock()
    svc._log_usage = AsyncMock()
    return svc


def _twilio_svc(quota_svc=None):
    from services.integrations.twilio_service import TwilioService, PHONE_POOL
    svc = TwilioService.__new__(TwilioService)
    svc.name = "twilio"
    svc.logger = MagicMock()
    svc._account_sid = "ACtest"
    svc._auth_token = "token"
    svc._webhook_base = ""
    svc._db = None
    svc._quota_svc = quota_svc
    svc._initialized = True
    svc._pool_state = {n["id"]: False for n in PHONE_POOL}
    svc._log_call = AsyncMock()
    return svc


def _twilio_http_mock(status=201, sid="CAtest123", call_status="initiated"):
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value={"sid": sid, "status": call_status})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    session = AsyncMock()
    session.post = MagicMock(return_value=resp)
    session.get = MagicMock(return_value=resp)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.fixture(autouse=True)
def _reset_phone_pool():
    """Reset PHONE_POOL global state after each test to avoid mutation leaks."""
    from services.integrations.twilio_service import PHONE_POOL
    import copy
    original = copy.deepcopy(PHONE_POOL)
    yield
    for i, entry in enumerate(original):
        PHONE_POOL[i].update(entry)


# ─── PLANS estrutura ─────────────────────────────────────────────────────────

class TestPlansStructure:

    def test_three_plans_exist(self):
        from services.business.quota_service import PLANS
        assert set(PLANS.keys()) == {"free", "me", "everywhere"}

    def test_all_18_resources_in_every_plan(self):
        from services.business.quota_service import PLANS
        for plan_name, plan in PLANS.items():
            for res in ALL_RESOURCES:
                assert res in plan["quotas"], (
                    f"Plano '{plan_name}' não tem recurso '{res}'"
                )

    def test_everywhere_always_gte_me(self):
        from services.business.quota_service import PLANS
        for res in ALL_RESOURCES:
            assert (
                PLANS["everywhere"]["quotas"][res]
                >= PLANS["me"]["quotas"][res]
            ), f"everywhere[{res}] < me[{res}]"

    def test_me_always_gte_free(self):
        from services.business.quota_service import PLANS
        for res in ALL_RESOURCES:
            assert (
                PLANS["me"]["quotas"][res]
                >= PLANS["free"]["quotas"][res]
            ), f"me[{res}] < free[{res}]"

    def test_free_blocked_resources_are_zero(self):
        from services.business.quota_service import PLANS
        for res in FREE_BLOCKED:
            assert PLANS["free"]["quotas"][res] == 0, (
                f"free[{res}] deveria ser 0"
            )

    def test_prices_correct(self):
        from services.business.quota_service import PLANS
        assert PLANS["free"]["price_eur"] == 0.0
        assert PLANS["me"]["price_eur"] == 9.99
        assert PLANS["everywhere"]["price_eur"] == 29.99

    def test_display_names(self):
        from services.business.quota_service import PLANS
        assert PLANS["free"]["display_name"] == "Free"
        assert PLANS["me"]["display_name"] == "Me"
        assert PLANS["everywhere"]["display_name"] == "Everywhere"


# ─── CUMULATIVE vs STOCK ─────────────────────────────────────────────────────

class TestResourceClassification:

    def test_stock_resources(self):
        from services.business.quota_service import STOCK_RESOURCES
        assert "reminders" in STOCK_RESOURCES
        assert "notes" in STOCK_RESOURCES

    def test_cumulative_resources_count(self):
        from services.business.quota_service import CUMULATIVE_RESOURCES
        # 18 total - 2 stock = 16 cumulativos
        assert len(CUMULATIVE_RESOURCES) == 16

    def test_twilio_is_cumulative(self):
        from services.business.quota_service import CUMULATIVE_RESOURCES
        assert "twilio_mins" in CUMULATIVE_RESOURCES

    def test_gpt_is_cumulative(self):
        from services.business.quota_service import CUMULATIVE_RESOURCES
        assert "gpt_tokens" in CUMULATIVE_RESOURCES

    def test_notes_not_cumulative(self):
        from services.business.quota_service import CUMULATIVE_RESOURCES
        assert "notes" not in CUMULATIVE_RESOURCES


# ─── RESOURCE_ICONS ──────────────────────────────────────────────────────────

class TestResourceIcons:

    def test_all_resources_have_icons(self):
        from services.business.quota_service import RESOURCE_ICONS
        for res in ALL_RESOURCES:
            assert res in RESOURCE_ICONS, f"'{res}' sem ícone"

    def test_icons_not_empty(self):
        from services.business.quota_service import RESOURCE_ICONS
        for res, icon in RESOURCE_ICONS.items():
            assert len(icon) > 2, f"Ícone de '{res}' parece vazio"


# ─── _usage_dict e _progress_bar ─────────────────────────────────────────────

class TestStaticHelpers:

    def test_usage_dict_normal(self):
        from services.business.quota_service import QuotaService
        d = QuotaService._usage_dict("twilio_mins", 10, 60, "me")
        assert d["used"] == 10
        assert d["limit"] == 60
        assert d["remaining"] == 50
        assert d["percent"] == pytest.approx(16.7, abs=0.1)
        assert d["exhausted"] is False

    def test_usage_dict_exhausted(self):
        from services.business.quota_service import QuotaService
        d = QuotaService._usage_dict("twilio_mins", 60, 60, "me")
        assert d["remaining"] == 0
        assert d["exhausted"] is True

    def test_usage_dict_zero_limit(self):
        from services.business.quota_service import QuotaService
        d = QuotaService._usage_dict("twilio_mins", 0, 0, "free")
        assert d["remaining"] == 0
        assert d["percent"] == 100.0
        assert d["exhausted"] is False  # 0 limite não conta como esgotado

    def test_progress_bar_empty(self):
        from services.business.quota_service import QuotaService
        bar = QuotaService._progress_bar(0)
        assert "░" in bar
        assert "█" not in bar

    def test_progress_bar_full(self):
        from services.business.quota_service import QuotaService
        bar = QuotaService._progress_bar(100)
        assert "█" in bar
        assert "░" not in bar

    def test_progress_bar_half(self):
        from services.business.quota_service import QuotaService
        bar = QuotaService._progress_bar(50)
        assert "█" in bar
        assert "░" in bar

    def test_next_reset_date_format(self):
        from services.business.quota_service import QuotaService
        date = QuotaService._next_reset_date()
        assert "de" in date
        assert any(m in date for m in [
            "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
        ])


# ─── QuotaExceededError ──────────────────────────────────────────────────────

class TestQuotaExceededError:

    def test_fields(self):
        from services.business.quota_service import QuotaExceededError
        e = QuotaExceededError("twilio_mins", 15, 15, "me")
        assert e.resource == "twilio_mins"
        assert e.used == 15
        assert e.limit == 15
        assert e.plan == "me"

    def test_message_has_plan_and_resource_icon(self):
        from services.business.quota_service import QuotaExceededError
        e = QuotaExceededError("twilio_mins", 15, 15, "me")
        msg = str(e)
        assert "me" in msg
        assert "Chamadas" in msg  # ícone do twilio_mins
        assert "upgrade" in msg.lower()

    def test_is_exception(self):
        from services.business.quota_service import QuotaExceededError
        e = QuotaExceededError("notes", 100, 100, "me")
        assert isinstance(e, Exception)


# ─── QuotaService async ──────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestQuotaServiceCheck:

    async def test_check_has_quota(self):
        svc = _quota_svc(plan="me", used=5)
        assert await svc.check("t1", "twilio_mins", 1) is True

    async def test_check_no_quota_free_blocked(self):
        svc = _quota_svc(plan="free", used=0)
        assert await svc.check("t1", "twilio_mins", 1) is False

    async def test_check_no_quota_exceeded(self):
        from services.business.quota_service import PLANS
        limit = PLANS["me"]["quotas"]["twilio_mins"]
        svc = _quota_svc(plan="me", used=limit)
        assert await svc.check("t1", "twilio_mins", 1) is False

    async def test_check_everywhere_weather(self):
        svc = _quota_svc(plan="everywhere", used=0)
        assert await svc.check("t1", "weather_reqs", 1) is True

    async def test_check_free_mercado(self):
        svc = _quota_svc(plan="free", used=2)
        assert await svc.check("t1", "mercado_scans", 1) is True  # free tem 3

    async def test_check_free_mercado_exhausted(self):
        svc = _quota_svc(plan="free", used=3)
        assert await svc.check("t1", "mercado_scans", 1) is False


@pytest.mark.asyncio
class TestQuotaServiceConsume:

    async def test_consume_calls_increment_and_log(self):
        svc = _quota_svc(plan="me", used=5)
        await svc.consume("t1", "google_places", 1)
        svc._increment_usage.assert_called_once_with("t1", "google_places", 1)
        svc._log_usage.assert_called_once()

    async def test_consume_returns_usage_dict(self):
        svc = _quota_svc(plan="me", used=10)
        result = await svc.consume("t1", "weather_reqs", 1)
        assert "used" in result
        assert "limit" in result
        assert "remaining" in result

    async def test_consume_multiple_amount(self):
        svc = _quota_svc(plan="me", used=0)
        await svc.consume("t1", "gpt_tokens", 500)
        svc._increment_usage.assert_called_once_with("t1", "gpt_tokens", 500)


@pytest.mark.asyncio
class TestQuotaServiceCheckAndConsume:

    async def test_success(self):
        svc = _quota_svc(plan="me", used=5)
        result = await svc.check_and_consume("t1", "twilio_mins", 1)
        assert result is not None
        svc._increment_usage.assert_called_once()

    async def test_raises_when_zero_limit(self):
        from services.business.quota_service import QuotaExceededError
        svc = _quota_svc(plan="free", used=0)
        with pytest.raises(QuotaExceededError) as exc:
            await svc.check_and_consume("t1", "twilio_mins", 1)
        assert exc.value.resource == "twilio_mins"
        assert exc.value.plan == "free"

    async def test_raises_when_exceeded(self):
        from services.business.quota_service import PLANS, QuotaExceededError
        limit = PLANS["me"]["quotas"]["google_places"]
        svc = _quota_svc(plan="me", used=limit)
        with pytest.raises(QuotaExceededError):
            await svc.check_and_consume("t1", "google_places", 1)

    async def test_does_not_consume_when_exceeded(self):
        from services.business.quota_service import PLANS, QuotaExceededError
        limit = PLANS["me"]["quotas"]["twilio_mins"]
        svc = _quota_svc(plan="me", used=limit)
        with pytest.raises(QuotaExceededError):
            await svc.check_and_consume("t1", "twilio_mins", 1)
        svc._increment_usage.assert_not_called()

    async def test_smartcar_free_blocked(self):
        from services.business.quota_service import QuotaExceededError
        svc = _quota_svc(plan="free", used=0)
        with pytest.raises(QuotaExceededError):
            await svc.check_and_consume("t1", "smartcar_reqs", 1)

    async def test_video_gen_free_blocked(self):
        from services.business.quota_service import QuotaExceededError
        svc = _quota_svc(plan="free", used=0)
        with pytest.raises(QuotaExceededError):
            await svc.check_and_consume("t1", "video_gen", 1)


@pytest.mark.asyncio
class TestQuotaServiceSummary:

    async def _make_summary_svc(self, plan="me"):
        from services.business.quota_service import PLANS, QuotaService
        svc = _quota_svc(plan=plan, used=0)

        async def mock_get_usage(tenant_id, resource=None):
            quotas = PLANS[plan]["quotas"]
            if resource:
                return QuotaService._usage_dict(resource, 0, quotas.get(resource, 0), plan)
            return {
                "plan": plan,
                "resources": {
                    res: QuotaService._usage_dict(res, 0, lim, plan)
                    for res, lim in quotas.items()
                },
            }

        svc.get_usage = mock_get_usage
        return svc

    async def test_summary_has_required_fields(self):
        svc = await self._make_summary_svc("me")
        summary = await svc.get_summary("t1")
        for field in ["plan", "plan_display", "price_eur", "resources",
                      "exhausted_resources", "low_resources",
                      "reset_date", "upgrade_available"]:
            assert field in summary

    async def test_summary_everywhere_no_upgrade(self):
        svc = await self._make_summary_svc("everywhere")
        summary = await svc.get_summary("t1")
        assert summary["upgrade_available"] is False

    async def test_summary_free_has_upgrade(self):
        svc = await self._make_summary_svc("free")
        summary = await svc.get_summary("t1")
        assert summary["upgrade_available"] is True

    async def test_summary_all_resources_present(self):
        svc = await self._make_summary_svc("me")
        summary = await svc.get_summary("t1")
        for res in ALL_RESOURCES:
            assert res in summary["resources"], f"'{res}' ausente do summary"

    async def test_format_telegram_has_categories(self):
        svc = await self._make_summary_svc("me")
        text = await svc.format_summary_telegram("t1")
        assert "Inteligência Artificial" in text
        assert "Comunicação" in text
        assert "Localização" in text
        assert "Serviços Externos" in text
        assert "Dados Pessoais" in text

    async def test_format_telegram_has_plan_price(self):
        svc = await self._make_summary_svc("me")
        text = await svc.format_summary_telegram("t1")
        assert "Me" in text
        assert "€9.99" in text

    async def test_format_telegram_free_blocked_shown(self):
        svc = await self._make_summary_svc("free")
        text = await svc.format_summary_telegram("t1")
        assert "❌ Não incluído" in text

    async def test_format_telegram_upgrade_shown_for_me(self):
        svc = await self._make_summary_svc("me")
        text = await svc.format_summary_telegram("t1")
        assert "Everywhere" in text

    async def test_format_telegram_reset_date(self):
        svc = await self._make_summary_svc("me")
        text = await svc.format_summary_telegram("t1")
        assert "Reset" in text or "reset" in text.lower()


# ─── requires_quota decorator ────────────────────────────────────────────────

@pytest.mark.asyncio
class TestRequiresQuotaDecorator:

    async def test_passes_when_quota_ok(self):
        from services.business.quota_service import requires_quota

        class FakeSvc:
            @requires_quota("google_places")
            async def search(self, tenant_id, query):
                return f"results:{query}"

        quota_mock = AsyncMock()
        quota_mock.check_and_consume = AsyncMock(return_value={"used": 1})

        with patch("services.core.get_service", return_value=quota_mock):
            result = await FakeSvc().search("t1", "pizza")

        assert result == "results:pizza"
        quota_mock.check_and_consume.assert_called_once_with("t1", "google_places", 1)

    async def test_raises_when_exceeded(self):
        from services.business.quota_service import requires_quota, QuotaExceededError

        class FakeSvc:
            @requires_quota("twilio_mins")
            async def call(self, tenant_id):
                return "called"

        quota_mock = AsyncMock()
        quota_mock.check_and_consume = AsyncMock(
            side_effect=QuotaExceededError("twilio_mins", 15, 15, "me")
        )

        with patch("services.core.get_service", return_value=quota_mock):
            with pytest.raises(QuotaExceededError):
                await FakeSvc().call("t1")

    async def test_skips_check_when_no_quota_svc(self):
        from services.business.quota_service import requires_quota

        class FakeSvc:
            @requires_quota("weather_reqs")
            async def weather(self, tenant_id):
                return "rainy"

        with patch("services.core.get_service", return_value=None):
            result = await FakeSvc().weather("t1")

        assert result == "rainy"

    async def test_custom_amount(self):
        from services.business.quota_service import requires_quota

        class FakeSvc:
            @requires_quota("gpt_tokens", amount=500)
            async def chat(self, tenant_id, msg):
                return "ok"

        quota_mock = AsyncMock()
        quota_mock.check_and_consume = AsyncMock(return_value={"used": 500})

        with patch("services.core.get_service", return_value=quota_mock):
            await FakeSvc().chat("t1", "olá")

        quota_mock.check_and_consume.assert_called_once_with("t1", "gpt_tokens", 500)


# ─── TwilioService pool ──────────────────────────────────────────────────────

class TestTwilioPool:

    def test_us_number_active(self):
        from services.integrations.twilio_service import PHONE_POOL
        us = next(n for n in PHONE_POOL if n["id"] == "us_1")
        assert us["active"] is True
        assert us["number"] == "+14064164577"

    def test_ie_slot_pending(self):
        from services.integrations.twilio_service import PHONE_POOL
        ie = next(n for n in PHONE_POOL if n["id"] == "ie_1")
        assert ie["active"] is False
        assert ie["number"] is None

    def test_acquire_us_number(self):
        svc = _twilio_svc()
        num = svc._acquire_number("US")
        assert num is not None
        assert num["number"] == "+14064164577"
        assert svc._pool_state["us_1"] is True

    def test_acquire_fallback_when_no_regional(self):
        svc = _twilio_svc()
        num = svc._acquire_number("JP")
        assert num is not None  # US como fallback

    def test_acquire_returns_none_when_all_in_use(self):
        svc = _twilio_svc()
        for k in svc._pool_state:
            svc._pool_state[k] = True
        assert svc._acquire_number("US") is None

    def test_release_frees_number(self):
        svc = _twilio_svc()
        svc._pool_state["us_1"] = True
        svc._release_number("us_1")
        assert svc._pool_state["us_1"] is False

    def test_add_ireland_number_activates(self):
        from services.integrations.twilio_service import PHONE_POOL
        svc = _twilio_svc()
        svc.add_ireland_number("+353539407368")
        ie = next(n for n in PHONE_POOL if n["id"] == "ie_1")
        assert ie["active"] is True
        assert ie["number"] == "+353539407368"

    def test_pool_status_counts(self):
        svc = _twilio_svc()
        status = svc.get_pool_status()
        assert status["total_active"] >= 1
        assert status["total_pending"] >= 1
        assert "numbers" in status
        assert "pending" in status

    def test_pool_status_available_decreases_in_use(self):
        svc = _twilio_svc()
        before = svc.get_pool_status()["available_now"]
        svc._pool_state["us_1"] = True
        after = svc.get_pool_status()["available_now"]
        assert after == before - 1


# ─── TwilioService.make_call ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTwilioMakeCall:

    async def test_make_call_success(self):
        svc = _twilio_svc()
        with patch("aiohttp.ClientSession", return_value=_twilio_http_mock(201)):
            result = await svc.make_call(
                "t1", "+351910000001", "<Response/>", destination_country="US"
            )
        assert result["call_sid"] == "CAtest123"
        assert result["status"] == "initiated"
        assert result["from_number"] == "+14064164577"
        svc._log_call.assert_called_once()

    async def test_make_call_with_url(self):
        svc = _twilio_svc()
        with patch("aiohttp.ClientSession", return_value=_twilio_http_mock(201)):
            result = await svc.make_call(
                "t1", "+351910000001",
                "https://myapp.com/twiml/reserve"
            )
        assert result["call_sid"] == "CAtest123"

    async def test_make_call_releases_after_success(self):
        svc = _twilio_svc()
        with patch("aiohttp.ClientSession", return_value=_twilio_http_mock(201)):
            await svc.make_call("t1", "+351910000001", "<Response/>")
        assert svc._pool_state["us_1"] is False

    async def test_make_call_releases_after_error(self):
        svc = _twilio_svc()
        with patch("aiohttp.ClientSession", return_value=_twilio_http_mock(400)):
            with pytest.raises(RuntimeError):
                await svc.make_call("t1", "+351910000001", "<Response/>")
        assert svc._pool_state["us_1"] is False

    async def test_make_call_quota_exceeded(self):
        from services.business.quota_service import QuotaExceededError
        quota_mock = AsyncMock()
        quota_mock.check_and_consume = AsyncMock(
            side_effect=QuotaExceededError("twilio_mins", 15, 15, "me")
        )
        svc = _twilio_svc(quota_svc=quota_mock)
        with pytest.raises(QuotaExceededError):
            await svc.make_call("t1", "+351910000001", "<Response/>")

    async def test_make_call_no_numbers_raises(self):
        from services.core import ServiceUnavailableError
        svc = _twilio_svc()
        for k in svc._pool_state:
            svc._pool_state[k] = True
        with pytest.raises(ServiceUnavailableError, match="pool"):
            await svc.make_call("t1", "+351910000001", "<Response/>")

    async def test_make_call_prefers_ie_for_europe(self):
        svc = _twilio_svc()
        svc.add_ireland_number("+353539407368")
        with patch("aiohttp.ClientSession", return_value=_twilio_http_mock(201)):
            result = await svc.make_call(
                "t1", "+351910000001", "<Response/>",
                destination_country="PT"
            )
        assert result["from_number"] == "+353539407368"

    async def test_make_call_falls_back_to_us_when_ie_pending(self):
        svc = _twilio_svc()
        # IE ainda pendente (default)
        with patch("aiohttp.ClientSession", return_value=_twilio_http_mock(201)):
            result = await svc.make_call(
                "t1", "+351910000001", "<Response/>",
                destination_country="PT"
            )
        assert result["from_number"] == "+14064164577"

    async def test_make_call_result_has_all_fields(self):
        svc = _twilio_svc()
        with patch("aiohttp.ClientSession", return_value=_twilio_http_mock(201)):
            result = await svc.make_call("t1", "+351910000001", "<Response/>")
        for field in ["call_sid", "status", "from_number", "to_number",
                      "tenant_id", "created_at"]:
            assert field in result


# ─── TwilioService.get_call_status e hangup ──────────────────────────────────

@pytest.mark.asyncio
class TestTwilioCallOps:

    def _svc(self):
        from services.integrations.twilio_service import TwilioService
        svc = TwilioService.__new__(TwilioService)
        svc.name = "twilio"
        svc.logger = MagicMock()
        svc._account_sid = "ACtest"
        svc._auth_token = "token"
        svc._initialized = True
        svc._pool_state = {}
        return svc

    async def test_get_call_status_completed(self):
        svc = self._svc()
        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={
            "sid": "CAtest123", "status": "completed",
            "duration": "90", "price": "-0.015", "price_unit": "USD",
        })
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        session = AsyncMock()
        session.get = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=session):
            status = await svc.get_call_status("CAtest123")

        assert status["status"] == "completed"
        assert status["duration"] == "90"
        assert status["price"] == "-0.015"

    async def test_hangup_returns_true(self):
        svc = self._svc()
        resp = AsyncMock()
        resp.status = 200
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        session = AsyncMock()
        session.post = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=session):
            assert await svc.hangup_call("CAtest123") is True

    async def test_hangup_returns_false_on_error(self):
        svc = self._svc()
        resp = AsyncMock()
        resp.status = 404
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        session = AsyncMock()
        session.post = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=session):
            assert await svc.hangup_call("CAtest123") is False


# ─── TwiML helpers ───────────────────────────────────────────────────────────

class TestTwiML:

    def test_twiml_say_has_xml_header(self):
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_say("Olá!")
        assert "<?xml" in xml
        assert "<Response>" in xml
        assert "<Say" in xml
        assert "Olá!" in xml

    def test_twiml_say_default_portuguese(self):
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_say("Olá!")
        assert "pt-PT" in xml
        assert "Ines" in xml

    def test_twiml_say_custom_language(self):
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_say("Hello!", language="en-US", voice="Polly.Joanna-Neural")
        assert "en-US" in xml
        assert "Joanna" in xml

    def test_twiml_reservation_pt_has_client_name(self):
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_restaurant_reservation(
            "Tasca do João", 2, "sábado às 20h", "Henrique"
        )
        assert "Henrique" in xml
        assert "2" in xml
        assert "pt-PT" in xml

    def test_twiml_reservation_en_has_client_name(self):
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_restaurant_reservation(
            "The Pub", 4, "Saturday at 8pm", "John", language="en-US"
        )
        assert "John" in xml
        assert "4" in xml
        assert "en-US" in xml

    def test_twiml_reservation_is_valid_xml(self):
        import xml.etree.ElementTree as ET
        from services.integrations.twilio_service import TwilioService
        xml = TwilioService.twiml_restaurant_reservation(
            "Restaurante X", 2, "amanhã às 19h", "Ana"
        )
        # Não deve levantar excepção
        ET.fromstring(xml)


# ─── Supplementary: _best_number, _utcnow, init, health, context, log ──────

class TestBestNumber:
    """Tests for module-level _best_number helper."""

    def test_regional_match(self):
        from services.integrations.twilio_service import _best_number
        result = _best_number("US")
        assert result is not None
        assert result["country"] == "US"

    def test_fallback_when_no_regional(self):
        from services.integrations.twilio_service import _best_number
        result = _best_number("JP")
        assert result is not None  # US como fallback

    def test_no_available_numbers(self):
        from services.integrations.twilio_service import PHONE_POOL, _best_number
        orig_states = [(n["active"], n["number"]) for n in PHONE_POOL]
        for n in PHONE_POOL:
            n["active"] = False
        try:
            assert _best_number("US") is None
        finally:
            for n, (a, num) in zip(PHONE_POOL, orig_states):
                n["active"] = a
                n["number"] = num

    def test_default_country(self):
        from services.integrations.twilio_service import _best_number
        result = _best_number("")
        assert result is not None


class TestUtcnowHelpers:
    """Tests for _utcnow helpers."""

    def test_twilio_utcnow(self):
        from services.integrations.twilio_service import _utcnow
        from datetime import timezone
        dt = _utcnow()
        assert dt.tzinfo == timezone.utc

    def test_quota_utcnow(self):
        from services.business.quota_service import _utcnow
        from datetime import timezone
        dt = _utcnow()
        assert dt.tzinfo == timezone.utc

    def test_month_start(self):
        from services.business.quota_service import _month_start
        ms = _month_start()
        assert "T00:00:00" in ms


@pytest.mark.asyncio
class TestTwilioInit:

    async def test_initialize_sets_credentials(self):
        from services.integrations.twilio_service import TwilioService
        svc = TwilioService.__new__(TwilioService)
        svc.name = "twilio"
        svc.logger = MagicMock()
        svc._initialized = False
        svc._pool_state = {}

        db_mock = MagicMock()
        db_mock.is_initialized.return_value = True
        quota_mock = MagicMock()
        quota_mock.is_initialized.return_value = True

        with patch.dict("os.environ", {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "tok",
            "TWILIO_WEBHOOK_BASE_URL": "https://x.com",
        }), patch("services.core.get_service", side_effect=lambda n: {
            "database": db_mock, "quota": quota_mock
        }.get(n)):
            await svc._initialize()

        assert svc._account_sid == "ACtest"
        assert svc._auth_token == "tok"
        assert svc._db == db_mock
        assert svc._quota_svc == quota_mock

    async def test_initialize_missing_creds_raises(self):
        from services.integrations.twilio_service import TwilioService
        from services.core import ServiceUnavailableError
        svc = TwilioService.__new__(TwilioService)
        svc.name = "twilio"
        svc.logger = MagicMock()
        svc._initialized = False
        svc._pool_state = {}

        with patch.dict("os.environ", {}, clear=True), \
             patch("services.core.get_service", return_value=None):
            with pytest.raises(ServiceUnavailableError):
                await svc._initialize()

    async def test_health_check(self):
        svc = _twilio_svc()
        assert await svc._health_check() is True
        svc._account_sid = None
        assert await svc._health_check() is False


@pytest.mark.asyncio
class TestTwilioNumberContext:

    async def test_number_context_acquires_and_releases(self):
        svc = _twilio_svc()
        async with svc.number_context("US") as num:
            assert num["number"] == "+14064164577"
            assert svc._pool_state["us_1"] is True
        assert svc._pool_state["us_1"] is False

    async def test_number_context_raises_when_empty(self):
        from services.core import ServiceUnavailableError
        svc = _twilio_svc()
        for k in svc._pool_state:
            svc._pool_state[k] = True
        with pytest.raises(ServiceUnavailableError):
            async with svc.number_context("US"):
                pass


@pytest.mark.asyncio
class TestTwilioLogCall:

    async def test_log_call_no_client(self):
        from services.integrations.twilio_service import TwilioService
        svc = TwilioService.__new__(TwilioService)
        svc.name = "twilio"
        svc.logger = MagicMock()
        svc._db = None
        svc._initialized = True
        svc._pool_state = {}
        # Should not raise, just return
        await svc._log_call({"call_sid": "CA123"})

    async def test_log_call_exception_warns(self):
        from services.integrations.twilio_service import TwilioService
        svc = TwilioService.__new__(TwilioService)
        svc.name = "twilio"
        svc.logger = MagicMock()
        db_mock = MagicMock()
        db_mock.get_client.return_value.table.return_value.insert.side_effect = Exception("db fail")
        svc._db = db_mock
        svc._initialized = True
        svc._pool_state = {}
        await svc._log_call({"call_sid": "CA123"})
        svc.logger.warning.assert_called()


class TestQuotaInit:

    @pytest.mark.asyncio
    async def test_initialize_with_db_and_redis(self):
        from services.business.quota_service import QuotaService
        svc = QuotaService.__new__(QuotaService)
        svc.name = "quota"
        svc.logger = MagicMock()
        svc._initialized = False

        db_mock = MagicMock()
        db_mock.is_initialized.return_value = True
        redis_mock = MagicMock()
        redis_mock.is_initialized.return_value = True

        with patch("services.core.get_service", side_effect=lambda n: {
            "database": db_mock, "redis": redis_mock
        }.get(n)):
            await svc._initialize()

        assert svc._db == db_mock
        assert svc._redis == redis_mock

    @pytest.mark.asyncio
    async def test_initialize_redis_failure(self):
        from services.business.quota_service import QuotaService
        svc = QuotaService.__new__(QuotaService)
        svc.name = "quota"
        svc.logger = MagicMock()
        svc._initialized = False

        db_mock = MagicMock()
        db_mock.is_initialized.return_value = True
        redis_mock = MagicMock()
        redis_mock.is_initialized.side_effect = Exception("redis down")

        with patch("services.core.get_service", side_effect=lambda n: {
            "database": db_mock, "redis": redis_mock
        }.get(n)):
            await svc._initialize()

        assert svc._db == db_mock
        assert svc._redis is None  # cleared on failure

    @pytest.mark.asyncio
    async def test_health_check(self):
        svc = _quota_svc()
        svc._db = MagicMock()
        svc._db.is_initialized.return_value = True
        assert await svc._health_check() is True

    def test_get_plan_info(self):
        svc = _quota_svc()
        info = svc.get_plan_info("me")
        assert info["display_name"] == "Me"
        assert info["price_eur"] == 9.99

    def test_get_plan_info_unknown_defaults_free(self):
        svc = _quota_svc()
        info = svc.get_plan_info("nonexistent")
        assert info["display_name"] == "Free"
