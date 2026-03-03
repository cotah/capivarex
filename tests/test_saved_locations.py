# -*- coding: utf-8 -*-
"""
tests/test_saved_locations.py
=============================
Tests for SavedLocationsService and alias resolution.
"""

import pytest
from unittest.mock import AsyncMock, patch

from services.business.saved_locations_service import (
    SavedLocationsService,
    resolve_alias,
    get_label,
    get_saved_locations_service,
)


# -- Alias resolution --


class TestAliasResolution:
    def test_resolve_home_pt(self):
        assert resolve_alias("casa") == "home"
        assert resolve_alias("minha casa") == "home"

    def test_resolve_home_en(self):
        assert resolve_alias("home") == "home"

    def test_resolve_home_es(self):
        assert resolve_alias("mi casa") == "home"
        assert resolve_alias("hogar") == "home"

    def test_resolve_work_pt(self):
        assert resolve_alias("trabalho") == "work"
        assert resolve_alias("escritorio") == "work"

    def test_resolve_work_en(self):
        assert resolve_alias("work") == "work"
        assert resolve_alias("office") == "work"
        assert resolve_alias("the office") == "work"

    def test_resolve_gym(self):
        assert resolve_alias("academia") == "gym"
        assert resolve_alias("gym") == "gym"
        assert resolve_alias("the gym") == "gym"

    def test_resolve_school(self):
        assert resolve_alias("faculdade") == "school"
        assert resolve_alias("uni") == "school"
        assert resolve_alias("school") == "school"

    def test_resolve_parents(self):
        assert resolve_alias("casa dos meus pais") == "parents"
        assert resolve_alias("my parents") == "parents"

    def test_resolve_unknown(self):
        assert resolve_alias("supermercado") is None
        assert resolve_alias("Dublin Airport") is None
        assert resolve_alias("") is None

    def test_resolve_case_insensitive(self):
        assert resolve_alias("Casa") == "home"
        assert resolve_alias("TRABALHO") == "work"
        assert resolve_alias("  gym  ") == "gym"


class TestGetLabel:
    def test_label_pt(self):
        assert get_label("home", "pt") == "Casa"
        assert get_label("work", "pt") == "Trabalho"

    def test_label_en(self):
        assert get_label("home", "en") == "Home"
        assert get_label("work", "en") == "Work"

    def test_label_es(self):
        assert get_label("home", "es") == "Casa"
        assert get_label("work", "es") == "Trabajo"

    def test_label_unknown_key(self):
        assert get_label("unknown_place", "pt") == "Unknown_Place"


# -- SavedLocationsService --


