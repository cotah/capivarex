"""Tests for travel planner service — trip detection and proactive alerts."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.travel_planner_service import (
    detect_upcoming_trips,
    generate_trip_alert,
    _detect_destination,
    _has_trip_keywords,
    _extract_destination_from_text,
    _parse_date,
    gather_travel_profile,
    build_preference_questions,
    build_itinerary,
    _build_research_query,
    generate_trip_summary,
    adjust_itinerary,
    finalize_itinerary,
)


# We'll need to import this after defining it
def _make_event(summary, location="", start_days=20, duration_days=7, description=""):
    """Helper: create a calendar event dict for testing."""
    start = datetime.now(timezone.utc) + timedelta(days=start_days)
    end = start + timedelta(days=duration_days)
    return {
        "id": f"evt_{summary[:10].replace(' ', '_')}",
        "summary": summary,
        "location": location,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "description": description,
        "attendees": [],
    }


class TestDestinationDetection:
    """Tests for destination and keyword detection."""

    def test_detect_known_destination(self):
        assert _detect_destination("thailand trip", "", "") == "Thailand"

    def test_detect_city_in_location(self):
        result = _detect_destination("", "bangkok, thailand", "")
        assert result in ("Bangkok", "Thailand")

    def test_detect_destination_in_description(self):
        assert _detect_destination("holiday", "", "flying to tokyo") == "Tokyo"

    def test_no_destination(self):
        assert _detect_destination("team meeting", "office", "discuss Q4") is None

    def test_trip_keywords(self):
        assert _has_trip_keywords("viagem para o porto", "", "") is True
        assert _has_trip_keywords("vacation in bali", "", "") is True
        assert _has_trip_keywords("flight to london", "", "") is True
        assert _has_trip_keywords("hotel booking", "", "") is True
        assert _has_trip_keywords("team standup", "office", "agenda") is False

    def test_extract_destination_from_summary(self):
        assert "Porto" in _extract_destination_from_text("trip to porto", "")

    def test_extract_destination_from_location(self):
        assert "Paris" in _extract_destination_from_text("holiday", "paris, france")

    def test_extract_destination_fallback(self):
        result = _extract_destination_from_text("férias em lisboa", "")
        assert "Lisboa" in result


class TestDateParsing:
    """Tests for date parsing."""

    def test_parse_iso_datetime(self):
        dt = _parse_date("2026-04-15T10:00:00+00:00")
        assert dt is not None
        assert dt.month == 4
        assert dt.day == 15

    def test_parse_date_only(self):
        dt = _parse_date("2026-04-15")
        assert dt is not None
        assert dt.day == 15

    def test_parse_none(self):
        assert _parse_date(None) is None
        assert _parse_date("") is None

    def test_parse_invalid(self):
        assert _parse_date("not a date") is None


class TestDetectUpcomingTrips:
    """Tests for the main trip detection function."""

    @pytest.mark.asyncio
    async def test_detect_trip_by_location(self):
        """Detects trip when location is a known destination."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            _make_event("Holiday", location="Bangkok, Thailand", start_days=20, duration_days=10),
        ])

        with patch("services.business.travel_planner_service.get_service", return_value=mock_cal):
            trips = await detect_upcoming_trips("user-123")

        assert len(trips) == 1
        assert "Bangkok" in trips[0]["destination"] or "Thailand" in trips[0]["destination"]
        assert trips[0]["duration_days"] == 10

    @pytest.mark.asyncio
    async def test_detect_trip_by_keyword(self):
        """Detects trip when summary has travel keywords."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            _make_event("Viagem para a Tailândia", start_days=18, duration_days=14),
        ])

        with patch("services.business.travel_planner_service.get_service", return_value=mock_cal):
            trips = await detect_upcoming_trips("user-123")

        assert len(trips) == 1
        assert trips[0]["duration_days"] == 14

    @pytest.mark.asyncio
    async def test_skip_short_events(self):
        """Events shorter than 3 days are skipped."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            _make_event("Trip to Paris", location="Paris", start_days=20, duration_days=1),
        ])

        with patch("services.business.travel_planner_service.get_service", return_value=mock_cal):
            trips = await detect_upcoming_trips("user-123")

        assert len(trips) == 0  # Too short

    @pytest.mark.asyncio
    async def test_skip_too_soon(self):
        """Events less than 14 days away are skipped."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            _make_event("Trip to Tokyo", location="Tokyo", start_days=5, duration_days=7),
        ])

        with patch("services.business.travel_planner_service.get_service", return_value=mock_cal):
            trips = await detect_upcoming_trips("user-123")

        assert len(trips) == 0  # Too soon

    @pytest.mark.asyncio
    async def test_skip_non_trip_events(self):
        """Regular meetings are not detected as trips."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            _make_event("Q4 Planning Week", location="Office", start_days=20, duration_days=5),
        ])

        with patch("services.business.travel_planner_service.get_service", return_value=mock_cal):
            trips = await detect_upcoming_trips("user-123")

        assert len(trips) == 0

    @pytest.mark.asyncio
    async def test_no_calendar_service(self):
        """Returns empty when calendar not available."""
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            trips = await detect_upcoming_trips("user-123")
        assert trips == []

    @pytest.mark.asyncio
    async def test_multiple_trips(self):
        """Detects multiple trips."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            _make_event("Trip to Japan", location="Tokyo", start_days=18, duration_days=10),
            _make_event("Holiday in Bali", location="Bali, Indonesia", start_days=25, duration_days=7),
            _make_event("Team meeting", location="Office", start_days=20, duration_days=1),
        ])

        with patch("services.business.travel_planner_service.get_service", return_value=mock_cal):
            trips = await detect_upcoming_trips("user-123")

        assert len(trips) == 2  # Two trips, meeting excluded


class TestTripAlert:
    """Tests for proactive alert generation."""

    @pytest.mark.asyncio
    async def test_generate_alert_fallback(self):
        """Alert generates with fallback when GPT unavailable."""
        trip = {
            "event_id": "evt-123",
            "summary": "Thailand trip",
            "destination": "Thailand",
            "start_date": "Mar 15",
            "end_date": "Apr 15",
            "duration_days": 30,
            "days_until": 20,
            "location": "Bangkok",
            "start": "2026-03-15T00:00:00",
            "end": "2026-04-15T00:00:00",
        }

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()

        def fake_svc(name):
            return mock_db if name == "database" else None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            result = await generate_trip_alert(
                user_id="user-123",
                trip=trip,
                user_name="Marcos Silva",
            )

        assert result is not None
        assert "Thailand" in result["message"]
        assert "Marcos" in result["message"]

    @pytest.mark.asyncio
    async def test_deduplication(self):
        """Alert not sent twice for same event."""
        trip = {"event_id": "evt-123", "destination": "Paris", "start": "", "end": "",
                "duration_days": 5, "summary": "Paris", "location": "Paris",
                "start_date": "Apr 1", "end_date": "Apr 6", "days_until": 20}

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "1", "metadata": '{"event_id": "evt-123"}'}]
        )

        with patch("services.business.travel_planner_service.get_service", return_value=mock_db):
            result = await generate_trip_alert("user-123", trip, "Marcos")

        assert result is None  # Already sent

    @pytest.mark.asyncio
    async def test_alert_no_db(self):
        """Alert works even without DB (no dedup, no store)."""
        trip = {"event_id": "evt-456", "destination": "Lisbon", "start": "", "end": "",
                "duration_days": 4, "summary": "Lisbon trip", "location": "Lisbon",
                "start_date": "May 1", "end_date": "May 5", "days_until": 18}

        with patch("services.business.travel_planner_service.get_service", return_value=None):
            result = await generate_trip_alert("user-123", trip, "Ana")

        assert result is not None
        assert "Lisbon" in result["message"]


class TestHelpers:
    """Tests for helper functions."""

    @pytest.mark.asyncio
    async def test_trip_alert_sent_no_db(self):
        from services.business.travel_planner_service import _trip_alert_sent
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            assert await _trip_alert_sent("u1", "evt-1") is False

    @pytest.mark.asyncio
    async def test_store_trip_alert_no_db(self):
        from services.business.travel_planner_service import _store_trip_alert
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            await _store_trip_alert("u1", "evt-1", "t", "m", {})  # Should not crash


class TestCheckTravelForAllUsers:
    """Tests for the proactivity loop runner."""

    @pytest.mark.asyncio
    async def test_no_db(self):
        from services.business.travel_planner_service import check_travel_for_all_users
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            result = await check_travel_for_all_users()
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_users(self):
        from services.business.travel_planner_service import check_travel_for_all_users
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_all_users_with_proactivity_enabled = AsyncMock(return_value=[])

        with patch("services.business.travel_planner_service.get_service", return_value=mock_db):
            result = await check_travel_for_all_users()
        assert result == 0

    @pytest.mark.asyncio
    async def test_humanize_trip_alert_no_gpt(self):
        """Fallback produces warm message without GPT."""
        from services.business.travel_planner_service import _humanize_trip_alert
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            result = await _humanize_trip_alert(
                "User: Test\nDestination: Bali", "Test", "Bali", 7
            )
        assert "Bali" in result
        assert "Test" in result
        assert "✈️" in result

    @pytest.mark.asyncio
    async def test_detect_trip_by_description(self):
        """Detects trip when description has destination."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            _make_event("Férias", description="flying to lisbon portugal", start_days=20, duration_days=5),
        ])

        with patch("services.business.travel_planner_service.get_service", return_value=mock_cal):
            trips = await detect_upcoming_trips("user-123")

        assert len(trips) == 1

    @pytest.mark.asyncio
    async def test_detect_trip_with_flight_keyword(self):
        """Detects trip with 'voo' keyword even without known destination."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            _make_event("Voo para Marrakech", start_days=20, duration_days=5),
        ])

        with patch("services.business.travel_planner_service.get_service", return_value=mock_cal):
            trips = await detect_upcoming_trips("user-123")

        assert len(trips) == 1
        assert trips[0]["duration_days"] == 5

    @pytest.mark.asyncio
    async def test_check_travel_with_users_and_trips(self):
        """Full flow: users with proactivity → calendar → trip detected → alert sent."""
        from services.business.travel_planner_service import check_travel_for_all_users

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_all_users_with_proactivity_enabled = AsyncMock(return_value=[
            {"user_id": "user-abc"},
        ])
        mock_db.get_user_by_id = AsyncMock(return_value={
            "full_name": "Ana Costa", "telegram_chat_id": None,
        })
        # For dedup check: not sent yet
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        # For store
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()

        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            _make_event("Férias em Lisboa", location="Lisbon, Portugal", start_days=20, duration_days=7),
        ])

        def fake_svc(name):
            if name == "database":
                return mock_db
            if name == "calendar":
                return mock_cal
            return None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            alerts = await check_travel_for_all_users()

        assert alerts == 1

    @pytest.mark.asyncio
    async def test_store_trip_alert_with_db(self):
        """Store actually writes to proactivity_feed."""
        from services.business.travel_planner_service import _store_trip_alert
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()

        with patch("services.business.travel_planner_service.get_service", return_value=mock_db):
            await _store_trip_alert("u1", "evt-1", "Trip!", "msg", {"destination": "Paris"})

        mock_db.get_client.return_value.table.assert_called_with("proactivity_feed")

    @pytest.mark.asyncio
    async def test_trip_alert_sent_found(self):
        """Dedup returns True when alert already sent."""
        from services.business.travel_planner_service import _trip_alert_sent
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "1", "metadata": '{"event_id": "evt-match"}'}]
        )

        with patch("services.business.travel_planner_service.get_service", return_value=mock_db):
            result = await _trip_alert_sent("u1", "evt-match")
        assert result is True

    @pytest.mark.asyncio
    async def test_trip_alert_sent_not_found(self):
        """Dedup returns False when different event_id."""
        from services.business.travel_planner_service import _trip_alert_sent
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "1", "metadata": '{"event_id": "evt-other"}'}]
        )

        with patch("services.business.travel_planner_service.get_service", return_value=mock_db):
            result = await _trip_alert_sent("u1", "evt-new")
        assert result is False


# ===========================================================================
# Phase 2 — Preference Gathering + Itinerary Building
# ===========================================================================

class TestGatherTravelProfile:
    """Tests for profile gathering from RAG + user_context."""

    @pytest.mark.asyncio
    async def test_profile_defaults_no_services(self):
        """Returns empty profile when no services available."""
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            profile = await gather_travel_profile("user-123")

        assert profile["travel_style"] == ""
        assert profile["budget_level"] == ""
        assert profile["interests"] == []

    @pytest.mark.asyncio
    async def test_profile_from_user_context(self):
        """Loads saved preferences from user_context."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"context_data": '{"travel_style": "adventurous", "budget_level": "mid-range"}'}]
        )

        with patch("services.business.travel_planner_service.get_service", return_value=mock_db):
            profile = await gather_travel_profile("user-123")

        assert profile["travel_style"] == "adventurous"
        assert profile["budget_level"] == "mid-range"

    @pytest.mark.asyncio
    async def test_profile_with_rag(self):
        """RAG context is included when available."""
        mock_rag = MagicMock()
        mock_rag.is_initialized.return_value = True
        mock_rag.search = AsyncMock(return_value=[
            {"content": "User loves hiking and Japanese food"},
        ])

        def fake_svc(name):
            return mock_rag if name == "rag" else None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            profile = await gather_travel_profile("user-123")

        assert "_rag_context" in profile
        assert "hiking" in profile["_rag_context"]


