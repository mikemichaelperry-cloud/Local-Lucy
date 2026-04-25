#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_UI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_UI_ROOT))

# Set required environment variables before importing state_store
os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v7")
os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = "/home/mike/lucy/snapshots/opt-experimental-v7-dev"
os.environ["LUCY_UI_ROOT"] = str(REPO_UI_ROOT)
os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"

from app.services.state_store import resolve_last_request_paid, resolve_last_request_provider


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    assert_ok(resolve_last_request_provider(None) == "unknown", "missing payload should stay unknown")
    assert_ok(resolve_last_request_paid(None) == "unknown", "missing payload paid state should stay unknown")

    local_payload = {"outcome": {"augmented_provider_used": "none", "augmented_paid_provider_invoked": "false"}}
    assert_ok(resolve_last_request_provider(local_payload) == "none", "local request should report provider none")
    assert_ok(resolve_last_request_paid(local_payload) == "no", "local request should report paid=no")

    wiki_payload = {"outcome": {"augmented_provider_used": "wikipedia", "augmented_paid_provider_invoked": "false"}}
    assert_ok(resolve_last_request_provider(wiki_payload) == "wikipedia", "wikipedia fallback should report wikipedia")
    assert_ok(resolve_last_request_paid(wiki_payload) == "no", "wikipedia fallback should report paid=no")

    openai_payload = {"outcome": {"augmented_provider_used": "openai", "augmented_paid_provider_invoked": "true"}}
    assert_ok(resolve_last_request_provider(openai_payload) == "openai", "openai request should report openai")
    assert_ok(resolve_last_request_paid(openai_payload) == "yes", "openai paid invocation should report yes")

    legacy_payload = {"outcome": {"augmented_provider": "grok"}}
    assert_ok(resolve_last_request_provider(legacy_payload) == "grok", "legacy provider field should still be honored")
    assert_ok(resolve_last_request_paid(legacy_payload) == "unknown", "paid state should stay unknown without explicit flag")

    print("STATE_STORE_LAST_REQUEST_PROVIDER_TRUTH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
