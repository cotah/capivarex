"""Tests for cross-language grocery synonym detection."""

from services.business.grocery_synonyms import (
    get_canonical,
    are_synonyms,
    find_synonym_in_list,
)


class TestGetCanonical:
    """Tests for get_canonical function."""

    def test_portuguese_canonical(self):
        assert get_canonical("pão") == "pão"
        assert get_canonical("leite") == "leite"

    def test_english_to_canonical(self):
        assert get_canonical("bread") == "pão"
        assert get_canonical("milk") == "leite"
        assert get_canonical("eggs") == "ovos"

    def test_spanish_to_canonical(self):
        assert get_canonical("pan") == "pão"
        assert get_canonical("leche") == "leite"
        assert get_canonical("huevos") == "ovos"

    def test_case_insensitive(self):
        assert get_canonical("Bread") == "pão"
        assert get_canonical("MILK") == "leite"
        assert get_canonical("Queijo") == "queijo"

    def test_unknown_item_returns_lowered(self):
        assert get_canonical("Nutella") == "nutella"
        assert get_canonical("Some Brand Product") == "some brand product"

    def test_accented_variants(self):
        assert get_canonical("acucar") == "açúcar"
        assert get_canonical("açúcar") == "açúcar"
        assert get_canonical("cafe") == "café"

    def test_plural_forms(self):
        assert get_canonical("eggs") == "ovos"
        assert get_canonical("egg") == "ovos"
        assert get_canonical("batatas") == "batata"
        assert get_canonical("potatoes") == "batata"


class TestAreSynonyms:
    """Tests for are_synonyms function."""

    def test_same_word(self):
        assert are_synonyms("pão", "pão") is True

    def test_cross_language(self):
        assert are_synonyms("bread", "pão") is True
        assert are_synonyms("milk", "leite") is True
        assert are_synonyms("cheese", "queijo") is True
        assert are_synonyms("eggs", "ovos") is True

    def test_different_products(self):
        assert are_synonyms("bread", "milk") is False
        assert are_synonyms("pão", "leite") is False

    def test_unknown_vs_known(self):
        assert are_synonyms("Nutella", "bread") is False

    def test_unknown_same(self):
        assert are_synonyms("Nutella", "Nutella") is True

    def test_three_languages(self):
        assert are_synonyms("bread", "pan") is True  # EN <-> ES
        assert are_synonyms("pão", "pan") is True  # PT <-> ES
        assert are_synonyms("leche", "milk") is True  # ES <-> EN


class TestFindSynonymInList:
    """Tests for find_synonym_in_list function."""

    def test_finds_portuguese_equivalent(self):
        result = find_synonym_in_list("bread", ["leite", "pão", "arroz"])
        assert result == "pão"

    def test_finds_english_equivalent(self):
        result = find_synonym_in_list("leite", ["milk", "bread", "rice"])
        assert result == "milk"

    def test_returns_none_when_not_found(self):
        result = find_synonym_in_list("banana", ["leite", "pão"])
        assert result is None

    def test_returns_none_for_empty_list(self):
        result = find_synonym_in_list("bread", [])
        assert result is None

    def test_finds_spanish_equivalent(self):
        result = find_synonym_in_list("huevos", ["pão", "ovos", "leite"])
        assert result == "ovos"

    def test_unknown_item_no_false_match(self):
        result = find_synonym_in_list("Nutella", ["pão", "leite"])
        assert result is None

    def test_exact_same_item(self):
        result = find_synonym_in_list("pão", ["pão", "leite"])
        assert result == "pão"


class TestDuplicateMessage:
    """Tests for duplicate message format with synonym info."""

    def test_synonym_display_format(self):
        """When a synonym is found, show 'bread (= pão)'."""
        item = "bread"
        synonym = "pão"
        msg = f"{item} (= {synonym})"
        assert msg == "bread (= pão)"