class TestPreferenceQuestions:
    """Tests for question generation."""

    def test_all_unknown(self):
        """Generates all questions when nothing is known."""
        profile = {"travel_style": "", "budget_level": "", "travel_companion": "", "interests": []}
        questions = build_preference_questions(profile, "Thailand", 14)
        assert len(questions) >= 3
        assert len(questions) <= 4

    def test_companion_known(self):
        """Skips companion question when already known."""
        profile = {"travel_style": "", "budget_level": "", "travel_companion": "couple", "interests": []}
        questions = build_preference_questions(profile, "Japan", 10)
        # Should NOT ask about companion
        assert not any("solo" in q.lower() and "couple" in q.lower() for q in questions)

    def test_style_known(self):
        """Skips style question when interests are known."""
        profile = {"travel_style": "adventurous", "budget_level": "", "travel_companion": "", "interests": ["hiking"]}
        questions = build_preference_questions(profile, "Peru", 7)
        # Should NOT ask about style since interests exist
        assert not any("relaxed" in q.lower() and "adventurous" in q.lower() for q in questions)

    def test_short_trip_no_city_question(self):
        """Short trips (<7 days) don't get the cities question."""
        profile = {"travel_style": "", "budget_level": "", "travel_companion": "", "interests": []}
        questions = build_preference_questions(profile, "Lisbon", 4)
        assert not any("cities" in q.lower() or "regions" in q.lower() for q in questions)


