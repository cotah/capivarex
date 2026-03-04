# -*- coding: utf-8 -*-
"""Tests for OCR validation logic."""

import logging

from services.business.mercado_service import MercadoService


class TestValidarOCR:
    """Tests for _validar_ocr method."""

    def setup_method(self):
        """Create service instance for testing."""
        self.svc = MercadoService.__new__(MercadoService)
        self.svc.logger = logging.getLogger("test")

    def test_high_confidence_when_perfect(self):
        """High confidence when sum matches total exactly."""
        data = {
            "total": 10.00,
            "itens": [
                {
                    "produto": "Leite",
                    "preco_total": 4.00,
                    "preco_unitario": 4.00,
                    "quantidade": 1,
                },
                {
                    "produto": "Pão",
                    "preco_total": 6.00,
                    "preco_unitario": 6.00,
                    "quantidade": 1,
                },
            ],
        }
        result = self.svc._validar_ocr(data)
        assert result["ocr_confidence"] == "high"
        assert result["ocr_warnings"] == []

    def test_medium_confidence_small_mismatch(self):
        """Medium confidence when sum slightly off from total."""
        data = {
            "total": 10.00,
            "itens": [
                {
                    "produto": "Leite",
                    "preco_total": 4.00,
                    "preco_unitario": 4.00,
                    "quantidade": 1,
                },
                {
                    "produto": "Pão",
                    "preco_total": 5.50,
                    "preco_unitario": 5.50,
                    "quantidade": 1,
                },
            ],
        }
        result = self.svc._validar_ocr(data)
        assert result["ocr_confidence"] == "medium"
        assert any("mismatch" in w.lower() for w in result["ocr_warnings"])

    def test_low_confidence_big_mismatch(self):
        """Low confidence when sum way off from total (>15%)."""
        data = {
            "total": 50.00,
            "itens": [
                {
                    "produto": "Leite",
                    "preco_total": 4.00,
                    "preco_unitario": 4.00,
                    "quantidade": 1,
                },
                {
                    "produto": "Pão",
                    "preco_total": 6.00,
                    "preco_unitario": 6.00,
                    "quantidade": 1,
                },
            ],
        }
        result = self.svc._validar_ocr(data)
        assert result["ocr_confidence"] == "low"

    def test_infer_single_missing_price(self):
        """Infers price for single item with null price."""
        data = {
            "total": 10.00,
            "itens": [
                {
                    "produto": "Leite",
                    "preco_total": 4.00,
                    "preco_unitario": 4.00,
                    "quantidade": 1,
                },
                {
                    "produto": "Pão",
                    "preco_total": 0,
                    "preco_unitario": 0,
                    "quantidade": 1,
                },
            ],
        }
        result = self.svc._validar_ocr(data)
        assert result["itens"][1]["preco_total"] == 6.00

    def test_duplicate_adjacent_prices_flagged(self):
        """Flags duplicate prices in adjacent items."""
        data = {
            "total": 7.00,
            "itens": [
                {
                    "produto": "Leite",
                    "preco_total": 3.50,
                    "preco_unitario": 3.50,
                    "quantidade": 1,
                },
                {
                    "produto": "Queijo",
                    "preco_total": 3.50,
                    "preco_unitario": 3.50,
                    "quantidade": 1,
                },
            ],
        }
        result = self.svc._validar_ocr(data)
        assert any("duplicate" in w.lower() for w in result["ocr_warnings"])

    def test_price_exceeds_total_nulled(self):
        """Item with price > total gets zeroed out."""
        data = {
            "total": 10.00,
            "itens": [
                {
                    "produto": "Leite",
                    "preco_total": 25.00,
                    "preco_unitario": 25.00,
                    "quantidade": 1,
                },
                {
                    "produto": "Pão",
                    "preco_total": 3.00,
                    "preco_unitario": 3.00,
                    "quantidade": 1,
                },
            ],
        }
        result = self.svc._validar_ocr(data)
        assert result["itens"][0]["preco_total"] == 0

    def test_negative_prices_removed(self):
        """Negative price items (discounts) are removed."""
        data = {
            "total": 7.00,
            "itens": [
                {
                    "produto": "Leite",
                    "preco_total": 4.00,
                    "preco_unitario": 4.00,
                    "quantidade": 1,
                },
                {
                    "produto": "Desconto",
                    "preco_total": -1.00,
                    "preco_unitario": -1.00,
                    "quantidade": 1,
                },
                {
                    "produto": "Pão",
                    "preco_total": 4.00,
                    "preco_unitario": 4.00,
                    "quantidade": 1,
                },
            ],
        }
        result = self.svc._validar_ocr(data)
        assert len(result["itens"]) == 2
        assert all(i["produto"] != "Desconto" for i in result["itens"])

    def test_no_total_no_mismatch_warning(self):
        """No mismatch warning when total is 0 (not on receipt)."""
        data = {
            "total": 0,
            "itens": [
                {
                    "produto": "Leite",
                    "preco_total": 4.00,
                    "preco_unitario": 4.00,
                    "quantidade": 1,
                },
            ],
        }
        result = self.svc._validar_ocr(data)
        assert not any("mismatch" in w.lower() for w in result["ocr_warnings"])
