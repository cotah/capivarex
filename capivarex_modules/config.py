# capivarex_modules/config.py
"""
CAPIVAREX Module Configuration
Defines the 8 capivara modules and their agent mappings.
This is the single source of truth for module-to-agent relationships.
"""
from typing import Dict, List, Set

# Status constants
MODULE_STATUS_ACTIVE = "active"
MODULE_STATUS_COMING_SOON = "coming_soon"
MODULE_STATUS_DISABLED = "disabled"

# Internal modules — not sold as subscriptions, always active for all users
INTERNAL_MODULES: Set[str] = {"tupa"}

# Complete module definition
CAPIVARA_MODULES: Dict[str, Dict] = {
    "ara": {
        "name": "ARA",
        "full_name": "ARA — Life & Time",
        "description": "Your day, before it begins. Calendar, reminders, weather, notes, voice.",
        "color": "#D4A017",
        "emoji": "🟡",
        "status": MODULE_STATUS_ACTIVE,
        "always_included": True,  # ARA is always unlocked — it's the base product
        "agents": [
            "chat", "calendar", "reminder", "weather", "notes",
            "timer", "translate", "research", "search", "voice",
            "meeting", "tracking", "maps"
        ],
        "stripe_price_env": "STRIPE_PRICE_ARA",  # env var name for Stripe price ID
        "price_eur": 19.99,
    },
    "ivi": {
        "name": "IVI",
        "full_name": "IVI — Finance & Crypto",
        "description": "Your financial intelligence. Stocks, crypto, expense tracking.",
        "color": "#2ECC71",
        "emoji": "💚",
        "status": MODULE_STATUS_COMING_SOON,
        "always_included": False,
        "agents": ["finance", "crypto", "mercado"],
        "stripe_price_env": "STRIPE_PRICE_IVI",
        "price_eur": 9.99,
    },
    "oka": {
        "name": "OKA",
        "full_name": "OKA — Home & IoT",
        "description": "Your smart home command center. Lights, temperature, connected car.",
        "color": "#3498DB",
        "emoji": "🔵",
        "status": MODULE_STATUS_COMING_SOON,
        "always_included": False,
        "agents": ["smarthome", "car"],
        "stripe_price_env": "STRIPE_PRICE_OKA",
        "price_eur": 9.99,
    },
    "yara": {
        "name": "YARA",
        "full_name": "YARA — Travel & Mobility",
        "description": "Your travel companion. Flights, hotels, traffic, public transport.",
        "color": "#9B59B6",
        "emoji": "🟣",
        "status": MODULE_STATUS_COMING_SOON,
        "always_included": False,
        "agents": ["travel", "traffic", "transport", "leaving_now", "restaurant"],
        "stripe_price_env": "STRIPE_PRICE_YARA",
        "price_eur": 9.99,
    },
    "ayvu": {
        "name": "AYVU",
        "full_name": "AYVU — Voice & Media",
        "description": "Your voice and entertainment hub. Phone calls, music, YouTube, Chromecast.",
        "color": "#E91E8C",
        "emoji": "🩷",
        "status": MODULE_STATUS_COMING_SOON,
        "always_included": False,
        "agents": ["twilio", "music", "youtube", "media_cast"],
        "stripe_price_env": "STRIPE_PRICE_AYVU",
        "price_eur": 14.99,  # Higher price due to ElevenLabs ConvAI cost
    },
    "mbae": {
        "name": "MBAE",
        "full_name": "MBAE — Work & Productivity",
        "description": "Your professional assistant. Email, GitHub, dev tools, Notion.",
        "color": "#E67E22",
        "emoji": "🟠",
        "status": MODULE_STATUS_COMING_SOON,
        "always_included": False,
        "agents": ["email", "dev", "github"],
        "stripe_price_env": "STRIPE_PRICE_MBAE",
        "price_eur": 9.99,
    },
    "pora": {
        "name": "PORA",
        "full_name": "PORA — Vision & Creative",
        "description": "Your creative studio. AI image generation, video creation.",
        "color": "#1ABC9C",
        "emoji": "🩵",
        "status": MODULE_STATUS_DISABLED,  # Agents currently disabled
        "always_included": False,
        "agents": ["image", "video"],
        "stripe_price_env": "STRIPE_PRICE_PORA",
        "price_eur": 9.99,
    },
    # TUPA — Security é uma camada de infraestrutura interna.
    # Não é vendida como módulo. Está ativa em todos os planos automaticamente.
    # Gerenciada em cybersecurity/ e autofix/ — não requer controle de acesso por subscription.
}

# Reverse lookup: agent_name → module_name
AGENT_TO_MODULE: Dict[str, str] = {}
for _module_name, _module_data in CAPIVARA_MODULES.items():
    for _agent in _module_data["agents"]:
        AGENT_TO_MODULE[_agent] = _module_name

# Core agents that bypass module checking (always available)
CORE_AGENTS: Set[str] = {"orchestrator", "chat"}  # chat is in ARA but also used as fallback


def get_module_for_agent(agent_name: str) -> str:
    """Returns the module name for a given agent. Defaults to 'ara' for unknown agents."""
    return AGENT_TO_MODULE.get(agent_name, "ara")


def get_agents_for_module(module_name: str) -> List[str]:
    """Returns all agent names for a given module."""
    return CAPIVARA_MODULES.get(module_name, {}).get("agents", [])


def is_core_agent(agent_name: str) -> bool:
    """Returns True if the agent bypasses module access checking."""
    return agent_name in CORE_AGENTS
