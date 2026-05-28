"""Classify module - wrapper to single source of truth.

⚠️  WARNING: This file is a RE-EXPORT WRAPPER ONLY.
Do NOT add logic here. The real implementation lives in:
    tools/router_py/classify.py

If you need to change routing, guards, or classification behaviour,
edit tools/router_py/classify.py and let this wrapper pick it up
automatically via backend/__init__.py.
"""
from backend import classify_intent, select_route, ClassificationResult, RoutingDecision
__all__ = ['classify_intent', 'select_route', 'ClassificationResult', 'RoutingDecision']
