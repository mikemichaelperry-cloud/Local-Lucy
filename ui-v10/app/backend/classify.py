"""Re-export for backward compatibility — implementation lives in router_py."""

from router_py.classify import classify_intent, select_route
from router_py.request_types import ClassificationResult, RoutingDecision

__all__ = ["classify_intent", "select_route", "ClassificationResult", "RoutingDecision"]
