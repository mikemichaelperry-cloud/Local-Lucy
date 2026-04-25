#!/usr/bin/env python3
"""
Router utility functions - Python port of shell implementations.
Maintains deterministic behavior matching original shell functions.
"""

import hashlib
import re


def sha256_text(s: str) -> str:
    """
    Compute SHA256 hash of input string.
    Falls back to MD5 if SHA256 unavailable (for compatibility).
    
    Args:
        s: Input string to hash
        
    Returns:
        Hexadecimal hash string
    """
    try:
        return hashlib.sha256(s.encode('utf-8')).hexdigest()
    except Exception:
        # Fallback to MD5 for compatibility
        return hashlib.md5(s.encode('utf-8')).hexdigest()


def guard_normalize(text: str) -> str:
    """
    Normalize text for guard/comparison purposes.
    Converts to lowercase, collapses whitespace, strips ends.
    
    Args:
        text: Input text to normalize
        
    Returns:
        Normalized text string
    """
    # Convert to lowercase
    result = text.lower()
    # Collapse multiple whitespace to single space
    result = re.sub(r'\s+', ' ', result)
    # Strip leading/trailing whitespace
    result = result.strip()
    return result


def deterministic_pick_index(seed: str, mod: int) -> int:
    """
    Deterministically pick an index from 0 to mod-1 based on seed.
    Uses first 8 hex chars of SHA256 hash modulo mod.
    
    Args:
        seed: Seed string for deterministic selection
        mod: Modulus (number of choices)
        
    Returns:
        Integer index in range [0, mod-1]
    """
    h = sha256_text(seed)
    # Take first 8 hex chars and convert to int
    hex_val = int(h[:8], 16)
    return hex_val % mod


# Allowed repeat bodies - normalized forms that are acceptable repeats
_ALLOWED_REPEAT_BODIES = {
    "i could not generate a reply locally. please retry, or switch mode.",
    "error"
}


def is_allowed_repeat_body(body: str) -> bool:
    """
    Check if a response body is an allowed repeat (e.g., error messages).
    
    Args:
        body: Response body text
        
    Returns:
        True if repeat is allowed, False otherwise
    """
    normalized = guard_normalize(body)
    return normalized in _ALLOWED_REPEAT_BODIES


if __name__ == "__main__":
    # Quick sanity check
    print("sha256_text('test'):", sha256_text("test")[:16], "...")
    print("guard_normalize('  Hello   WORLD  '):", guard_normalize("  Hello   WORLD  "))
    print("deterministic_pick_index('seed', 10):", deterministic_pick_index("seed", 10))
