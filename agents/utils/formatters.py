"""
Response formatters for agents.

Provides:
- Text formatting utilities
- Date/time formatting
- List formatting
- Error message formatting
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import re


def format_datetime(dt: datetime, format_type: str = "friendly") -> str:
    """
    Format datetime in a user-friendly way.

    Args:
        dt: Datetime to format
        format_type: "friendly", "short", or "full"

    Returns:
        Formatted string
    """
    if format_type == "friendly":
        now = datetime.now()
        delta = dt - now

        if delta.days == 0:
            if delta.seconds < 3600:
                minutes = delta.seconds // 60
                return f"in {minutes} minutes"
            else:
                hours = delta.seconds // 3600
                return f"in {hours} hours"
        elif delta.days == 1:
            return f"tomorrow at {dt.strftime('%H:%M')}"
        elif delta.days < 7:
            return dt.strftime("%A at %H:%M")
        else:
            return dt.strftime("%B %d at %H:%M")

    elif format_type == "short":
        return dt.strftime("%m/%d %H:%M")

    else:  # full
        return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_list(items: List[str], max_items: int = 5, bullet: str = "•") -> str:
    """
    Format a list of items with bullets.

    Args:
        items: List of items
        max_items: Maximum items to show
        bullet: Bullet character

    Returns:
        Formatted string
    """
    if not items:
        return "No items"

    lines = []
    for i, item in enumerate(items[:max_items]):
        lines.append(f"{bullet} {item}")

    if len(items) > max_items:
        remaining = len(items) - max_items
        lines.append(f"... and {remaining} more")

    return "\n".join(lines)


def format_dict(data: Dict[str, Any], indent: int = 0) -> str:
    """
    Format a dictionary for display.

    Args:
        data: Dictionary to format
        indent: Indentation level

    Returns:
        Formatted string
    """
    lines = []
    prefix = "  " * indent

    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(format_dict(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}: {', '.join(str(v) for v in value)}")
        else:
            lines.append(f"{prefix}{key}: {value}")

    return "\n".join(lines)


def format_error(error: str, context: Optional[str] = None) -> str:
    """
    Format an error message for display.

    Args:
        error: Error message
        context: Optional context

    Returns:
        Formatted error string
    """
    message = f"❌ Error: {error}"
    if context:
        message += f"\n\nContext: {context}"
    return message


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Truncate text to maximum length.

    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def clean_text(text: str) -> str:
    """
    Clean text by removing extra whitespace and special characters.

    Args:
        text: Text to clean

    Returns:
        Cleaned text
    """
    # Remove extra whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove leading/trailing whitespace
    text = text.strip()
    return text


def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Format a float as percentage.

    Args:
        value: Value between 0 and 1
        decimals: Number of decimal places

    Returns:
        Formatted percentage string
    """
    return f"{value * 100:.{decimals}f}%"


def format_currency(
    amount: float, currency: str = "USD", symbol: Optional[str] = None
) -> str:
    """
    Format amount as currency.

    Args:
        amount: Amount to format
        currency: Currency code
        symbol: Currency symbol (auto-detected if None)

    Returns:
        Formatted currency string
    """
    if symbol is None:
        symbols = {
            "USD": "$",
            "EUR": "€",
            "GBP": "£",
            "BRL": "R$",
        }
        symbol = symbols.get(currency, currency)

    return f"{symbol}{amount:,.2f}"
