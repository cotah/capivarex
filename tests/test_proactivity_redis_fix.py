"""
Tests para ProactivityService — cobrindo os bugs de Redis corrigidos.
Fase C do QA: testes reproduzem bugs ANTES de existir para garantir regressão não volta.

BUGS COBERTOS:
  1. redis_service.get_client() não existe → self._redis_client sempre None
     → filtros de anti-spam nunca funcionam
  2. Métodos sync (lrange, lpush, exists) em contexto async com RedisService Upstash
"""

from unittest.mock import AsyncMock, Mock, patch
import pytest


def _make_redis_svc(responses=None):
    """Mock do RedisService com interface async get/set/delete."""
    svc = AsyncMock()
    svc.is_initialized = Mock(return_value=True)
    svc.initialize = AsyncMock()

    # Simula storage in-memory
    _store = {}

    async def _get(key):
        return _store.get(key)

    async def _set(key, value, expire_seconds=None):
        _store[key] = value
        return True

    async def _delete(key):
        _store.pop(key, None)
        return True

    svc.get = _get
    svc.set = _set
    svc.delete = _delete
    return svc


# ── Bug 1: redis_service.get_client() não existe ──────────────────────────


def test_proactivity_service_class_importable():
    """ProactivityService deve ser importável."""
    from services.business.proactivity_service import ProactivityService

    svc = ProactivityService()
    assert svc is not None


@pytest.mark.asyncio
async def test_proactivity_initialize_without_redis():
    """ProactivityService não deve crashar quando Redis não está disponível."""
    from services.business.proactivity_service import ProactivityService

    svc = ProactivityService()
    with patch("services.business.proactivity_service.get_service", return_value=None):
        await svc._initialize()
    assert svc._openai_client is None
    assert svc._redis_client is None


@pytest.mark.asyncio
async def test_proactivity_is_notification_allowed_fail_open_without_redis():
    """
    REGRESSION BUG 1: Com Redis indisponível, is_notification_allowed deve
    retornar True (fail-open) sem exceção.
    """
    from services.business.proactivity_service import ProactivityService

    svc = ProactivityService()
    svc._redis_client = None  # Simula Redis indisponível

    result = await svc.is_notification_allowed("user_123", "alerta importante")
    assert result is True, "Deve retornar True (fail-open) quando Redis indisponível"


@pytest.mark.asyncio
async def test_proactivity_is_notification_allowed_rate_limit():
    """
    REGRESSION BUG 2: Com Redis funcionando (mock async), rate limiting deve
    bloquear após 5 notificações em 1 hora.
    BUG ORIGINAL: usava lrange() síncrono que não existia no serviço.
    FIX: usa redis_svc.get/set async.
    """
    from services.business.proactivity_service import ProactivityService
    import time

    svc = ProactivityService()
    redis_svc = _make_redis_svc()
    svc._redis_client = redis_svc

    user_id = "user_rate_limit_test"

    # Pré-preenche 5 timestamps válidos (últimos 5 minutos)
    now = time.time()
    valid_timestamps = [now - 60 * i for i in range(5)]
    await redis_svc.set(f"proactive_freq:{user_id}", valid_timestamps)

    # 6ª notificação deve ser bloqueada
    result = await svc.is_notification_allowed(user_id, "nova mensagem")
    assert result is False, "Rate limit deveria bloquear após 5 notificações/hora"


@pytest.mark.asyncio
async def test_proactivity_is_notification_allowed_deduplication():
    """
    REGRESSION BUG 3: Deduplicação deve bloquear o mesmo insight dentro de 30min.
    BUG ORIGINAL: usava redis_client.exists() síncrono.
    FIX: usa redis_svc.get() async.
    """
    from services.business.proactivity_service import ProactivityService
    import hashlib

    svc = ProactivityService()
    redis_svc = _make_redis_svc()
    svc._redis_client = redis_svc

    user_id = "user_dedup_test"
    insight = "bateria do carro em 20%"
    insight_hash = hashlib.md5(insight.encode()).hexdigest()

    # Pré-preenche deduplication key
    await redis_svc.set(f"proactive_rep:{user_id}:{insight_hash}", 1)

    # Mesmo insight deve ser bloqueado
    result = await svc.is_notification_allowed(user_id, insight)
    assert result is False, "Deduplicação deveria bloquear o mesmo insight"


@pytest.mark.asyncio
async def test_proactivity_record_notification_sent():
    """
    REGRESSION BUG 4: record_notification_sent deve registrar notificação no Redis.
    BUG ORIGINAL: usava lpush/expire/set síncronos.
    FIX: usa get/set async.
    """
    from services.business.proactivity_service import ProactivityService

    svc = ProactivityService()
    redis_svc = _make_redis_svc()
    svc._redis_client = redis_svc

    user_id = "user_record_test"
    insight = "novo alerta importante"

    # Deve registrar sem exceptions
    await svc.record_notification_sent(user_id, insight)

    # Após registrar, o mesmo insight deve ser bloqueado (deduplication)
    result_blocked = await svc.is_notification_allowed(user_id, insight)
    assert result_blocked is False, (
        "Insight recém-enviado deveria ser bloqueado por deduplicação"
    )


@pytest.mark.asyncio
async def test_proactivity_record_notification_no_redis():
    """record_notification_sent com Redis None não deve causar exceção."""
    from services.business.proactivity_service import ProactivityService

    svc = ProactivityService()
    svc._redis_client = None

    # Não deve lançar exceção
    await svc.record_notification_sent("user_123", "algum insight")
