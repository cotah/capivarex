"""
Tests para BaseAgent e BaseService — cobertura de ciclo de vida e retry logic.
Adicionado na Fase C do QA.
"""
import pytest
from agents.core import AgentStatus, AgentResponse


# ── BaseAgent ─────────────────────────────────────────────────────────────

class ConcreteAgent:
    """Agente concreto mínimo para testes de BaseAgent."""

    def __new__(cls):
        from agents.core import BaseAgent, AgentStatus, AgentResponse

        class _Agent(BaseAgent):
            def __init__(self):
                super().__init__(name="test", description="Test agent")

            async def execute(self, prompt, context):
                if prompt == "error":
                    raise RuntimeError("test error")
                return AgentResponse(status=AgentStatus.SUCCESS, response="ok")

        return _Agent()


def test_agent_repr():
    """BaseAgent __repr__ deve incluir nome."""
    agent = ConcreteAgent()
    assert "test" in repr(agent)


def test_agent_initial_metrics():
    """Métricas iniciais do agente devem ser zeradas."""
    agent = ConcreteAgent()
    metrics = agent.get_metrics()
    assert metrics["execution_count"] == 0
    assert metrics["error_count"] == 0
    assert metrics["error_rate"] == 0.0


@pytest.mark.asyncio
async def test_agent_process_increments_counter():
    """process() deve incrementar execution_count."""
    agent = ConcreteAgent()
    await agent.process("hello", {})
    assert agent._execution_count == 1


@pytest.mark.asyncio
async def test_agent_process_empty_prompt_returns_error():
    """process() com prompt vazio deve retornar ERROR."""
    agent = ConcreteAgent()
    result = await agent.process("", {})
    assert result.status == AgentStatus.ERROR
    assert "empty" in result.response.lower() or "invalid" in result.response.lower()


@pytest.mark.asyncio
async def test_agent_process_invalid_context_returns_error():
    """process() com context não-dict deve retornar ERROR."""
    agent = ConcreteAgent()
    result = await agent.process("hello", "not_a_dict")  # type: ignore
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_agent_process_exception_returns_error():
    """process() com exceção em execute() deve retornar ERROR graciosamente."""
    agent = ConcreteAgent()
    result = await agent.process("error", {})
    assert result.status == AgentStatus.ERROR
    assert result.error is not None


@pytest.mark.asyncio
async def test_agent_error_count_increments_on_exception():
    """_error_count deve incrementar quando execute() lança exceção."""
    agent = ConcreteAgent()
    await agent.process("error", {})
    assert agent._error_count == 1
    assert agent._execution_count == 1


def test_agent_response_is_success():
    """AgentResponse.is_success() deve retornar True para SUCCESS."""
    resp = AgentResponse(status=AgentStatus.SUCCESS, response="ok")
    assert resp.is_success() is True
    assert AgentResponse(status=AgentStatus.ERROR, response="err").is_success() is False


def test_agent_response_to_dict():
    """AgentResponse.to_dict() deve incluir todos os campos."""
    resp = AgentResponse(
        status=AgentStatus.SUCCESS,
        response="test",
        data={"key": "val"},
        error=None,
        metadata={"type": "chat"}
    )
    d = resp.to_dict()
    assert d["status"] == "success"
    assert d["response"] == "test"
    assert d["data"] == {"key": "val"}
    assert "timestamp" in d


# ── BaseService ─────────────────────────────────────────────────────────────

class ConcreteService:
    """Serviço concreto mínimo para testes de BaseService."""

    def __new__(cls, fail_init=False):
        from services.core import BaseService

        class _Service(BaseService):
            def __init__(self):
                super().__init__(name="test_svc")
                self.fail_init = fail_init

            async def _initialize(self):
                if self.fail_init:
                    raise RuntimeError("init failed")

            async def _health_check(self):
                return True

        svc = _Service()
        svc.fail_init = fail_init
        return svc


@pytest.mark.asyncio
async def test_service_initialize_sets_flag():
    """initialize() deve setar _initialized = True."""
    svc = ConcreteService()
    await svc.initialize()
    assert svc.is_initialized() is True
    assert svc.is_healthy() is True


@pytest.mark.asyncio
async def test_service_double_initialize_is_safe():
    """Chamar initialize() duas vezes não deve causar erro."""
    svc = ConcreteService()
    await svc.initialize()
    await svc.initialize()  # segunda chamada deve ser no-op
    assert svc.is_initialized() is True


@pytest.mark.asyncio
async def test_service_initialize_failure_raises():
    """initialize() com falha deve propagar ServiceConfigurationError."""
    from services.core import ServiceConfigurationError
    svc = ConcreteService(fail_init=True)
    svc.fail_init = True  # garante o flag

    # Forçar o fail_init no svc gerado
    async def failing_init():
        raise RuntimeError("init failed")

    svc._initialize = failing_init

    with pytest.raises(ServiceConfigurationError):
        await svc.initialize()


@pytest.mark.asyncio
async def test_service_health_check():
    """health_check() deve retornar HEALTHY para serviço saudável."""
    from services.core import ServiceStatus
    svc = ConcreteService()
    await svc.initialize()
    status = await svc.health_check()
    assert status == ServiceStatus.HEALTHY


def test_service_metrics_structure():
    """get_metrics() deve retornar dicionário com campos esperados."""
    svc = ConcreteService()
    m = svc.get_metrics()
    assert "name" in m
    assert "status" in m
    assert "initialized" in m
    assert "call_count" in m
    assert "error_rate" in m


# ── retry_on_failure decorator ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_on_failure_retries_on_timeout():
    """retry_on_failure deve retry em asyncio.TimeoutError."""
    import asyncio
    from services.core import retry_on_failure

    call_count = 0

    @retry_on_failure(max_retries=2, backoff_factor=0.01)
    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise asyncio.TimeoutError()
        return "ok"

    result = await flaky()
    assert result == "ok"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_on_failure_does_not_retry_value_error():
    """retry_on_failure NÃO deve retry em erros não-transientes (ValueError)."""
    from services.core import retry_on_failure

    call_count = 0

    @retry_on_failure(max_retries=3, backoff_factor=0.01)
    async def always_fail():
        nonlocal call_count
        call_count += 1
        raise ValueError("invalid input")

    with pytest.raises(ValueError):
        await always_fail()

    # Não deve ter retentado (ValueError não é retryable)
    assert call_count == 1
