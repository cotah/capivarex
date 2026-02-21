# -*- coding: utf-8 -*-
"""
Tests para TrackingService e TrackingAgent (17TRACK API v2).

Cobre:
  - Service: track() — auto-detect carrier
  - Service: track_with_carrier() — carrier específica
  - Service: get_quota()
  - Service: _normalize() — todos os campos
  - Service: _validate_number() — edge cases
  - Service: _resolve_carrier_code() — nome, inteiro, string numérica
  - Service: erros — 429, código rejeitado, sem dados
  - Agent: extração de código (An Post, Correios, UPS, Amazon, FedEx)
  - Agent: extração de carrier no prompt
  - Agent: intent quota
  - Agent: context override
  - Agent: mensagem de ajuda quando sem código
  - Agent: erro amigável quando API key ausente
  - Agent: formatação da resposta (emoji, ETA, histórico)
"""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx


# ─── Factories ───────────────────────────────────────────────────────────────

def _track_item(
    number="NB123456789IE",
    carrier_code=100011,
    status=20,
    sub_status="20.02",
    carrier_name="An Post",
    events=None,
    eta=None,
):
    """Simula um item 'accepted' da resposta 17TRACK."""
    events = events or [
        {
            "a": "2026-02-21T08:00:00Z",
            "b": "Parcel in transit",
            "c": "Dublin",
            "d": "Ireland",
            "z": "Parcel in transit — Dublin",
        },
        {
            "a": "2026-02-20T15:00:00Z",
            "b": "Arrived at sorting facility",
            "c": "Cork",
            "d": "Ireland",
            "z": "Arrived at sorting facility — Cork",
        },
    ]
    return {
        "number": number,
        "carrier": carrier_code,
        "track": {
            "b": status,
            "c": sub_status,
            "d": "IRL",
            "e": "CHN",
            "w1": carrier_code,
            "w2": carrier_name,
            "na": eta or "2026-02-25T00:00:00Z",
            "z0": events[0],
            "z1": events,
        },
    }


def _api_response(accepted=None, rejected=None, code=0, http_status=200):
    """Simula resposta JSON da 17TRACK."""
    resp = MagicMock()
    resp.status_code = http_status
    resp.json.return_value = {
        "code": code,
        "data": {
            "accepted": accepted or [],
            "rejected": rejected or [],
        },
    }
    resp.raise_for_status = MagicMock()
    return resp


def _quota_response(remaining=150, total=200, used=50):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "code": 0,
        "data": {
            "quotaleft": remaining,
            "quotatotal": total,
            "quotaused": used,
        },
    }
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def tracking_service():
    from services.integrations.tracking_service import TrackingService
    svc = TrackingService()
    svc._api_key = "test_17track_key"
    svc._client = AsyncMock()
    svc._initialized = True
    return svc


@pytest.fixture
def tracking_agent():
    from agents.specialized.tracking_agent import TrackingAgent
    return TrackingAgent()


