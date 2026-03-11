"""Tests for 'check list' routing bug fix.

Bug: 'check list' was being added as a product instead of showing the list.
Fix: Extended _RE_VER regex + guard clause on fallback for non-product words.
"""

from agents.specialized.mercado_agent import (
    _RE_VER,
    _NON_PRODUCT_WORDS,
)


class TestReVerExtended:
    """Tests that _RE_VER matches 'check list' variants."""

    def test_check_list(self):
        assert _RE_VER.search("check list") is not None

    def test_check_my_list(self):
        assert _RE_VER.search("check my list") is not None

    def test_checklist(self):
        assert _RE_VER.search("checklist") is not None

    def test_show_my_list(self):
        assert _RE_VER.search("show my list") is not None

    def test_whats_on_my_list(self):
        assert _RE_VER.search("what's on my list") is not None

    def test_whats_on_my_list_curly_quote(self):
        assert _RE_VER.search("what\u2019s on my list") is not None

    def test_see_my_list(self):
        assert _RE_VER.search("see my list") is not None

    def test_my_shopping_list(self):
        assert _RE_VER.search("my shopping list") is not None

    def test_ver_lista_still_works(self):
        """Original patterns still work."""
        assert _RE_VER.search("ver lista") is not None

    def test_minha_lista_still_works(self):
        assert _RE_VER.search("minha lista") is not None

    def test_generic_text_no_match(self):
        """Generic text should NOT match _RE_VER."""
        assert _RE_VER.search("buy milk") is None
        assert _RE_VER.search("leite e pão") is None


class TestNonProductWordsGuard:
    """Tests that command-like words are not added as products."""

    def test_check_list_is_non_product(self):
        """'check list' words are all in _NON_PRODUCT_WORDS."""
        words = set("check list".lower().split())
        assert words.issubset(_NON_PRODUCT_WORDS)

    def test_show_list_is_non_product(self):
        words = set("show list".lower().split())
        assert words.issubset(_NON_PRODUCT_WORDS)

    def test_view_list_is_non_product(self):
        words = set("view list".lower().split())
        assert words.issubset(_NON_PRODUCT_WORDS)

    def test_ver_lista_is_non_product(self):
        words = set("ver lista".lower().split())
        assert words.issubset(_NON_PRODUCT_WORDS)

    def test_minha_lista_is_non_product(self):
        words = set("minha lista".lower().split())
        assert words.issubset(_NON_PRODUCT_WORDS)

    def test_real_product_not_blocked(self):
        """Real products should NOT be subsets of _NON_PRODUCT_WORDS."""
        words = set("leite".lower().split())
        assert not words.issubset(_NON_PRODUCT_WORDS)

    def test_mixed_product_not_blocked(self):
        """'check leite' should NOT be fully in _NON_PRODUCT_WORDS."""
        words = set("check leite".lower().split())
        assert not words.issubset(_NON_PRODUCT_WORDS)

    def test_help_is_non_product(self):
        words = set("help".lower().split())
        assert words.issubset(_NON_PRODUCT_WORDS)

    def test_cancel_is_non_product(self):
        words = set("cancel".lower().split())
        assert words.issubset(_NON_PRODUCT_WORDS)
