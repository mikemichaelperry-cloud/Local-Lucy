"""Backend package for Local Lucy v8."""
from __future__ import annotations

import sys
from pathlib import Path

# Setup paths for backend imports
BACKEND_DIR = Path(__file__).parent

# Add router/core to path for intent_classifier
CORE_DIR = BACKEND_DIR / "router" / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

# Add router to path
ROUTER_DIR = BACKEND_DIR / "router"
if str(ROUTER_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTER_DIR))

# Now do imports
from .policy import (
    normalize_augmentation_policy,
    requires_evidence_mode,
    provider_usage_class_for,
)

from .classify import (
    ClassificationResult,
    RoutingDecision,
    classify_intent,
    select_route,
)

from .main import (
    RouterOutcome,
    ShadowComparison,
    execute_plan_python,
)

__all__ = [
    'normalize_augmentation_policy',
    'requires_evidence_mode',
    'provider_usage_class_for',
    'ClassificationResult',
    'RoutingDecision',
    'classify_intent',
    'select_route',
    'RouterOutcome',
    'ShadowComparison',
    'execute_plan_python',
]
