"""Re-export for backward compatibility — implementation lives in router_py."""

from router_py.policy import (
    normalize_augmentation_policy,
    requires_evidence_mode,
    provider_usage_class_for,
)

__all__ = ["normalize_augmentation_policy", "requires_evidence_mode", "provider_usage_class_for"]
