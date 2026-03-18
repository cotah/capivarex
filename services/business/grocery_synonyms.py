"""
Cross-language synonym map for common grocery items.

Each tuple is a group of synonyms (PT, EN, ES).
The FIRST item in each group is the canonical form used for matching.
"""

from typing import Dict, List, Optional, Tuple

# Each group: (canonical_pt, *variants_all_languages)
# Canonical is the first entry — used as the "key" for dedup
_SYNONYM_GROUPS: Tuple[Tuple[str, ...], ...] = (
    # Bread
    ("pão", "pao", "bread", "pan", "pães", "paes", "breads", "panes"),
    # Milk
    ("leite", "milk", "leche", "milch"),
    # Eggs
    ("ovos", "ovo", "eggs", "egg", "huevos", "huevo"),
    # Cheese
    ("queijo", "cheese", "queso", "fromage"),
    # Butter
    ("manteiga", "butter", "mantequilla", "margarina", "margarine"),
    # Chicken
    ("frango", "chicken", "pollo", "galinha"),
    # Meat / Beef
    ("carne", "meat", "beef", "carne de vaca", "carne de res"),
    # Pork
    ("porco", "pork", "cerdo"),
    # Fish
    ("peixe", "fish", "pescado", "pescao"),
    # Rice
    ("arroz", "rice"),
    # Pasta
    ("massa", "pasta", "macarrão", "macarrao", "noodles", "fideos"),
    # Potatoes
    ("batata", "batatas", "potato", "potatoes", "patata", "patatas", "papa", "papas"),
    # Tomato
    ("tomate", "tomates", "tomato", "tomatoes"),
    # Onion
    ("cebola", "cebolas", "onion", "onions", "cebolla", "cebollas"),
    # Garlic
    ("alho", "garlic", "ajo"),
    # Lettuce
    ("alface", "lettuce", "lechuga"),
    # Carrot
    ("cenoura", "cenouras", "carrot", "carrots", "zanahoria", "zanahorias"),
    # Apple
    ("maçã", "maca", "maçãs", "apple", "apples", "manzana", "manzanas"),
    # Banana
    ("banana", "bananas", "plátano", "platano"),
    # Orange
    ("laranja", "laranjas", "orange", "oranges", "naranja", "naranjas"),
    # Sugar
    ("açúcar", "acucar", "sugar", "azúcar", "azucar"),
    # Salt
    ("sal", "salt"),
    # Oil
    ("óleo", "oleo", "azeite", "oil", "olive oil", "aceite"),
    # Coffee
    ("café", "cafe", "coffee"),
    # Tea
    ("chá", "cha", "tea", "té"),
    # Water
    ("água", "agua", "water"),
    # Juice
    ("sumo", "suco", "juice", "jugo", "zumo"),
    # Yogurt
    ("iogurte", "yogurt", "yoghurt", "yogur"),
    # Ham
    ("fiambre", "presunto", "ham", "jamón", "jamon"),
    # Tuna
    ("atum", "tuna", "atún", "atun"),
    # Soap / Detergent
    ("sabão", "sabao", "soap", "jabón", "jabon", "detergente", "detergent"),
    # Toilet paper
    (
        "papel higiénico",
        "papel higienico",
        "toilet paper",
        "papel higiênico",
    ),
    # Shampoo
    ("champô", "champo", "shampoo", "champú", "champu"),
)

# Build lookup: word → canonical form
_WORD_TO_CANONICAL: Dict[str, str] = {}
for _group in _SYNONYM_GROUPS:
    _canonical = _group[0]
    for _word in _group:
        _WORD_TO_CANONICAL[_word.lower()] = _canonical


def get_canonical(item: str) -> str:
    """
    Get the canonical form of a grocery item.

    Returns the canonical synonym if found, otherwise returns
    the original item lowered and stripped.

    Examples:
        "bread" → "pão"
        "Milk" → "leite"
        "queijo" → "queijo"
        "something unknown" → "something unknown"
    """
    normalized = item.lower().strip()
    return _WORD_TO_CANONICAL.get(normalized, normalized)


def are_synonyms(item1: str, item2: str) -> bool:
    """
    Check if two items are synonyms (same product in different languages).

    Examples:
        are_synonyms("bread", "pão") → True
        are_synonyms("milk", "leite") → True
        are_synonyms("milk", "bread") → False
    """
    return get_canonical(item1) == get_canonical(item2)


def find_synonym_in_list(
    item: str,
    existing_items: List[str],
) -> Optional[str]:
    """
    Check if a synonym of `item` already exists in `existing_items`.

    Returns the existing item string if found, None otherwise.

    Examples:
        find_synonym_in_list("bread", ["leite", "pão"]) → "pão"
        find_synonym_in_list("rice", ["leite", "pão"]) → None
    """
    canonical = get_canonical(item)
    for existing in existing_items:
        if get_canonical(existing) == canonical:
            return existing
    return None