@pytest.fixture
def mock_svc():
    """TrackingService mockado com dados de An Post em trânsito."""
    from services.integrations.tracking_service import TrackingService
    svc = AsyncMock(spec=TrackingService)
    svc.is_initialized.return_value = True

    tracking_data = {
        "tracking_number": "NB123456789IE",
        "carrier": "An Post",
        "carrier_code": 100011,
        "status_code": 20,
        "status_emoji": "🚚",
        "status_label": "Em trânsito",
        "sub_status": "Em trânsito internacional",
        "last_location": "Dublin",
        "last_message": "Parcel in transit — Dublin",
        "last_update": "21/02/2026 08:00",
        "estimated_delivery": "25/02/2026 00:00",
        "origin_country": "CHN",
        "destination_country": "IRL",
        "events": [
            {"date": "21/02/2026 08:00", "location": "Dublin",
             "message": "Parcel in transit — Dublin"},
            {"date": "20/02/2026 15:00", "location": "Cork",
             "message": "Arrived at sorting facility — Cork"},
        ],
        "total_events": 2,
        "delivered": False,
    }

    svc.track = AsyncMock(return_value=tracking_data)
    svc.track_with_carrier = AsyncMock(return_value=tracking_data)
    svc.get_quota = AsyncMock(return_value={
        "quota_remaining": 150,
        "quota_total": 200,
        "quota_used": 50,
    })
    return svc


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TrackingService — track()
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrackingServiceTrack:

    @pytest.mark.asyncio
    async def test_track_uses_cache_first(self, tracking_service):
        """Se já registrado, usa /gettrackinfo sem custo (não chama /getrealtimetrackinfo)."""
        item = _track_item()
        tracking_service._client.post = AsyncMock(
            return_value=_api_response(accepted=[item])
        )

        result = await tracking_service.track("NB123456789IE")

        assert result["tracking_number"] == "NB123456789IE"
        assert result["status_code"] == 20
        assert result["status_label"] == "Em trânsito"
        # Deve ter chamado /gettrackinfo (primeiro POST)
        first_call_url = str(tracking_service._client.post.call_args_list[0])
        assert "gettrackinfo" in first_call_url

    @pytest.mark.asyncio
    async def test_track_falls_back_to_realtime(self, tracking_service):
        """Se não está no cache, chama /getrealtimetrackinfo."""
        item = _track_item()
        # Primeira chamada (gettrackinfo) → vazio
        # Segunda chamada (getrealtimetrackinfo) → retorna dados
        tracking_service._client.post = AsyncMock(
            side_effect=[
                _api_response(accepted=[]),   # gettrackinfo: nada
                _api_response(accepted=[item]),  # getrealtimetrackinfo: encontrou
            ]
        )

        result = await tracking_service.track("NB123456789IE")
        assert result["status_code"] == 20
        assert tracking_service._client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_track_normalizes_to_uppercase(self, tracking_service):
        item = _track_item()
        tracking_service._client.post = AsyncMock(
            return_value=_api_response(accepted=[item])
        )
        await tracking_service.track("nb123456789ie")

        call_json = tracking_service._client.post.call_args.kwargs.get("json", [{}])
        assert call_json[0]["number"] == "NB123456789IE"

    @pytest.mark.asyncio
    async def test_track_short_code_raises(self, tracking_service):
        with pytest.raises(ValueError, match="inválido"):
            await tracking_service.track("AB1")

    @pytest.mark.asyncio
    async def test_track_too_long_raises(self, tracking_service):
        with pytest.raises(ValueError, match="inválido"):
            await tracking_service.track("A" * 51)

    @pytest.mark.asyncio
    async def test_track_429_raises_rate_limit(self, tracking_service):
        tracking_service._client.post = AsyncMock(
            return_value=_api_response(http_status=429)
        )
        with pytest.raises(RuntimeError, match="Rate limit"):
            await tracking_service.track("NB123456789IE")

    @pytest.mark.asyncio
    async def test_track_rejected_invalid_raises(self, tracking_service):
        rejected = [{"number": "INVALID", "error": {"code": -18010013, "message": "Invalid"}}]
        tracking_service._client.post = AsyncMock(
            side_effect=[
                _api_response(accepted=[]),          # gettrackinfo: nada
                _api_response(rejected=rejected),    # getrealtimetrackinfo: rejeitado
            ]
        )
        with pytest.raises(ValueError, match="inválido"):
            await tracking_service.track("INVALIDCODE")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TrackingService — track_with_carrier()
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrackingServiceWithCarrier:

    @pytest.mark.asyncio
    async def test_track_with_carrier_name(self, tracking_service):
        item = _track_item(carrier_code=100011)
        tracking_service._client.post = AsyncMock(
            return_value=_api_response(accepted=[item])
        )

        result = await tracking_service.track_with_carrier("NB123456789IE", "an post")

        assert result["carrier_code"] == 100011
        # Verifica que o carrier code foi passado no payload
        call_json = tracking_service._client.post.call_args.kwargs.get("json", [{}])
        assert call_json[0].get("carrier") == 100011

    @pytest.mark.asyncio
    async def test_track_with_carrier_int(self, tracking_service):
        item = _track_item(carrier_code=300004)
        tracking_service._client.post = AsyncMock(
            return_value=_api_response(accepted=[item])
        )

        await tracking_service.track_with_carrier("1234567890", 300004)

        call_json = tracking_service._client.post.call_args.kwargs.get("json", [{}])
        assert call_json[0].get("carrier") == 300004

    @pytest.mark.asyncio
    async def test_track_with_unknown_carrier_no_code(self, tracking_service):
        """Carrier desconhecida → não passa carrier code (auto-detect)."""
        item = _track_item()
        tracking_service._client.post = AsyncMock(
            return_value=_api_response(accepted=[item])
        )
        await tracking_service.track_with_carrier("NB123456789IE", "carrier desconhecida")

        call_json = tracking_service._client.post.call_args.kwargs.get("json", [{}])
        assert "carrier" not in call_json[0]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TrackingService — get_quota()
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrackingServiceQuota:

    @pytest.mark.asyncio
    async def test_get_quota_returns_fields(self, tracking_service):
        tracking_service._client.post = AsyncMock(
            return_value=_quota_response(150, 200, 50)
        )
        q = await tracking_service.get_quota()

        assert q["quota_remaining"] == 150
        assert q["quota_total"] == 200
        assert q["quota_used"] == 50

    @pytest.mark.asyncio
    async def test_get_quota_error_raises(self, tracking_service):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"code": 1, "data": {"msg": "erro"}}
        tracking_service._client.post = AsyncMock(return_value=resp)

        with pytest.raises(RuntimeError, match="17TRACK erro"):
            await tracking_service.get_quota()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TrackingService — _normalize()
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrackingServiceNormalize:

    def _svc(self):
        from services.integrations.tracking_service import TrackingService
        return TrackingService()

    def test_normalize_in_transit(self):
        svc = self._svc()
        item = _track_item(status=20, sub_status="20.02")
        result = svc._normalize("NB123456789IE", item)

        assert result["tracking_number"] == "NB123456789IE"
        assert result["status_code"] == 20
        assert result["status_emoji"] == "🚚"
        assert result["status_label"] == "Em trânsito"
        assert result["sub_status"] == "Em trânsito internacional"
        assert result["carrier"] == "An Post"
        assert result["delivered"] is False
        assert result["total_events"] == 2
        assert result["estimated_delivery"] == "25/02/2026 00:00"

    def test_normalize_delivered(self):
        svc = self._svc()
        item = _track_item(status=40, sub_status="40.01")
        result = svc._normalize("NB123456789IE", item)

        assert result["status_emoji"] == "✅"
        assert result["status_label"] == "Entregue"
        assert result["sub_status"] == "Entregue ao destinatário"
        assert result["delivered"] is True

    def test_normalize_exception(self):
        svc = self._svc()
        item = _track_item(status=60, sub_status="60.02")
        result = svc._normalize("NB123456789IE", item)

        assert result["status_emoji"] == "❌"
        assert result["sub_status"] == "Perdido"

    def test_normalize_empty_events(self):
        svc = self._svc()
        item = _track_item(events=[])
        item["track"]["z0"] = {}
        item["track"]["z1"] = []
        result = svc._normalize("NB123456789IE", item)

        assert result["events"] == []
        assert result["total_events"] == 0
        assert result["last_message"] == ""

    def test_normalize_all_status_codes(self):
        from services.integrations.tracking_service import _STATUS_MAP
        svc = self._svc()
        for code in _STATUS_MAP:
            item = _track_item(status=code, sub_status="")
            result = svc._normalize("TEST12345", item)
            assert result["status_code"] == code
            assert result["status_emoji"]
            assert result["status_label"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TrackingService — helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrackingServiceHelpers:

    def test_fmt_date_utc(self):
        from services.integrations.tracking_service import _fmt_date
        assert _fmt_date("2026-02-21T10:30:00Z") == "21/02/2026 10:30"

    def test_fmt_date_none(self):
        from services.integrations.tracking_service import _fmt_date
        assert _fmt_date(None) == ""

    def test_fmt_date_empty(self):
        from services.integrations.tracking_service import _fmt_date
        assert _fmt_date("") == ""

    def test_validate_number_valid(self):
        from services.integrations.tracking_service import TrackingService
        svc = TrackingService()
        svc._validate_number("NB123456789IE")  # não deve levantar

    def test_validate_number_too_short(self):
        from services.integrations.tracking_service import TrackingService
        svc = TrackingService()
        with pytest.raises(ValueError):
            svc._validate_number("AB1")

    def test_validate_number_too_long(self):
        from services.integrations.tracking_service import TrackingService
        svc = TrackingService()
        with pytest.raises(ValueError):
            svc._validate_number("A" * 51)

    def test_resolve_carrier_code_name(self):
        from services.integrations.tracking_service import TrackingService
        svc = TrackingService()
        assert svc._resolve_carrier_code("an post") == 100011
        assert svc._resolve_carrier_code("dhl") == 300004
        assert svc._resolve_carrier_code("correios") == 3011

    def test_resolve_carrier_code_int(self):
        from services.integrations.tracking_service import TrackingService
        svc = TrackingService()
        assert svc._resolve_carrier_code(100011) == 100011

    def test_resolve_carrier_code_numeric_string(self):
        from services.integrations.tracking_service import TrackingService
        svc = TrackingService()
        assert svc._resolve_carrier_code("100011") == 100011

    def test_resolve_carrier_code_unknown(self):
        from services.integrations.tracking_service import TrackingService
        svc = TrackingService()
        assert svc._resolve_carrier_code("carrier desconhecida") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TrackingAgent — extração de código
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrackingAgentExtraction:

    @pytest.fixture
    def agent(self):
        from agents.specialized.tracking_agent import TrackingAgent
        return TrackingAgent()

    def test_extract_an_post_ie(self, agent):
        assert agent._extract_tracking_number("Rastreia NB123456789IE") == "NB123456789IE"

    def test_extract_correios_br(self, agent):
        assert agent._extract_tracking_number("tracking QR123456789BR") == "QR123456789BR"

    def test_extract_ups(self, agent):
        assert agent._extract_tracking_number("onde está 1Z999AA10123456784") == "1Z999AA10123456784"

    def test_extract_amazon(self, agent):
        assert agent._extract_tracking_number("TBA123456789000") == "TBA123456789000"

    def test_extract_fedex_numeric(self, agent):
        assert agent._extract_tracking_number("fedex 123456789012") == "123456789012"

    def test_extract_china_post(self, agent):
        assert agent._extract_tracking_number("RA123456789CN em trânsito") == "RA123456789CN"

    def test_extract_not_found(self, agent):
        assert agent._extract_tracking_number("qual o clima em Dublin?") is None

    def test_extract_carrier_an_post(self, agent):
        result = agent._extract_carrier("rastreia pela an post", {})
        assert result == 100011

    def test_extract_carrier_dhl(self, agent):
        result = agent._extract_carrier("rastreia pelo dhl", {})
        assert result == 300004

    def test_extract_carrier_correios(self, agent):
        result = agent._extract_carrier("rastreia pelos correios", {})
        assert result == 3011

    def test_extract_carrier_context_override(self, agent):
        result = agent._extract_carrier("texto qualquer", {"carrier": 300002})
        assert result == 300002

    def test_extract_carrier_not_found(self, agent):
        result = agent._extract_carrier("rastreia meu pacote", {})
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TrackingAgent — intents
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrackingAgentIntents:

    @pytest.mark.asyncio
    async def test_track_by_number(self, tracking_agent, mock_svc):
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute("Rastreia NB123456789IE", {})
        assert r.is_success()
        mock_svc.track.assert_called_once_with("NB123456789IE")

    @pytest.mark.asyncio
    async def test_track_with_carrier_in_prompt(self, tracking_agent, mock_svc):
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute(
                "Rastreia NB123456789IE pela An Post", {}
            )
        assert r.is_success()
        mock_svc.track_with_carrier.assert_called_once_with("NB123456789IE", 100011)

    @pytest.mark.asyncio
    async def test_track_context_override(self, tracking_agent, mock_svc):
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute(
                "rastreia",
                {"tracking_number": "NB123456789IE"},
            )
        assert r.is_success()

    @pytest.mark.asyncio
    async def test_track_bare_code(self, tracking_agent, mock_svc):
        """Prompt é só o código de rastreio."""
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute("NB123456789IE", {})
        assert r.is_success()

    @pytest.mark.asyncio
    async def test_quota_intent(self, tracking_agent, mock_svc):
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute("Quanto de quota me resta?", {})
        assert r.is_success()
        mock_svc.get_quota.assert_called_once()
        assert "150" in r.response
        assert "17TRACK" in r.response

    @pytest.mark.asyncio
    async def test_no_tracking_number_returns_help(self, tracking_agent, mock_svc):
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute("onde está meu pacote?", {})
        assert not r.is_success()
        assert "NB" in r.response or "código" in r.response.lower()

    @pytest.mark.asyncio
    async def test_service_unavailable(self, tracking_agent):
        with patch("agents.specialized.tracking_agent.get_service", return_value=None):
            r = await tracking_agent.execute("Rastreia NB123456789IE", {})
        assert not r.is_success()

    @pytest.mark.asyncio
    async def test_api_key_missing_friendly_error(self, tracking_agent):
        svc = AsyncMock()
        svc.is_initialized = MagicMock(return_value=False)
        svc.initialize = AsyncMock(
            side_effect=RuntimeError("17TRACK_API_KEY não encontrada")
        )
        with patch("agents.specialized.tracking_agent.get_service", return_value=svc):
            r = await tracking_agent.execute("Rastreia NB123456789IE", {})
        assert not r.is_success()
        assert "17TRACK_API_KEY" in r.response or "configurado" in r.response.lower()

    @pytest.mark.asyncio
    async def test_invalid_code_error(self, tracking_agent, mock_svc):
        mock_svc.track.side_effect = ValueError(
            "Código 'INVALIDO' inválido ou transportadora não suportada."
        )
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute("Rastreia INVALIDO12345", {})
        assert not r.is_success()
        assert "inválido" in r.response.lower()

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, tracking_agent, mock_svc):
        mock_svc.track.side_effect = RuntimeError("Rate limit da 17TRACK (3 req/s).")
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute("Rastreia NB123456789IE", {})
        assert not r.is_success()
        assert "Rate limit" in r.response or "rate" in r.response.lower()

    @pytest.mark.asyncio
    async def test_response_contains_status_emoji(self, tracking_agent, mock_svc):
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute("NB123456789IE", {})
        assert "🚚" in r.response

    @pytest.mark.asyncio
    async def test_response_contains_eta(self, tracking_agent, mock_svc):
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute("NB123456789IE", {})
        assert "25/02/2026" in r.response

    @pytest.mark.asyncio
    async def test_response_delivered(self, tracking_agent, mock_svc):
        delivered = {**mock_svc.track.return_value,
                     "status_code": 40, "status_emoji": "✅",
                     "status_label": "Entregue", "delivered": True}
        mock_svc.track.return_value = delivered
        with patch("agents.specialized.tracking_agent.get_service", return_value=mock_svc):
            r = await tracking_agent.execute("NB123456789IE", {})
        assert "✅" in r.response
        assert "entregue" in r.response.lower()

    def test_capabilities(self, tracking_agent):
        caps = tracking_agent.get_capabilities()
        assert "track_package" in caps
        assert "auto_detect_carrier" in caps
        assert "check_quota" in caps
