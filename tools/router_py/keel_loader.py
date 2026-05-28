"""Keel loader — loads keel/keel.yaml and returns formatted text for prompt injection.

This module is safe to import even when the keel file is missing or malformed.
It returns an empty string on any failure, so prompt construction never breaks.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Project root candidates (tries repo first, then explicit fallback)
_ROOT_CANDIDATES = [
    Path(__file__).resolve().parent.parent.parent,  # tools/router_py/../../
    Path("/home/mike/lucy-v10"),
]


def _find_keel_path() -> Path | None:
    for root in _ROOT_CANDIDATES:
        keel_path = root / "keel" / "keel.yaml"
        if keel_path.exists():
            return keel_path
    return None


def _format_keel(raw: dict[str, Any]) -> str:
    """Convert keel YAML dict to a concise plain-text policy block."""
    if not raw or not isinstance(raw, dict):
        return ""

    parts: list[str] = ["[KEEL — Hard Constraints]"]

    # Capabilities
    caps = raw.get("capabilities")
    if isinstance(caps, dict):
        parts.append("Capabilities:")
        for k, v in caps.items():
            parts.append(f"  - {k}: {v}")

    # Provider policy
    prov = raw.get("provider_policy")
    if isinstance(prov, dict):
        parts.append("Provider Policy:")
        for k, v in prov.items():
            if isinstance(v, list):
                parts.append(f"  - {k}: {', '.join(str(x) for x in v)}")
            else:
                parts.append(f"  - {k}: {v}")

    # HMI authority
    hmi = raw.get("hmi_authority")
    if isinstance(hmi, dict):
        parts.append("HMI Authority:")
        for k, v in hmi.items():
            parts.append(f"  - {k}: {v}")

    # Multilingual capability
    multi = raw.get("multilingual_capability")
    if isinstance(multi, dict):
        parts.append("Multilingual Capability:")
        for k, v in multi.items():
            parts.append(f"  - {k}: {v}")

    # Auto-learn gating
    al = raw.get("auto_learn")
    if isinstance(al, dict):
        parts.append("Auto-Learn:")
        for k, v in al.items():
            parts.append(f"  - {k}: {v}")

    # Session policy (concise)
    sess = raw.get("session_policy")
    if isinstance(sess, dict):
        parts.append("Session Policy:")
        for k, v in sess.items():
            if isinstance(v, dict):
                parts.append(f"  {k}:")
                for sk, sv in v.items():
                    parts.append(f"    - {sk}: {sv}")
            else:
                parts.append(f"  - {k}: {v}")

    # Refusals
    refs = raw.get("refusals")
    if isinstance(refs, dict):
        parts.append("Refusals:")
        for k, v in refs.items():
            parts.append(f"  - {k}: {v}")

    parts.append("[END KEEL]")
    return "\n".join(parts)


def load_keel_status() -> dict[str, Any]:
    """Load keel and return structured status.

    Returns a dict with:
      loaded: bool
      path: str
      version: str | None
      sha256: str | None
      error: str | None
      rendered_text: str
    """
    status: dict[str, Any] = {
        "loaded": False,
        "path": "",
        "version": None,
        "sha256": None,
        "error": None,
        "rendered_text": "",
    }

    try:
        import yaml
    except ImportError as exc:
        status["error"] = f"PyYAML not available: {exc}"
        logger.warning(status["error"])
        return status

    keel_path = _find_keel_path()
    if keel_path is None:
        status["error"] = "keel.yaml not found"
        logger.warning(status["error"])
        return status

    status["path"] = str(keel_path)

    try:
        raw_text = keel_path.read_text(encoding="utf-8")
    except Exception as exc:
        status["error"] = f"Failed to read keel: {exc}"
        logger.warning(status["error"])
        return status

    # SHA-256 of raw file content
    try:
        status["sha256"] = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    except Exception:
        pass

    try:
        raw = yaml.safe_load(raw_text)
    except Exception as exc:
        status["error"] = f"Malformed YAML: {exc}"
        logger.warning(status["error"])
        return status

    if raw is None or not isinstance(raw, dict):
        status["error"] = "keel.yaml empty or malformed"
        logger.warning(status["error"])
        return status

    status["version"] = raw.get("version") if isinstance(raw, dict) else None
    text = _format_keel(raw)
    if len(text) > 4096:
        logger.warning("keel.yaml exceeds 4KB, truncating")
        text = text[:4096]
    status["rendered_text"] = text
    status["loaded"] = True
    return status


def load_keel_text() -> str:
    """Load and format keel text. Returns empty string on any failure.

    This is intentionally fail-silent: if the keel is missing, malformed,
    or PyYAML is unavailable, the system continues without it.
    """
    return load_keel_status()["rendered_text"]
