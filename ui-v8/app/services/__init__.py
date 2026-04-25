"""Services package with consolidated runtime bridge."""

import os

# Use consolidated bridge when LUCY_USE_CONSOLIDATED_BRIDGE is set
# Default is now consolidated (pure Python) for v9+ architecture
if os.environ.get("LUCY_USE_CONSOLIDATED_BRIDGE", "1") == "1":
    from app.services.runtime_bridge_consolidated import ConsolidatedRuntimeBridge
    RuntimeBridge = ConsolidatedRuntimeBridge
    USE_CONSOLIDATED = True
else:
    from app.services.runtime_bridge import RuntimeBridge
    USE_CONSOLIDATED = False

__all__ = ["RuntimeBridge", "USE_CONSOLIDATED"]
