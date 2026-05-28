#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _print_fail(provider: str, reason: str) -> int:
    print(json.dumps({"ok": False, "provider": provider, "reason": reason}))
    return 1


def _run_tool(tool: Path, question: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if os.access(tool, os.X_OK):
        cmd = [str(tool), question]
    else:
        cmd = [sys.executable, str(tool), question]
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_wikipedia(root: Path, question: str) -> int:
    tool = root / "tools" / "unverified_context_wikipedia.py"
    if not tool.exists():
        return _print_fail("wikipedia", "missing_wikipedia_tool")
    try:
        sys.path.insert(0, str(tool.parent))
        import unverified_context_wikipedia as wikipedia_provider  # type: ignore

        payload = wikipedia_provider.fetch_context(question)
    except Exception:
        try:
            completed = _run_tool(tool, question)
        except Exception:
            return _print_fail("wikipedia", "provider_exec_failed")
        if completed.returncode != 0:
            return _print_fail("wikipedia", "provider_no_context")
        raw = (completed.stdout or "").strip()
        if not raw:
            return _print_fail("wikipedia", "provider_no_payload")
        try:
            payload = json.loads(raw)
        except Exception:
            return _print_fail("wikipedia", "provider_bad_payload")
    if not isinstance(payload, dict) or not payload.get("ok"):
        return _print_fail("wikipedia", "provider_no_context")
    payload["provider"] = "wikipedia"
    print(json.dumps(payload))
    return 0


def _run_kimi(root: Path, question: str) -> int:
    tool = root / "tools" / "unverified_context_kimi.py"
    if not tool.exists():
        return _print_fail("kimi", "missing_kimi_tool")
    try:
        completed = _run_tool(tool, question)
    except Exception:
        return _print_fail("kimi", "provider_exec_failed")
    if completed.returncode != 0:
        raw_err = (completed.stdout or "").strip()
        try:
            parsed = json.loads(raw_err) if raw_err else {}
        except Exception:
            parsed = {}
        reason = str(parsed.get("reason", "")).strip() or "provider_no_context"
        return _print_fail("kimi", reason)
    raw = (completed.stdout or "").strip()
    if not raw:
        return _print_fail("kimi", "provider_no_payload")
    try:
        payload = json.loads(raw)
    except Exception:
        return _print_fail("kimi", "provider_bad_payload")
    if not isinstance(payload, dict) or not payload.get("ok"):
        return _print_fail("kimi", "provider_no_context")
    payload["provider"] = "kimi"
    print(json.dumps(payload))
    return 0


def _run_openai(root: Path, question: str) -> int:
    tool = root / "tools" / "unverified_context_openai.py"
    if not tool.exists():
        return _print_fail("openai", "missing_openai_tool")
    try:
        completed = _run_tool(tool, question)
    except Exception:
        return _print_fail("openai", "provider_exec_failed")
    if completed.returncode != 0:
        raw_err = (completed.stdout or "").strip()
        try:
            parsed = json.loads(raw_err) if raw_err else {}
        except Exception:
            parsed = {}
        reason = str(parsed.get("reason", "")).strip() or "provider_no_context"
        return _print_fail("openai", reason)
    raw = (completed.stdout or "").strip()
    if not raw:
        return _print_fail("openai", "provider_no_payload")
    try:
        payload = json.loads(raw)
    except Exception:
        return _print_fail("openai", "provider_bad_payload")
    if not isinstance(payload, dict) or not payload.get("ok"):
        return _print_fail("openai", "provider_no_context")
    payload["provider"] = "openai"
    print(json.dumps(payload))
    return 0


def _run_trusted(root: Path, question: str) -> int:
    """Run trusted sources provider for category-specific queries."""
    tool = root / "tools" / "unverified_context_trusted.py"
    if not tool.exists():
        return _print_fail("trusted", "missing_trusted_tool")
    try:
        completed = _run_tool(tool, question)
    except Exception:
        return _print_fail("trusted", "provider_exec_failed")
    if completed.returncode != 0:
        raw_err = (completed.stdout or "").strip()
        try:
            parsed = json.loads(raw_err) if raw_err else {}
        except Exception:
            parsed = {}
        reason = str(parsed.get("reason", "")).strip() or "provider_no_context"
        # "not_applicable" means this provider doesn't handle this query
        if reason == "not_applicable":
            return _print_fail("trusted", "not_applicable")
        return _print_fail("trusted", reason)
    raw = (completed.stdout or "").strip()
    if not raw:
        return _print_fail("trusted", "provider_no_payload")
    try:
        payload = json.loads(raw)
    except Exception:
        return _print_fail("trusted", "provider_bad_payload")
    if not isinstance(payload, dict) or not payload.get("ok"):
        # Check if it's a "not applicable" response (not an error, just not handled)
        if isinstance(payload, dict) and payload.get("reason") == "not_applicable":
            return _print_fail("trusted", "not_applicable")
        return _print_fail("trusted", "provider_no_context")
    payload["provider"] = "trusted"
    print(json.dumps(payload))
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        return _print_fail("", "usage")
    provider = (sys.argv[1] or "").strip().lower()
    question = " ".join(sys.argv[2:]).strip()
    if not provider:
        return _print_fail("", "missing_provider")
    if not question:
        return _print_fail(provider, "missing_question")

    root = Path(os.environ.get("LUCY_ROOT") or Path(__file__).resolve().parents[1]).expanduser()
    if provider == "wikipedia":
        return _run_wikipedia(root, question)
    if provider == "kimi":
        return _run_kimi(root, question)
    if provider == "openai":
        return _run_openai(root, question)
    if provider == "trusted":
        return _run_trusted(root, question)
    return _print_fail(provider, "unsupported_provider")


if __name__ == "__main__":
    raise SystemExit(main())
