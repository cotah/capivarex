"""
Capivarex i18n — Multi-language keyword detection for routing.

Replaces hardcoded Portuguese-only keyword checks in bot.py
with multi-language support (EN, PT, ES).

Usage:
    from services.i18n.keywords import check_keywords, TWILIO_KEYWORDS

    if check_keywords(user_message, TWILIO_KEYWORDS):
        agent_name = "twilio"
"""

import re
from typing import Dict, List


# ══════════════════════════════════════════════════════════════════════════════
# VOICE / AUDIO keywords
# ══════════════════════════════════════════════════════════════════════════════

VOICE_KEYWORDS: Dict[str, List[str]] = {
    "pt": [
        "manda um audio",
        "mande um audio",
        "manda um áudio",
        "mande um áudio",
        "envia audio",
        "envia um áudio",
        "envia um audio",
        "gera audio",
        "gera um audio",
        "gera um áudio",
        "faz um audio",
        "faz um áudio",
        "cria um audio",
        "cria um áudio",
        "mensagem de voz",
        "audio dizendo",
        "áudio dizendo",
        "audio falando",
        "áudio falando",
        "audio que diz",
        "áudio que diz",
        "audio a dizer",
        "áudio a dizer",
        "fala isso",
        "lê isso em voz alta",
        "converte em audio",
        "converte em áudio",
        "produz um audio",
    ],
    "en": [
        "send audio",
        "send an audio",
        "send a voice",
        "make an audio",
        "make a voice",
        "voice message",
        "voice note",
        "generate audio",
        "create audio",
        "text to speech",
        "tts",
        "say this",
        "speak this",
        "read this aloud",
        "read aloud",
        "audio saying",
        "audio that says",
        "convert to audio",
        "convert to speech",
    ],
    "es": [
        "manda un audio",
        "mándame un audio",
        "envía un audio",
        "envía audio",
        "genera un audio",
        "genera audio",
        "crea un audio",
        "mensaje de voz",
        "nota de voz",
        "audio diciendo",
        "audio que diga",
        "convierte en audio",
        "lee esto en voz alta",
        "texto a voz",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# TWILIO / PHONE CALL keywords
# ══════════════════════════════════════════════════════════════════════════════

TWILIO_KEYWORDS: Dict[str, List[str]] = {
    "pt": [
        "liga para",
        "ligar para",
        "faz chamada",
        "faz uma chamada",
        "chamada para",
        "chama o",
        "chama a",
        "telefona para",
        "telefonar para",
        "liga +",
        "liga pro",
        "liga pra",
        "faz uma ligação",
    ],
    "en": [
        "call ",
        "phone call",
        "dial ",
        "ring ",
        "call +",
        "call the",
        "make a call",
        "place a call",
        "give a call",
        "phone ",
    ],
    "es": [
        "llama a",
        "llama al",
        "llamar a",
        "llamar al",
        "haz una llamada",
        "llamada a",
        "llamada al",
        "telefona a",
        "telefonear a",
        "marca a",
        "marca al",
        "llama +",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# TRANSPORT / PUBLIC TRANSIT keywords
# ══════════════════════════════════════════════════════════════════════════════

TRANSPORT_KEYWORDS: Dict[str, List[str]] = {
    "pt": [
        "autocarro",
        "autocarros",
        "comboio",
        "comboios",
        "metro ",
        "metrô",
        "ônibus",
        "onibus",
        "trem ",
        "trens",
        "bus éireann",
        "bus eireann",
        "dublin bus",
        "dart ",
        "luas ",
        "irish rail",
        "próximo autocarro",
        "proximo autocarro",
        "próximo bus",
        "proximo bus",
        "próximo comboio",
        "proximo comboio",
        "horário do bus",
        "horario do bus",
        "paragem",
        "transporte público",
        "transporte publico",
        "como chegar de transporte",
    ],
    "en": [
        "bus ",
        "buses",
        "train ",
        "trains",
        "subway ",
        "metro ",
        "transit",
        "tram",
        "bus éireann",
        "bus eireann",
        "dublin bus",
        "dart ",
        "luas ",
        "irish rail",
        "next bus",
        "next train",
        "bus schedule",
        "train schedule",
        "bus stop",
        "bus route",
        "public transport",
        "public transit",
        "commute by bus",
        "commute by train",
    ],
    "es": [
        "autobús",
        "autobus",
        "tren ",
        "trenes",
        "metro ",
        "tranvía",
        "tranvia",
        "bus éireann",
        "bus eireann",
        "dublin bus",
        "dart ",
        "luas ",
        "irish rail",
        "próximo autobús",
        "proximo autobus",
        "próximo tren",
        "proximo tren",
        "horario del bus",
        "horario del tren",
        "parada de bus",
        "parada de tren",
        "transporte público",
        "transporte publico",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# LEAVING NOW keywords
# ══════════════════════════════════════════════════════════════════════════════

LEAVING_NOW_KEYWORDS: Dict[str, List[str]] = {
    "pt": [
        "quando devo sair",
        "hora de sair",
        "que horas sair",
        "a que horas sair",
        "quanto tempo para chegar",
        "preciso sair",
        "devo sair agora",
        "saio a que horas",
    ],
    "en": [
        "when should i leave",
        "time to leave",
        "when to leave",
        "departure time",
        "how long to get there",
        "should i leave now",
        "need to leave",
    ],
    "es": [
        "cuándo debo salir",
        "cuando debo salir",
        "hora de salir",
        "a qué hora salir",
        "cuánto tiempo para llegar",
        "cuando salir",
        "debo salir ahora",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# MERCADO / SHOPPING LIST keywords
# ══════════════════════════════════════════════════════════════════════════════

MERCADO_KEYWORDS: Dict[str, List[str]] = {
    "pt": [
        "lista de compras",
        "supermercado",
        "mercado",
        "comprar no mercado",
        "adiciona na lista",
        "adicionar na lista",
        "nota fiscal",
        "gastos do mercado",
        "comparar preços",
        "ranking mercados",
    ],
    "en": [
        "shopping list",
        "grocery list",
        "supermarket",
        "groceries",
        "add to list",
        "add to shopping",
        "grocery receipt",
        "shopping expenses",
        "compare prices",
        "store ranking",
    ],
    "es": [
        "lista de compras",
        "supermercado",
        "mercado",
        "comprar en el mercado",
        "añadir a la lista",
        "agregar a la lista",
        "nota de compra",
        "gastos del mercado",
        "comparar precios",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# Utility function
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# TRAVEL / FLIGHTS / HOTELS keywords
# ══════════════════════════════════════════════════════════════════════════════

TRAVEL_KEYWORDS: Dict[str, List[str]] = {
    "en": [
        "flight",
        "flights",
        "fly",
        "airplane",
        "plane",
        "airline",
        "book flight",
        "round trip",
        "one way",
        "layover",
        "stopover",
        "hotel",
        "hotels",
        "stay",
        "accommodation",
        "hostel",
        "airbnb",
        "check in",
        "check out",
        "booking",
        "reservation",
        "travel to",
        "trip to",
        "vacation",
        "holiday",
    ],
    "pt": [
        "voo",
        "voos",
        "voar",
        "avião",
        "aviao",
        "companhia aérea",
        "ida e volta",
        "só ida",
        "escala",
        "hotel",
        "hotéis",
        "estadia",
        "alojamento",
        "hospedagem",
        "reserva",
        "reservar",
        "viagem",
        "viajar",
        "férias",
    ],
    "es": [
        "vuelo",
        "vuelos",
        "volar",
        "avión",
        "ida y vuelta",
        "solo ida",
        "alojamiento",
        "hospedaje",
        "reserva",
        "reservar",
        "viaje",
        "viajar",
        "vacaciones",
    ],
}


def check_keywords(text: str, keyword_map: Dict[str, List[str]]) -> bool:
    """
    Check if text matches any keyword in any language.

    Args:
        text: User message to check
        keyword_map: Dict of {lang: [keywords]} (e.g., TWILIO_KEYWORDS)

    Returns:
        True if any keyword matches (case-insensitive)
    """
    text_lower = text.lower()
    for lang_keywords in keyword_map.values():
        for kw in lang_keywords:
            if kw.lower() in text_lower:
                return True
    return False


def check_keywords_with_phone(text: str) -> bool:
    """
    Check if text contains a phone number pattern combined with
    a call-related word in any language.

    Detects patterns like:
        "+353 89 443 4456 call"
        "call +1 555 1234"
        "liga +351912345678"
    """
    has_phone = bool(re.search(r"\+\d[\d\s\-]{6,}", text))
    if not has_phone:
        return False

    call_words = [
        # PT
        "liga",
        "ligar",
        "chamada",
        "chama",
        "telefon",
        # EN
        "call",
        "phone",
        "dial",
        "ring",
        # ES
        "llama",
        "llamar",
        "llamada",
        "marca",
        "telefon",
    ]
    text_lower = text.lower()
    return any(w in text_lower for w in call_words)
