"""Unit tests for the permissions decorator."""

import pytest
from utils.permissions import requires_permission, PermissionDeniedError
from schemas.context import UserContext, Device


def _make_context(permissions=None):
    """Create a UserContext with a device holding given permissions."""
    devices = []
    if permissions is not None:
        devices = [Device(type="mobile", id="phone", permissions=permissions)]
    return UserContext(
        user_id="u1",
        telegram_chat_id=123,
        full_name="Test",
        devices=devices,
    )


class TestRequiresPermission:
    @pytest.mark.asyncio
    async def test_permission_granted(self):
        @requires_permission("read_calendar")
        async def protected(ctx):
            return "ok"

        ctx = _make_context(permissions=["read_calendar", "write_calendar"])
        result = await protected(ctx)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_permission_denied(self):
        @requires_permission("admin")
        async def protected(ctx):
            return "ok"

        ctx = _make_context(permissions=["read_calendar"])
        with pytest.raises(PermissionDeniedError, match="admin"):
            await protected(ctx)

    @pytest.mark.asyncio
    async def test_no_devices_denied(self):
        @requires_permission("read")
        async def protected(ctx):
            return "ok"

        ctx = _make_context(permissions=None)
        # No devices at all
        ctx.devices = []
        with pytest.raises(PermissionDeniedError):
            await protected(ctx)

    @pytest.mark.asyncio
    async def test_no_context_raises_value_error(self):
        @requires_permission("read")
        async def protected(x):
            return "ok"

        with pytest.raises(ValueError, match="UserContext"):
            await protected("not_a_context")

    @pytest.mark.asyncio
    async def test_context_in_kwargs(self):
        """Permission check finds UserContext in positional args."""
        @requires_permission("write")
        async def protected(a, b, ctx):
            return "ok"

        ctx = _make_context(permissions=["write"])
        result = await protected("a", "b", ctx)
        assert result == "ok"
