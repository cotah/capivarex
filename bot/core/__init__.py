"""
Core modules for CAPIVAREX Bot.

Provides:
- ConfigManager: Configuration and credit system
- MemoryManager: Notes and preferences
- TenancyManager: Multi-tenancy and identity mapping
- TenantContext: Tenant context dataclass
"""

from .config import ConfigManager
from .memory import MemoryManager
from .tenancy import TenancyManager, TenantContext

__all__ = [
    "ConfigManager",
    "MemoryManager",
    "TenancyManager",
    "TenantContext",
]
