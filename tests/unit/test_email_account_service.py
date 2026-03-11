"""Unit tests for email_account_service."""

import pytest
from unittest.mock import MagicMock, Mock, patch

MODULE = "services.business.email_account_service"


def _chain(data):
    result = Mock()
    result.data = data
    return result


def _mock_sb(return_data):
    sb = MagicMock()
    chain = MagicMock()
    sb.table.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.insert.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = _chain(return_data)
    return sb


class TestGetEmailAccounts:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        rows = [{"account": "gmail", "email_address": "a@b.com"}]
        sb = _mock_sb(rows)
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.email_account_service import get_email_accounts

            result = await get_email_accounts("u1")
        assert result == rows

    @pytest.mark.asyncio
    async def test_db_none_returns_empty(self):
        with patch(f"{MODULE}.get_supabase_client", return_value=None):
            from services.business.email_account_service import get_email_accounts

            result = await get_email_accounts("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        sb = MagicMock()
        sb.table.side_effect = Exception("db error")
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.email_account_service import get_email_accounts

            result = await get_email_accounts("u1")
        assert result == []


class TestAddEmailAccount:
    @pytest.mark.asyncio
    async def test_adds_and_returns_row(self):
        row = {"user_id": "u1", "account": "gmail", "email_address": "a@b.com"}
        sb = _mock_sb([row])
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.email_account_service import add_email_account

            result = await add_email_account("u1", "gmail", "a@b.com")
        assert result == row

    @pytest.mark.asyncio
    async def test_db_none_returns_empty(self):
        with patch(f"{MODULE}.get_supabase_client", return_value=None):
            from services.business.email_account_service import add_email_account

            result = await add_email_account("u1", "gmail", "a@b.com")
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty(self):
        sb = _mock_sb([])
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.email_account_service import add_email_account

            result = await add_email_account("u1", "gmail", "a@b.com")
        assert result == {}

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        sb = MagicMock()
        sb.table.side_effect = Exception("db error")
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.email_account_service import add_email_account

            result = await add_email_account("u1", "gmail", "a@b.com")
        assert result == {}


class TestSaveReply:
    @pytest.mark.asyncio
    async def test_saves_without_raising(self):
        sb = _mock_sb(None)
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.email_account_service import save_reply

            await save_reply("u1", "gmail", "to@b.com", "Subject", "Body")
        sb.table.assert_called_with("email_replies")

    @pytest.mark.asyncio
    async def test_db_none_does_not_raise(self):
        with patch(f"{MODULE}.get_supabase_client", return_value=None):
            from services.business.email_account_service import save_reply

            await save_reply("u1", "gmail", "to@b.com", "Subject", "Body")

    @pytest.mark.asyncio
    async def test_exception_does_not_raise(self):
        sb = MagicMock()
        sb.table.side_effect = Exception("db error")
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.email_account_service import save_reply

            await save_reply("u1", "gmail", "to@b.com", "Subject", "Body")


class TestGetSentReplies:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        rows = [{"to_email": "a@b.com", "subject": "Hi"}]
        sb = _mock_sb(rows)
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.email_account_service import get_sent_replies

            result = await get_sent_replies("u1")
        assert result == rows

    @pytest.mark.asyncio
    async def test_db_none_returns_empty(self):
        with patch(f"{MODULE}.get_supabase_client", return_value=None):
            from services.business.email_account_service import get_sent_replies

            result = await get_sent_replies("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        sb = MagicMock()
        sb.table.side_effect = Exception("db error")
        with patch(f"{MODULE}.get_supabase_client", return_value=sb):
            from services.business.email_account_service import get_sent_replies

            result = await get_sent_replies("u1")
        assert result == []
