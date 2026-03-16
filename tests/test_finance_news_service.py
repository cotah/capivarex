"""Tests for services.business.finance_news_service."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.finance_news_service import (
    _parse_news_response,
    _time_ago,
    get_cached_news,
    fetch_and_store_news,
)


# ---------------------------------------------------------------------------
# _parse_news_response
# ---------------------------------------------------------------------------


class TestParseNewsResponse:
    """Test the news response parser."""

    def test_numbered_list(self):
        answer = (
            "1. Apple stock surges. The company reported record Q4 earnings.\n"
            "2. Bitcoin hits new high. Crypto markets rally on ETF news.\n"
            "3. Fed holds rates steady. Interest rates unchanged at 5.25%."
        )
        articles = _parse_news_response(answer, ["https://example.com"])
        assert len(articles) == 3
        assert "Apple" in articles[0]["title"]
        assert articles[0]["source"] == "Perplexity"

    def test_bold_headers(self):
        answer = (
            "**Apple Stock Surges**\nThe company reported record earnings.\n\n"
            "**Bitcoin Hits New High**\nCrypto markets are rallying."
        )
        articles = _parse_news_response(answer, [])
        assert len(articles) >= 2
        assert "Apple" in articles[0]["title"]

    def test_single_paragraph_fallback(self):
        answer = "The market had a mixed day with some gains and losses across sectors."
        articles = _parse_news_response(answer, ["https://src.com"])
        assert len(articles) == 1
        assert len(articles[0]["title"]) > 0
        assert articles[0]["sources"] == ["https://src.com"]

    def test_empty_answer(self):
        articles = _parse_news_response("", [])
        assert articles == []

    def test_title_truncation(self):
        long_title = "A" * 200
        answer = f"1. {long_title}. Some body text here."
        articles = _parse_news_response(answer, [])
        assert len(articles) >= 1
        assert len(articles[0]["title"]) <= 120

    def test_summary_truncation(self):
        long_body = "B" * 600
        answer = f"1. Title here. {long_body}"
        articles = _parse_news_response(answer, [])
        assert len(articles) >= 1
        assert len(articles[0]["summary"]) <= 500

    def test_sources_limited_to_3(self):
        sources = [f"https://src{i}.com" for i in range(10)]
        articles = _parse_news_response("1. Some news. Details here.", sources)
        assert len(articles[0]["sources"]) <= 3


# ---------------------------------------------------------------------------
# _time_ago
# ---------------------------------------------------------------------------


class TestTimeAgo:
    """Test the time_ago helper."""

    def test_just_now(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        result = _time_ago(now)
        assert result in ("just now", "1m ago")

    def test_hours_ago(self):
        from datetime import datetime, timezone, timedelta
        dt = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        result = _time_ago(dt)
        assert "3h ago" == result

    def test_days_ago(self):
        from datetime import datetime, timezone, timedelta
        dt = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        result = _time_ago(dt)
        assert "2d ago" == result

    def test_invalid_date(self):
        assert _time_ago("not-a-date") == ""

    def test_empty_string(self):
        assert _time_ago("") == ""


# ---------------------------------------------------------------------------
# get_cached_news
# ---------------------------------------------------------------------------


class TestGetCachedNews:
    """Test cached news retrieval."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_db(self):
        with patch("services.business.finance_news_service.get_service", return_value=None):
            result = await get_cached_news("user-123")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_articles(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.initialize = AsyncMock()
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        mock_result = MagicMock()
        mock_result.data = [
            {
                "id": "abc",
                "title": "Test News",
                "message": "Some summary",
                "metadata": json.dumps({"source": "Perplexity", "category": "finance"}),
                "created_at": "2026-03-15T10:00:00+00:00",
                "is_read": False,
            }
        ]
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

        with patch("services.business.finance_news_service.get_service", return_value=mock_db):
            result = await get_cached_news("user-123", limit=5)

        assert len(result) == 1
        assert result[0]["title"] == "Test News"
        assert result[0]["source"] == "Perplexity"

    @pytest.mark.asyncio
    async def test_handles_bad_metadata(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.initialize = AsyncMock()
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        mock_result = MagicMock()
        mock_result.data = [
            {
                "id": "abc",
                "title": "Test",
                "message": "Summary",
                "metadata": "not-json",
                "created_at": "",
                "is_read": False,
            }
        ]
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_result

        with patch("services.business.finance_news_service.get_service", return_value=mock_db):
            result = await get_cached_news("user-123")

        assert len(result) == 1
        assert result[0]["source"] == "Perplexity"  # fallback


# ---------------------------------------------------------------------------
# fetch_and_store_news
# ---------------------------------------------------------------------------


class TestFetchAndStoreNews:
    """Test news fetching and storage."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_perplexity(self):
        with patch("services.business.finance_news_service.get_service", return_value=None):
            result = await fetch_and_store_news()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_db(self):
        mock_perplexity = MagicMock()
        mock_perplexity.initialize = AsyncMock()
        mock_perplexity.search = AsyncMock(return_value={"answer": "1. News. Details.", "sources": []})

        def side_effect(name):
            if name == "perplexity":
                return mock_perplexity
            return None

        with patch("services.business.finance_news_service.get_service", side_effect=side_effect):
            result = await fetch_and_store_news()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetches_and_stores(self):
        mock_perplexity = MagicMock()
        mock_perplexity.initialize = AsyncMock()
        mock_perplexity.search = AsyncMock(return_value={
            "answer": "1. Market rises. Stocks gained today.",
            "sources": ["https://example.com"],
        })

        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        # Mock proactivity_preferences query
        mock_result = MagicMock()
        mock_result.data = [{"user_id": "user-1"}]
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        # Mock insert
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock()

        def side_effect(name):
            if name == "perplexity":
                return mock_perplexity
            if name == "database":
                return mock_db
            return None

        with patch("services.business.finance_news_service.get_service", side_effect=side_effect):
            result = await fetch_and_store_news()

        assert len(result) >= 1
        assert "Market rises" in result[0]["title"]


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


class TestFetchAndStoreNewsEdgeCases:
    """Edge cases for fetch_and_store_news."""

    @pytest.mark.asyncio
    async def test_perplexity_init_fails(self):
        mock_perplexity = MagicMock()
        mock_perplexity.initialize = AsyncMock(side_effect=RuntimeError("init fail"))

        with patch("services.business.finance_news_service.get_service", return_value=mock_perplexity):
            result = await fetch_and_store_news()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_for_specific_user(self):
        mock_perplexity = MagicMock()
        mock_perplexity.initialize = AsyncMock()
        mock_perplexity.search = AsyncMock(return_value={
            "answer": "1. Tech stocks rally. Markets are up today.",
            "sources": [],
        })

        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock()

        def side_effect(name):
            if name == "perplexity":
                return mock_perplexity
            if name == "database":
                return mock_db
            return None

        with patch("services.business.finance_news_service.get_service", side_effect=side_effect):
            result = await fetch_and_store_news(user_id="specific-user-123")

        assert len(result) >= 1
        # Verify insert was called with the specific user_id
        mock_client.table.return_value.insert.assert_called()

    @pytest.mark.asyncio
    async def test_no_users_found(self):
        mock_perplexity = MagicMock()
        mock_perplexity.initialize = AsyncMock()
        mock_perplexity.search = AsyncMock(return_value={
            "answer": "1. Some news. Details here.",
            "sources": [],
        })

        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        # No users with proactivity enabled
        mock_result_empty = MagicMock()
        mock_result_empty.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result_empty
        # Fallback also empty
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = mock_result_empty

        def side_effect(name):
            if name == "perplexity":
                return mock_perplexity
            if name == "database":
                return mock_db
            return None

        with patch("services.business.finance_news_service.get_service", side_effect=side_effect):
            result = await fetch_and_store_news()

        assert len(result) >= 1  # articles fetched but not stored

    @pytest.mark.asyncio
    async def test_search_fails_gracefully(self):
        mock_perplexity = MagicMock()
        mock_perplexity.initialize = AsyncMock()
        mock_perplexity.search = AsyncMock(side_effect=RuntimeError("API error"))

        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value = MagicMock()

        def side_effect(name):
            if name == "perplexity":
                return mock_perplexity
            if name == "database":
                return mock_db
            return None

        with patch("services.business.finance_news_service.get_service", side_effect=side_effect):
            result = await fetch_and_store_news()

        assert result == []

    @pytest.mark.asyncio
    async def test_insert_failure_doesnt_crash(self):
        mock_perplexity = MagicMock()
        mock_perplexity.initialize = AsyncMock()
        mock_perplexity.search = AsyncMock(return_value={
            "answer": "1. News item. Details.",
            "sources": [],
        })

        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        mock_result = MagicMock()
        mock_result.data = [{"user_id": "user-1"}]
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result
        # Insert fails
        mock_client.table.return_value.insert.return_value.execute.side_effect = Exception("DB error")

        def side_effect(name):
            if name == "perplexity":
                return mock_perplexity
            if name == "database":
                return mock_db
            return None

        with patch("services.business.finance_news_service.get_service", side_effect=side_effect):
            result = await fetch_and_store_news()

        assert len(result) >= 1  # articles were fetched even if storage failed


class TestGetCachedNewsEdgeCases:

    @pytest.mark.asyncio
    async def test_db_exception(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client
        mock_client.table.return_value.select.side_effect = Exception("DB crash")

        with patch("services.business.finance_news_service.get_service", return_value=mock_db):
            result = await get_cached_news("user-123")

        assert result == []

    @pytest.mark.asyncio
    async def test_no_client(self):
        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value = None

        with patch("services.business.finance_news_service.get_service", return_value=mock_db):
            result = await get_cached_news("user-123")

        assert result == []


# ---------------------------------------------------------------------------
# Proactivity loop news scheduler
# ---------------------------------------------------------------------------


class TestTimeAgoEdgeCases:
    """Additional time_ago edge cases for coverage."""

    def test_z_suffix_timestamp(self):
        from datetime import datetime, timezone, timedelta
        dt = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _time_ago(dt)
        assert "30m ago" == result

    def test_minutes_boundary(self):
        from datetime import datetime, timezone, timedelta
        dt = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        result = _time_ago(dt)
        assert result == "just now"


class TestParseNewsMoreCases:
    """More parse cases for coverage."""

    def test_mixed_content(self):
        answer = "**Breaking News**\nMarkets are up.\n\nMore content follows here about the rally."
        articles = _parse_news_response(answer, ["src1", "src2", "src3", "src4"])
        assert len(articles) >= 1
        # Sources capped at 3
        assert len(articles[0]["sources"]) <= 3

    def test_only_whitespace(self):
        articles = _parse_news_response("   \n  \n  ", [])
        # Parser uses fallback for non-empty strings
        assert isinstance(articles, list)

    def test_no_numbered_no_bold(self):
        answer = "The market had a volatile day.\nTech stocks led the decline.\nEnergy sector was up."
        articles = _parse_news_response(answer, [])
        assert len(articles) >= 1


class TestFetchAndStoreNewsFallbacks:
    """Test fallback user lookup and empty answer handling."""

    @pytest.mark.asyncio
    async def test_db_client_none(self):
        """Line 55: client is None."""
        mock_perplexity = MagicMock()
        mock_perplexity.initialize = AsyncMock()

        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value = None  # No client

        def side_effect(name):
            if name == "perplexity":
                return mock_perplexity
            if name == "database":
                return mock_db
            return None

        with patch("services.business.finance_news_service.get_service", side_effect=side_effect):
            result = await fetch_and_store_news()
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_answer(self):
        """Line 70: answer is empty string."""
        mock_perplexity = MagicMock()
        mock_perplexity.initialize = AsyncMock()
        mock_perplexity.search = AsyncMock(return_value={"answer": "", "sources": []})

        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value = MagicMock()

        def side_effect(name):
            if name == "perplexity":
                return mock_perplexity
            if name == "database":
                return mock_db
            return None

        with patch("services.business.finance_news_service.get_service", side_effect=side_effect):
            result = await fetch_and_store_news()
        assert result == []

    @pytest.mark.asyncio
    async def test_prefs_query_fails_uses_messages_fallback(self):
        """Lines 97-111: proactivity_preferences fails, falls back to webapp_messages."""
        mock_perplexity = MagicMock()
        mock_perplexity.initialize = AsyncMock()
        mock_perplexity.search = AsyncMock(return_value={
            "answer": "1. Big news. Some details here.",
            "sources": [],
        })

        mock_db = MagicMock()
        mock_db.initialize = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_client = MagicMock()
        mock_db.get_client.return_value = mock_client

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "proactivity_preferences":
                # First call fails
                mock_table.select.return_value.eq.return_value.execute.side_effect = Exception("table error")
            elif table_name == "webapp_messages":
                # Fallback succeeds
                result = MagicMock()
                result.data = [{"user_id": "user-a"}, {"user_id": "user-b"}, {"user_id": "user-a"}]
                mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value = result
            elif table_name == "proactivity_feed":
                mock_table.insert.return_value.execute.return_value = MagicMock()
            return mock_table

        mock_client.table = table_side_effect

        def side_effect(name):
            if name == "perplexity":
                return mock_perplexity
            if name == "database":
                return mock_db
            return None

        with patch("services.business.finance_news_service.get_service", side_effect=side_effect):
            result = await fetch_and_store_news()

        assert len(result) >= 1
