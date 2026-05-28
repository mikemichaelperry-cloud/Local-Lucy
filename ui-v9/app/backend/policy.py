"""Policy module - wrapper to single source of truth.

⚠️  WARNING: This file is a RE-EXPORT WRAPPER ONLY.
Do NOT add logic here. The real implementation lives in:
    tools/router_py/policy.py

If you need to change evidence mode detection, augmentation policy,
or guard logic, edit tools/router_py/policy.py and let this wrapper
pick it up automatically via backend/__init__.py.
"""
from backend import normalize_augmentation_policy, requires_evidence_mode, provider_usage_class_for
__all__ = ['normalize_augmentation_policy', 'requires_evidence_mode', 'provider_usage_class_for']
