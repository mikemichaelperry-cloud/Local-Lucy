#!/usr/bin/env python3
"""Shared news data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NewsResult:
    """Result from news fetching."""

    ok: bool
    text: str
    source: str
    error: str = ""
    articles: list[dict[str, Any]] | None = None
    partial: bool = False
    errors: list[str] | None = None
    html_text: str = ""
    disagreement: bool = False
