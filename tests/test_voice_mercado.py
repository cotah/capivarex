"""Tests for voice shopping list parsing."""

from agents.specialized.mercado_agent import MercadoAgent


class TestParseVoiceItems:
    """Tests for _parse_voice_items method."""

    def test_simple_comma_list(self):
        """Parses comma-separated items."""
        items = MercadoAgent._parse_voice_items("leite, pão, ovos")
        assert items == ["leite", "pão", "ovos"]

    def test_conjunction_and(self):
        """Parses items joined by 'e'."""
        items = MercadoAgent._parse_voice_items("leite e pão e ovos")
        assert items == ["leite", "pão", "ovos"]

    def test_mixed_comma_and_conjunction(self):
        """Parses mixed comma and conjunction."""
        items = MercadoAgent._parse_voice_items("leite, pão e ovos")
        assert items == ["leite", "pão", "ovos"]

    def test_english_conjunction(self):
        """Parses English conjunctions."""
        items = MercadoAgent._parse_voice_items("milk and bread and eggs")
        assert items == ["milk", "bread", "eggs"]

    def test_removes_fillers(self):
        """Removes filler words like 'também', 'uns'."""
        items = MercadoAgent._parse_voice_items(
            "preciso de leite, também pão e uns ovos"
        )
        assert "leite" in items
        assert "pão" in items
        assert "ovos" in items
        assert "também" not in " ".join(items)

    def test_removes_articles(self):
        """Removes leading articles."""
        items = MercadoAgent._parse_voice_items("o leite, a manteiga, os ovos")
        assert items == ["leite", "manteiga", "ovos"]

    def test_preserves_quantities(self):
        """Preserves quantities like '2 leites'."""
        items = MercadoAgent._parse_voice_items("2 leites, 3 pães")
        assert "2 leites" in items
        assert "3 pães" in items

    def test_single_item(self):
        """Handles single item."""
        items = MercadoAgent._parse_voice_items("leite")
        assert items == ["leite"]

    def test_empty_string(self):
        """Handles empty string."""
        items = MercadoAgent._parse_voice_items("")
        assert items == []

    def test_spanish(self):
        """Parses Spanish items."""
        items = MercadoAgent._parse_voice_items("leche y pan y huevos")
        assert items == ["leche", "pan", "huevos"]

    def test_strips_trailing_punctuation(self):
        """Strips trailing punctuation."""
        items = MercadoAgent._parse_voice_items("leite, pão, ovos.")
        assert "ovos" in items

    def test_skips_single_char(self):
        """Skips single character items (noise)."""
        items = MercadoAgent._parse_voice_items("leite, a, pão")
        assert "leite" in items
        assert "pão" in items
        assert "a" not in items


class TestVoiceListRegex:
    """Tests for _RE_VOICE_LIST regex."""

    def test_preciso_de(self):
        from agents.specialized.mercado_agent import _RE_VOICE_LIST

        m = _RE_VOICE_LIST.match("preciso de leite e pão")
        assert m and m.group(1) == "leite e pão"

    def test_comprar(self):
        from agents.specialized.mercado_agent import _RE_VOICE_LIST

        m = _RE_VOICE_LIST.match("comprar leite pão ovos")
        assert m and m.group(1) == "leite pão ovos"

    def test_need(self):
        from agents.specialized.mercado_agent import _RE_VOICE_LIST

        m = _RE_VOICE_LIST.match("I need milk bread and eggs")
        assert m

    def test_quero(self):
        from agents.specialized.mercado_agent import _RE_VOICE_LIST

        m = _RE_VOICE_LIST.match("quero leite e pão")
        assert m and m.group(1) == "leite e pão"

    def test_faltam(self):
        from agents.specialized.mercado_agent import _RE_VOICE_LIST

        m = _RE_VOICE_LIST.match("faltam ovos e manteiga")
        assert m

    def test_necesito(self):
        from agents.specialized.mercado_agent import _RE_VOICE_LIST

        m = _RE_VOICE_LIST.match("necesito leche y pan")
        assert m
