from __future__ import annotations
import dataclasses
import os
from pathlib import Path
from typing import Any

import yaml


@dataclasses.dataclass(frozen=True)
class CapabilityFlags:
    source_attribution: bool = False
    suggest_web_escalation: bool = False
    auto_web_general_knowledge: bool = False
    trusted_sources_only_critical: bool = True
    auto_web_allowed_domains: tuple[str, ...] = ()


def load_capability_flags(path: str | Path | None = None) -> CapabilityFlags:
    if path is None:
        root = Path(__file__).resolve().parent.parent.parent.parent
        path = root / "config" / "capability_flags.yaml"
    path = Path(path)
    data: dict[str, Any] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    def _env_bool(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "on", "yes")

    def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return tuple(item.strip() for item in raw.split(",") if item.strip())

    return CapabilityFlags(
        source_attribution=_env_bool("LUCY_SOURCE_ATTRIBUTION", data.get("source_attribution", False)),
        suggest_web_escalation=_env_bool("LUCY_SUGGEST_WEB_ESCALATION", data.get("suggest_web_escalation", False)),
        auto_web_general_knowledge=_env_bool("LUCY_AUTO_WEB_GENERAL_KNOWLEDGE", data.get("auto_web_general_knowledge", False)),
        trusted_sources_only_critical=_env_bool("LUCY_TRUSTED_SOURCES_ONLY_CRITICAL", data.get("trusted_sources_only_critical", True)),
        auto_web_allowed_domains=_env_list(
            "LUCY_AUTO_WEB_ALLOWED_DOMAINS",
            tuple(data.get("auto_web_allowed_domains", [])),
        ),
    )
