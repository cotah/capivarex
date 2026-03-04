# -*- coding: utf-8 -*-
"""Tests for mercado export command."""

import os
import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.specialized.mercado_agent import MercadoAgent


class TestParseMonth:
    """Tests for _parse_month helper."""

    def test_numeric_month(self):
        assert MercadoAgent._parse_month("3") == 3
        assert MercadoAgent._parse_month("12") == 12

    def test_english_month(self):
        assert MercadoAgent._parse_month("march") == 3
        assert MercadoAgent._parse_month("December") == 12

    def test_portuguese_month(self):
        assert MercadoAgent._parse_month("março") == 3
        assert MercadoAgent._parse_month("fevereiro") == 2

    def test_spanish_month(self):
        assert MercadoAgent._parse_month("febrero") == 2
        assert MercadoAgent._parse_month("diciembre") == 12

    def test_invalid_returns_none(self):
        assert MercadoAgent._parse_month("xyz") is None
        assert MercadoAgent._parse_month("13") is None
        assert MercadoAgent._parse_month("0") is None

    def test_partial_match(self):
        assert MercadoAgent._parse_month("março 2025") == 3


class TestExportRegex:
    """Tests for _RE_EXPORT regex pattern."""

    def test_export_simple(self):
        from agents.specialized.mercado_agent import _RE_EXPORT

        assert _RE_EXPORT.match("exportar")
        assert _RE_EXPORT.match("export")
        assert _RE_EXPORT.match("excel")

    def test_export_with_month(self):
        from agents.specialized.mercado_agent import _RE_EXPORT

        m = _RE_EXPORT.match("exportar março")
        assert m and m.group(1) == "março"

    def test_export_english(self):
        from agents.specialized.mercado_agent import _RE_EXPORT

        m = _RE_EXPORT.match("export march")
        assert m and m.group(1) == "march"

    def test_download_report(self):
        from agents.specialized.mercado_agent import _RE_EXPORT

        assert _RE_EXPORT.match("download report")
        assert _RE_EXPORT.match("baixar relatório")


class TestDocumentResponseSender:
    """Tests for document type in response_sender."""

    @pytest.mark.asyncio
    async def test_sends_document_type(self):
        """response_sender sends reply_document for type=document."""
        from telegram_bot.utils.response_sender import send_agent_response
        from agents.core import AgentResponse, AgentStatus

        # Create a temp file
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        tmp.write(b"PK fake xlsx")
        tmp.close()

        try:
            result = AgentResponse(
                status=AgentStatus.SUCCESS,
                response="test caption",
                data={"document_path": tmp.name},
                metadata={
                    "type": "document",
                    "file_path": tmp.name,
                    "filename": "test.xlsx",
                },
            )

            mock_update = MagicMock()
            mock_update.message.reply_document = AsyncMock()
            mock_update.message.reply_text = AsyncMock()

            await send_agent_response(mock_update, result)

            mock_update.message.reply_document.assert_called_once()
            call_kwargs = mock_update.message.reply_document.call_args
            assert call_kwargs[1]["filename"] == "test.xlsx"
        finally:
            os.unlink(tmp.name)