class TestSavedLocationsService:
    @pytest.fixture
    def svc(self):
        return SavedLocationsService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.is_initialized.return_value = True
        db.get_user_context = AsyncMock(return_value=None)
        db.save_user_context = AsyncMock(return_value=True)
        return db

    @pytest.mark.asyncio
    async def test_get_all_locations_empty(self, svc, mock_db):
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.get_all_locations("user-123")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_all_locations_with_data(self, svc, mock_db):
        mock_db.get_user_context = AsyncMock(
            return_value={
                "home": {
                    "address": "Swords, Dublin",
                    "latitude": 53.45,
                    "longitude": -6.22,
                },
                "work": {"address": "City Centre, Dublin"},
            }
        )
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.get_all_locations("user-123")
        assert "home" in result
        assert result["home"]["address"] == "Swords, Dublin"
        assert "work" in result

    @pytest.mark.asyncio
    async def test_get_location_exists(self, svc, mock_db):
        mock_db.get_user_context = AsyncMock(
            return_value={
                "home": {"address": "Swords, Dublin"},
            }
        )
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.get_location("user-123", "home")
        assert result is not None
        assert result["address"] == "Swords, Dublin"

    @pytest.mark.asyncio
    async def test_get_location_not_exists(self, svc, mock_db):
        mock_db.get_user_context = AsyncMock(
            return_value={"home": {"address": "X"}}
        )
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.get_location("user-123", "work")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_location_with_geocode(self, svc, mock_db):
        mock_maps = AsyncMock()
        mock_maps.is_initialized.return_value = True
        mock_maps.geocode = AsyncMock(
            return_value={"latitude": 53.45, "longitude": -6.22}
        )

        mock_db.get_user_context = AsyncMock(return_value={})

        def fake_get_service(name):
            if name == "database":
                return mock_db
            if name == "maps":
                return mock_maps
            return None

        with patch(
            "services.business.saved_locations_service.get_service",
            side_effect=fake_get_service,
        ):
            result = await svc.save_location(
                "user-123", "home", "Swords, Dublin"
            )

        assert result["address"] == "Swords, Dublin"
        assert result["latitude"] == 53.45
        mock_db.save_user_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_location_without_geocode(self, svc, mock_db):
        mock_db.get_user_context = AsyncMock(return_value={})

        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.save_location(
                "user-123", "work", "City Centre", geocode=False
            )

        assert result["address"] == "City Centre"
        assert "latitude" not in result

    @pytest.mark.asyncio
    async def test_save_merges_with_existing(self, svc, mock_db):
        mock_db.get_user_context = AsyncMock(
            return_value={
                "home": {"address": "Old Address"},
            }
        )

        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            await svc.save_location(
                "user-123", "work", "New Work", geocode=False
            )

        # Check that save was called with both home and work
        call_args = mock_db.save_user_context.call_args
        saved_data = call_args[0][2]  # third positional arg
        assert "home" in saved_data
        assert "work" in saved_data
        assert saved_data["home"]["address"] == "Old Address"
        assert saved_data["work"]["address"] == "New Work"

    @pytest.mark.asyncio
    async def test_delete_location(self, svc, mock_db):
        mock_db.get_user_context = AsyncMock(
            return_value={
                "home": {"address": "Swords"},
                "work": {"address": "Dublin"},
            }
        )

        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.delete_location("user-123", "home")

        assert result is True
        call_args = mock_db.save_user_context.call_args
        saved_data = call_args[0][2]
        assert "home" not in saved_data
        assert "work" in saved_data

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, svc, mock_db):
        mock_db.get_user_context = AsyncMock(
            return_value={"home": {"address": "X"}}
        )

        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.delete_location("user-123", "work")

        assert result is False

    @pytest.mark.asyncio
    async def test_resolve_address_found(self, svc, mock_db):
        mock_db.get_user_context = AsyncMock(
            return_value={
                "home": {"address": "Swords, Dublin"},
            }
        )

        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.resolve_address("user-123", "casa")

        assert result == "Swords, Dublin"

    @pytest.mark.asyncio
    async def test_resolve_address_not_alias(self, svc, mock_db):
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.resolve_address(
                "user-123", "Dublin Airport"
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_address_alias_but_not_saved(
        self, svc, mock_db
    ):
        mock_db.get_user_context = AsyncMock(return_value={})

        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.resolve_address("user-123", "trabalho")

        assert result is None

    @pytest.mark.asyncio
    async def test_db_unavailable(self, svc):
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=None,
        ):
            result = await svc.get_all_locations("user-123")
        assert result == {}

    @pytest.mark.asyncio
    async def test_save_location_db_unavailable(self, svc):
        """save_location without DB returns location_data without persisting."""
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=None,
        ):
            result = await svc.save_location(
                "user-123", "home", "Swords", geocode=False
            )
        assert result["address"] == "Swords"

    @pytest.mark.asyncio
    async def test_delete_location_db_unavailable(self, svc):
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=None,
        ):
            result = await svc.delete_location("user-123", "home")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_all_locations_exception(self, svc, mock_db):
        mock_db.get_user_context = AsyncMock(
            side_effect=Exception("DB error")
        )
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.get_all_locations("user-123")
        assert result == {}

    @pytest.mark.asyncio
    async def test_save_location_exception(self, svc, mock_db):
        mock_db.get_user_context = AsyncMock(
            side_effect=Exception("DB error")
        )
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.save_location(
                "user-123", "home", "Swords", geocode=False
            )
        assert result["address"] == "Swords"

    @pytest.mark.asyncio
    async def test_delete_location_save_exception(self, svc, mock_db):
        """Exception in save_user_context during delete."""
        mock_db.get_user_context = AsyncMock(
            return_value={"home": {"address": "X"}}
        )
        mock_db.save_user_context = AsyncMock(
            side_effect=Exception("DB write error")
        )
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.delete_location("user-123", "home")
        assert result is False

    @pytest.mark.asyncio
    async def test_geocode_failure_still_saves(self, svc, mock_db):
        """Geocode failure should not prevent saving."""
        mock_maps = AsyncMock()
        mock_maps.is_initialized.return_value = True
        mock_maps.geocode = AsyncMock(
            side_effect=Exception("Geocode failed")
        )
        mock_db.get_user_context = AsyncMock(return_value={})

        def fake_get_service(name):
            if name == "database":
                return mock_db
            if name == "maps":
                return mock_maps
            return None

        with patch(
            "services.business.saved_locations_service.get_service",
            side_effect=fake_get_service,
        ):
            result = await svc.save_location(
                "user-123", "home", "Swords, Dublin"
            )
        assert result["address"] == "Swords, Dublin"
        assert "latitude" not in result
        mock_db.save_user_context.assert_called_once()


class TestSingleton:
    def test_get_saved_locations_service_returns_instance(self):
        import services.business.saved_locations_service as mod

        mod._instance = None
        svc1 = get_saved_locations_service()
        svc2 = get_saved_locations_service()
        assert svc1 is svc2
        assert isinstance(svc1, SavedLocationsService)
        # Reset for other tests
        mod._instance = None


class TestResolveAddressException:
    @pytest.fixture
    def svc(self):
        return SavedLocationsService()

    @pytest.mark.asyncio
    async def test_resolve_address_db_exception(self, svc):
        """resolve_address returns None when DB raises."""
        mock_db = AsyncMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_context = AsyncMock(
            side_effect=Exception("DB error")
        )
        with patch(
            "services.business.saved_locations_service.get_service",
            return_value=mock_db,
        ):
            result = await svc.resolve_address("user-123", "casa")
        assert result is None
