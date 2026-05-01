#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runtime_control import (
    RuntimeControlError,
    default_state,
    enforce_authority_contract,
    iso_now,
    load_or_create_state,
    locked_state_file,
    normalize_state,
    read_state_file,
    resolve_state_file,
    write_state_file,
)


PROFILE_FIELDS = ("profile", "model", "status")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        enforce_authority_contract(expected_authority_root=Path(__file__).resolve().parents[1])
        state_file = resolve_state_file(args.state_file)
        if args.command == "show":
            state = load_or_create_state(state_file, refresh_timestamp=False)
            print(json.dumps(build_payload("show", state_file, state, changed=False, changed_fields=[]), sort_keys=True))
            return 0
        if args.command == "reload":
            payload = reload_profile_state(state_file)
            print(json.dumps(payload, sort_keys=True))
            return 0
        raise RuntimeControlError(f"unsupported command: {args.command}")
    except RuntimeControlError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Authoritative Local Lucy runtime profile reload endpoints.",
    )
    parser.add_argument(
        "--state-file",
        help="Override the authoritative runtime state file path.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("reload")
    subparsers.add_parser("show")
    return parser


def reload_profile_state(state_file: Path) -> dict[str, Any]:
    with locked_state_file(state_file):
        current_state = read_state_file(state_file)
        state = normalize_state(current_state)
        defaults = default_state()
        changed_fields: list[str] = []

        for field in PROFILE_FIELDS:
            requested_value = defaults[field] if field != "status" else "ready"
            if state.get(field) != requested_value:
                changed_fields.append(field)
            state[field] = requested_value

        state["last_updated"] = iso_now()
        write_state_file(state_file, state)
        return build_payload(
            "reload",
            state_file,
            state,
            changed=bool(changed_fields),
            changed_fields=changed_fields,
        )


def build_payload(
    action: str,
    state_file: Path,
    state: dict[str, Any],
    *,
    changed: bool,
    changed_fields: list[str],
) -> dict[str, Any]:
    return {
        "ok": True,
        "action": action,
        "changed": changed,
        "changed_fields": changed_fields,
        "state_file": str(state_file),
        "state": state,
    }


if __name__ == "__main__":
    sys.exit(main())
