# utils/permissions.py
import logging
from functools import wraps
from schemas.context import UserContext

logger = logging.getLogger("capivarex.permissions")


class PermissionDeniedError(Exception):
    pass


def requires_permission(permission: str):
    """
    Decorator que verifica se o contexto do usuario (e seu device ativo)
    possui a permissao necessaria para executar a funcao.
    """
    def decorator(func):
        """Wrap *func* with a permission check before execution."""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Execute *func* only if the active device holds the required permission."""
            # Encontra o user_context nos argumentos da funcao
            user_context = None
            for arg in args:
                if isinstance(arg, UserContext):
                    user_context = arg
                    break

            if not user_context:
                raise ValueError("Funcao protegida por permissao chamada sem UserContext")

            # Assume que o device ativo e o primeiro da lista (simplificacao)
            active_device = user_context.devices[0] if user_context.devices else None

            if active_device and permission in active_device.permissions:
                return await func(*args, **kwargs)
            else:
                logger.warning(
                    "Permission '%s' denied for user %s (device: %s)",
                    permission,
                    user_context.user_id,
                    active_device.id if active_device else "none",
                )
                raise PermissionDeniedError(
                    f"Permissao '{permission}' necessaria, mas nao encontrada."
                )
        return wrapper
    return decorator