class TestBuildResearchQuery:
    """Tests for Perplexity research query building."""

    def test_basic_query(self):
        query = _build_research_query("Thailand", 14, {}, {})
        assert "Thailand" in query
        assert "14-day" in query
        assert "attractions" in query

    def test_query_with_preferences(self):
        prefs = {"style": "adventurous", "companion": "couple", "budget": "luxury"}
        query = _build_research_query("Japan", 10, prefs, {})
        assert "adventurous" in query
        assert "couple" in query
        assert "luxury" in query

    def test_query_with_specific_cities(self):
        prefs = {"cities": "Chiang Mai, Bangkok, Phuket"}
        query = _build_research_query("Thailand", 21, prefs, {})
        assert "Chiang Mai" in query


class TestBuildItinerary:
    """Tests for full itinerary building."""

    @pytest.mark.asyncio
    async def test_itinerary_no_services(self):
        """Itinerary still generates with fallback when no services."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()

        def fake_svc(name):
            return mock_db if name == "database" else None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            result = await build_itinerary(
                user_id="user-123",
                destination="Thailand",
                start_date="Mar 15",
                end_date="Apr 15",
                duration_days=30,
                user_name="Marcos",
            )

        assert result is not None
        assert "Thailand" in result["title"]
        assert result["duration_days"] == 30

    @pytest.mark.asyncio
    async def test_itinerary_with_preferences(self):
        """Itinerary uses preferences in query."""
        def fake_svc(name):
            return None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            result = await build_itinerary(
                user_id="user-123",
                destination="Japan",
                start_date="May 1",
                end_date="May 10",
                duration_days=10,
                user_name="Ana",
                preferences={"style": "cultural", "companion": "solo"},
            )

        assert result is not None
        assert "Japan" in result["itinerary"]

    @pytest.mark.asyncio
    async def test_save_prefs_no_db(self):
        from services.business.travel_planner_service import _save_travel_preferences
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            await _save_travel_preferences("u1", {"companion": "solo"}, {})

    @pytest.mark.asyncio
    async def test_store_itinerary_no_db(self):
        from services.business.travel_planner_service import _store_itinerary
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            await _store_itinerary("u1", "Trip", "itinerary text", "Tokyo")


# ===========================================================================
# Phase 3 — Presentation + Approval + Final Document
# ===========================================================================

class TestGenerateTripSummary:
    """Tests for trip summary/teaser generation."""

    @pytest.mark.asyncio
    async def test_summary_no_gpt(self):
        """Fallback summary is still warm and useful."""
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            result = await generate_trip_summary(
                itinerary="Day 1: Bangkok...\nDay 2: Temples...",
                destination="Thailand",
                duration_days=14,
                user_name="Marcos",
            )
        assert "Marcos" in result
        assert "Thailand" in result
        assert "14" in result

    @pytest.mark.asyncio
    async def test_summary_contains_cta(self):
        """Summary asks user to approve or adjust."""
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            result = await generate_trip_summary(
                itinerary="Week 1: Tokyo...",
                destination="Japan",
                duration_days=10,
                user_name="Ana",
            )
        assert "adjust" in result.lower() or "plan" in result.lower()


class TestAdjustItinerary:
    """Tests for itinerary adjustment based on user feedback."""

    @pytest.mark.asyncio
    async def test_adjust_no_gpt(self):
        """Fallback acknowledges feedback when GPT unavailable."""
        def fake_svc(name):
            return None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            result = await adjust_itinerary(
                user_id="user-123",
                current_itinerary="Day 1: Chiang Mai temples...",
                user_feedback="Swap Chiang Mai for Pai",
                destination="Thailand",
                duration_days=14,
                user_name="Marcos",
            )
        assert "Swap Chiang Mai for Pai" in result["itinerary"]
        assert result["adjusted"] is False

    @pytest.mark.asyncio
    async def test_adjust_with_gpt(self):
        """GPT adjustment returns modified itinerary."""
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = "Great call swapping Chiang Mai for Pai! Here's the updated plan..."

        def fake_svc(name):
            return mock_openai if name == "openai" else None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            result = await adjust_itinerary(
                user_id="user-123",
                current_itinerary="Day 1: Chiang Mai...",
                user_feedback="Swap Chiang Mai for Pai",
                destination="Thailand",
                duration_days=14,
                user_name="Marcos",
            )
        assert result["adjusted"] is True
        assert "Pai" in result["itinerary"]


class TestFinalizeItinerary:
    """Tests for final document generation."""

    @pytest.mark.asyncio
    async def test_finalize_no_services(self):
        """Finalize works even without GPT/notes (uses current itinerary)."""
        def fake_svc(name):
            return None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            result = await finalize_itinerary(
                user_id="user-123",
                itinerary="Day 1: Bangkok temples\nDay 2: Street food tour",
                destination="Thailand",
                duration_days=14,
                user_name="Marcos",
            )
        assert result is not None
        assert "Thailand" in result["destination"]
        assert "Thailand" in result["confirmation"]
        assert "Marcos" in result["confirmation"]

    @pytest.mark.asyncio
    async def test_finalize_saves_to_notes(self):
        """Finalize attempts to save to notes service."""
        mock_notes = MagicMock()
        mock_notes.is_initialized.return_value = True
        mock_notes.create_note = AsyncMock(return_value=True)

        def fake_svc(name):
            return mock_notes if name == "notes" else None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            result = await finalize_itinerary(
                user_id="user-123",
                itinerary="Full itinerary content here...",
                destination="Japan",
                duration_days=10,
                user_name="Ana",
            )
        assert result is not None
        # Notes service was called
        mock_notes.create_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_humanize_confirmation_no_gpt(self):
        from services.business.travel_planner_service import _humanize_confirmation
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            msg = await _humanize_confirmation("Marcos", "Thailand", 14)
        assert "Marcos" in msg
        assert "Thailand" in msg
        assert "notes" in msg.lower()

    @pytest.mark.asyncio
    async def test_save_to_notes_no_service(self):
        from services.business.travel_planner_service import _save_to_notes
        with patch("services.business.travel_planner_service.get_service", return_value=None):
            await _save_to_notes("u1", "Paris", 5, "content")  # Should not crash

    @pytest.mark.asyncio
    async def test_save_to_notes_with_db(self):
        """Saves itinerary to user_context even without notes service."""
        from services.business.travel_planner_service import _save_to_notes
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        def fake_svc(name):
            return mock_db if name == "database" else None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            await _save_to_notes("u1", "Tokyo", 7, "My itinerary content")

        mock_db.get_client.return_value.table.assert_called_with("user_context")

    @pytest.mark.asyncio
    async def test_finalize_with_gpt(self):
        """Finalize uses GPT for polished document."""
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = "🗺️ Ana's Japan Adventure — 10 Days\n\nDay 1: Tokyo..."

        def fake_svc(name):
            return mock_openai if name == "openai" else None

        with patch("services.business.travel_planner_service.get_service", fake_svc):
            result = await finalize_itinerary(
                user_id="user-456",
                itinerary="Day 1: Tokyo\nDay 2: Kyoto",
                destination="Japan",
                duration_days=10,
                user_name="Ana Costa",
            )
        assert result is not None
        assert "Japan" in result["document"] or "Ana" in result["document"]

    @pytest.mark.asyncio
    async def test_summary_with_gpt(self):
        """Summary uses GPT when available."""
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = "Hey Marcos! I planned 4 weeks across Thailand — Bangkok, Chiang Mai, islands, and more!"

        with patch("services.business.travel_planner_service.get_service", return_value=mock_openai):
            result = await generate_trip_summary(
                itinerary="Week 1: Bangkok\nWeek 2: Chiang Mai",
                destination="Thailand",
                duration_days=28,
                user_name="Marcos",
            )
        assert "Thailand" in result or "Bangkok" in result
