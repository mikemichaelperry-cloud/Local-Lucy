#!/usr/bin/env python3
"""Backward-compatible facade for router_py.state.

The monolithic state_manager.py was split into the router_py.state package.
This module re-exports the public API so existing imports continue to work.
"""

from __future__ import annotations

from router_py.state import SCHEMA_SQL, StateManager, get_state_manager, init_database

__all__ = ["StateManager", "get_state_manager", "init_database", "SCHEMA_SQL"]
