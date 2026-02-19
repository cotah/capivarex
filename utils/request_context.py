# utils/request_context.py
import uuid
import structlog.contextvars


def bind_request_id():
    """Gera um novo request_id e o binda ao contexto do structlog."""
    request_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    return request_id
