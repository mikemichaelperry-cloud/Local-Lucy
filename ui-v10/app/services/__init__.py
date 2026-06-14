"""Services package — canonical runtime bridge."""

from app.services.runtime_bridge import (
    CommandResult,
    RuntimeActionTask,
    RuntimeBridge,
)

USE_CONSOLIDATED = True

__all__ = ["RuntimeBridge", "CommandResult", "RuntimeActionTask", "USE_CONSOLIDATED"]
