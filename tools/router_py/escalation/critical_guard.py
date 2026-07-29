#!/usr/bin/env python3
"""Critical-category guard for web-fetch escalation.

Blocks automatic web fetching for sensitive topics regardless of capability
flags. The category list is shared with the escalation suggestion logic so
policy stays consistent.
"""

from __future__ import annotations

from router_py.escalation.config import CRITICAL_CATEGORIES
from router_py.request_types import ClassificationResult


def is_critical_category(classification: ClassificationResult) -> bool:
    """Return True when the classification is in a critical category.

    Critical categories include medical, financial, legal, safety, identity,
    and related regulatory/market/travel topics. Web search must not be
    performed automatically for these.
    """
    category = (classification.category or "").lower()
    return any(crit in category for crit in CRITICAL_CATEGORIES)
