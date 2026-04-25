"""
UI Level definitions for 3-level HMI structure.

SIMPLE:     Calm, focused assistant surface (default)
POWER:      Practical operator controls without engineering detail
ENGINEERING: Full inspectability and low-level access
"""
from __future__ import annotations

# New 3-level HMI structure
SIMPLE = "simple"
POWER = "power"
ENGINEERING = "engineering"

LEVELS = (SIMPLE, POWER, ENGINEERING)

LEVEL_LABELS = {
    SIMPLE: "Simple",
    POWER: "Power",
    ENGINEERING: "Engineering",
}

LEVEL_ORDER = {level: index for index, level in enumerate(LEVELS)}

# Legacy aliases for backward compatibility
LEGACY_LEVEL_ALIASES = {
    # Old names mapped to new
    "operator": SIMPLE,
    "advanced": ENGINEERING,
    # Alternative names
    "basic": SIMPLE,
    "standard": POWER,
    "dev": ENGINEERING,
    "debug": ENGINEERING,
}


def normalize_level(value: str | None) -> str:
    """Normalize a level string to one of the three valid levels."""
    raw = (value or "").strip().lower()
    raw = LEGACY_LEVEL_ALIASES.get(raw, raw)
    if raw in LEVEL_ORDER:
        return raw
    return SIMPLE  # Default to simple for calm experience


def display_level(level: str | None) -> str:
    """Get the display name for a level."""
    return LEVEL_LABELS[normalize_level(level)]


def level_at_least(level: str | None, minimum: str) -> bool:
    """Check if current level is at least the minimum level."""
    current = normalize_level(level)
    return LEVEL_ORDER[current] >= LEVEL_ORDER[normalize_level(minimum)]


def is_simple(level: str | None) -> bool:
    """Check if level is SIMPLE."""
    return normalize_level(level) == SIMPLE


def is_power(level: str | None) -> bool:
    """Check if level is POWER."""
    return normalize_level(level) == POWER


def is_engineering(level: str | None) -> bool:
    """Check if level is ENGINEERING."""
    return normalize_level(level) == ENGINEERING
