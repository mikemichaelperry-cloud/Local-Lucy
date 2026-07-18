#!/usr/bin/env python3
"""Explicit V10 -> V11 migration utility for Local Lucy.

This script is intentionally standalone and explicit: it never runs automatically,
opens all V10 sources read-only, and backs up any existing V11 state before
overwriting it.

Subcommands:
    dry-run     Discover V10 sources and print what would be migrated.
    migrate     Copy V10 databases and JSON state into V11 paths.
    verify      Re-read the migration report and check V11 counts match.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Import xdg_paths from the same tools package. We keep the script runnable
# directly, so we add the project root to sys.path when needed.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _import_xdg_paths() -> Any:
    """Import tools.xdg_paths, ensuring the project root is on sys.path."""
    root = str(_PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from tools import xdg_paths

    return xdg_paths


# ---------------------------------------------------------------------------
# Paths and discovery
# ---------------------------------------------------------------------------

DEFAULT_V10_ROOTS = [
    Path("/home/mike/lucy-v10"),
    Path.home() / ".codex-api-home" / "lucy" / "runtime-v10",
]
DEFAULT_V10_RUNTIME_ROOT = Path.home() / ".codex-api-home" / "lucy" / "runtime-v10"

JSON_STATE_FILES = [
    "current_state.json",
    "last_request_result.json",
    "last_route.json",
    "voice_runtime.json",
    "health.json",
]


class MigrationError(Exception):
    """Raised for fatal migration errors with a user-facing message."""


class AmbiguousSourceError(MigrationError):
    """Raised when multiple V10 roots are discovered."""


def _resolve_v10_root(cli_root: str | None, env_root: str | None) -> Path | None:
    """Resolve the V10 root directory using CLI arg, env var, or defaults."""
    explicit = (cli_root or env_root or "").strip()
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not root.is_dir():
            raise MigrationError(f"Explicit V10 root does not exist: {root}")
        return root

    valid_defaults: list[Path] = []
    for candidate in DEFAULT_V10_ROOTS:
        candidate = candidate.expanduser().resolve()
        # A default root is considered valid if it contains the canonical
        # V10 state database. This avoids treating an empty or unrelated
        # directory as a source of truth.
        if (candidate / "state" / "lucy_state.db").is_file():
            valid_defaults.append(candidate)

    if len(valid_defaults) > 1:
        raise AmbiguousSourceError(
            "Multiple V10 roots discovered; refusing to guess.\n"
            f"  {', '.join(str(p) for p in valid_defaults)}\n"
            "Use --v10-root or set LUCY_V10_ROOT to disambiguate."
        )
    return valid_defaults[0] if valid_defaults else None


def _resolve_v10_runtime_root(cli_root: str | None, env_root: str | None) -> Path | None:
    """Resolve the V10 runtime root directory."""
    explicit = (cli_root or env_root or "").strip()
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not root.is_dir():
            raise MigrationError(f"Explicit V10 runtime root does not exist: {root}")
        return root

    default = DEFAULT_V10_RUNTIME_ROOT.expanduser().resolve()
    return default if default.is_dir() else None


def _v11_state_dir() -> Path:
    """Return the V11 state directory from tools.xdg_paths."""
    xdg_paths = _import_xdg_paths()
    return xdg_paths.lucy_state_dir()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _list_tables(conn: sqlite3.Connection) -> list[str]:
    """Return user-visible table names from a SQLite connection."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return [row[0] for row in cursor.fetchall()]


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return row counts for every user table in the database."""
    counts: dict[str, int] = {}
    for table in _list_tables(conn):
        try:
            row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            counts[table] = row[0] if row else 0
        except sqlite3.Error as exc:
            counts[table] = -1
            print(f"    Warning: could not count table {table}: {exc}", file=sys.stderr)
    return counts


def _backup_sqlite(src: Path, dst: Path) -> dict[str, int]:
    """Copy a SQLite database read-only from src to dst, returning table counts.

    The source is opened with URI mode=ro so we never take a write lock or
    modify V10.  We use the SQLite backup API, which produces a standalone
    destination file that replays any committed WAL data visible to the
    read-only connection.
    """
    src_uri = f"{src.as_uri()}?mode=ro"
    src_conn = sqlite3.connect(src_uri, uri=True)
    try:
        src_counts = _table_counts(src_conn)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            raise MigrationError(
                f"Destination {dst} already exists; migration logic must back it up first"
            )
        dst_conn = sqlite3.connect(dst)
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
            dst_counts = _table_counts(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return {"src": src_counts, "dst": dst_counts}


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")


def _backup_existing(path: Path) -> Path | None:
    """Move an existing file to a timestamped .pre-migration-<ts>.bak backup."""
    if not path.exists():
        return None
    backup = path.parent / f"{path.name}.pre-migration-{_timestamp()}.bak"
    shutil.move(str(path), str(backup))
    return backup


def _copy_json(src: Path, dst: Path) -> Path | None:
    """Copy a JSON state file, backing up any existing destination."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    backup = _backup_existing(dst)
    shutil.copy2(src, dst)
    return backup


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _report_path(state_dir: Path) -> Path:
    return state_dir / "migration_report.json"


def _write_report(state_dir: Path, report: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _report_path(state_dir)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
    tmp.replace(path)


def _load_report(state_dir: Path) -> dict[str, Any]:
    path = _report_path(state_dir)
    if not path.is_file():
        raise MigrationError(f"Migration report not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Core migration logic
# ---------------------------------------------------------------------------


def _discover_sources(
    v10_root: Path | None, v10_runtime: Path | None
) -> list[dict[str, Any]]:
    """Build the canonical list of source -> destination mappings.

    Warns about expected source files that are missing, but still only returns
    items that actually exist.
    """
    state_dir = _v11_state_dir()
    sources: list[dict[str, Any]] = []

    expected_dbs: list[tuple[Path | None, Path, str]] = []
    if v10_root is not None:
        expected_dbs.append((v10_root / "state" / "lucy_state.db", state_dir / "lucy_state.db", "lucy_state.db"))
    if v10_runtime is not None:
        expected_dbs.append((v10_runtime / "state" / "memory.db", state_dir / "memory.db", "memory.db"))
        expected_dbs.append((v10_runtime / "session_memory.db", state_dir / "session_memory.db", "session_memory.db"))

    for src_db, dst_db, name in expected_dbs:
        if src_db is not None and src_db.is_file():
            sources.append({"kind": "database", "name": name, "src": src_db, "dst": dst_db})
        elif src_db is not None:
            print(f"  Warning: expected V10 database missing: {src_db}", file=sys.stderr)

    if v10_runtime is not None:
        for json_name in JSON_STATE_FILES:
            src_json = v10_runtime / "state" / json_name
            if src_json.is_file():
                sources.append(
                    {
                        "kind": "json",
                        "name": json_name,
                        "src": src_json,
                        "dst": state_dir / json_name,
                    }
                )
            else:
                print(f"  Warning: expected V10 JSON state missing: {src_json}", file=sys.stderr)

    return sources


def _gather_metadata(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich source mappings with size/count metadata without writing."""
    enriched: list[dict[str, Any]] = []
    for item in sources:
        meta: dict[str, Any] = dict(item)
        meta["src_size"] = item["src"].stat().st_size
        if item["kind"] == "database":
            try:
                conn = sqlite3.connect(f"{item['src'].as_uri()}?mode=ro", uri=True)
                try:
                    counts = _table_counts(conn)
                    meta["src_rows"] = sum(c for c in counts.values() if c >= 0)
                    meta["src_tables"] = sorted(counts.keys())
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                meta["src_rows"] = None
                meta["src_tables"] = []
                meta["warning"] = f"Could not read database: {exc}"
        enriched.append(meta)
    return enriched


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Print discovered sources and destinations without writing."""
    v10_root = _resolve_v10_root(args.v10_root, os.environ.get("LUCY_V10_ROOT"))
    v10_runtime = _resolve_v10_runtime_root(
        args.v10_runtime_root, os.environ.get("LUCY_V10_RUNTIME_ROOT")
    )
    sources = _discover_sources(v10_root, v10_runtime)
    print("V10 -> V11 migration dry-run")
    if not sources:
        print("No V10 sources found; nothing to migrate.")
        return 0

    print(f"  V10 root:        {v10_root or '(none)'}")
    print(f"  V10 runtime:     {v10_runtime or '(none)'}")
    print(f"  V11 state dir:   {_v11_state_dir()}")
    print()
    enriched = _gather_metadata(sources)
    for item in enriched:
        if item["kind"] == "database":
            rows = item.get("src_rows")
            rows_text = f"{rows} rows" if rows is not None else "unknown rows"
            print(
                f"  [DB]  {item['name']}: {item['src']} ({item['src_size']} bytes, "
                f"{rows_text}, tables={item.get('src_tables', [])}) -> {item['dst']}"
            )
        else:
            print(
                f"  [JSON] {item['name']}: {item['src']} ({item['src_size']} bytes) -> {item['dst']}"
            )
        warning = item.get("warning")
        if warning:
            print(f"    WARNING: {warning}")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    """Copy V10 state into V11 paths, backing up existing V11 files first."""
    state_dir = _v11_state_dir()
    v10_root = _resolve_v10_root(args.v10_root, os.environ.get("LUCY_V10_ROOT"))
    v10_runtime = _resolve_v10_runtime_root(
        args.v10_runtime_root, os.environ.get("LUCY_V10_RUNTIME_ROOT")
    )
    sources = _discover_sources(v10_root, v10_runtime)
    if not sources:
        print("No V10 sources found; nothing to migrate.", file=sys.stderr)
        return 1

    # Non-interactive safety: refuse to overwrite existing V11 state unless --force.
    existing_v11 = [item for item in sources if item["dst"].exists()]
    if existing_v11 and not args.force:
        print(
            "Refusing to overwrite existing V11 state without --force:", file=sys.stderr
        )
        for item in existing_v11:
            print(f"  {item['dst']}", file=sys.stderr)
        return 1

    report: dict[str, Any] = {
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "v10_root": str(v10_root) if v10_root else None,
        "v10_runtime_root": str(v10_runtime) if v10_runtime else None,
        "v11_state_dir": str(state_dir),
        "items": [],
    }

    state_dir.mkdir(parents=True, exist_ok=True)
    print(f"Migrating V10 state to {state_dir} ...")

    for item in sources:
        record: dict[str, Any] = {
            "kind": item["kind"],
            "name": item["name"],
            "src": str(item["src"]),
            "dst": str(item["dst"]),
        }
        if item["kind"] == "database":
            backup = _backup_existing(item["dst"])
            if backup:
                print(f"  Backed up existing {item['dst'].name} -> {backup.name}")
                record["backup"] = str(backup)
            counts = _backup_sqlite(item["src"], item["dst"])
            record["src_counts"] = counts["src"]
            record["dst_counts"] = counts["dst"]
            total_src = sum(c for c in counts["src"].values() if c >= 0)
            total_dst = sum(c for c in counts["dst"].values() if c >= 0)
            print(
                f"  Copied database {item['name']} ({total_src} source rows, "
                f"{total_dst} destination rows)"
            )
        else:
            backup = _copy_json(item["src"], item["dst"])
            if backup:
                print(f"  Backed up existing {item['dst'].name} -> {backup.name}")
                record["backup"] = str(backup)
            print(f"  Copied JSON {item['name']}")
        report["items"].append(record)

    _write_report(state_dir, report)
    print(f"Migration report written to {_report_path(state_dir)}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Re-open V11 databases and verify counts match the migration report."""
    state_dir = _v11_state_dir()
    report = _load_report(state_dir)
    errors: list[str] = []

    for item in report.get("items", []):
        if item["kind"] != "database":
            continue
        dst = Path(item["dst"])
        if not dst.is_file():
            errors.append(f"Missing database: {dst}")
            continue
        expected = item.get("dst_counts", {})
        try:
            actual = _table_counts(sqlite3.connect(dst))
        except sqlite3.Error as exc:
            errors.append(f"Could not open {dst}: {exc}")
            continue
        for table, expected_count in expected.items():
            actual_count = actual.get(table)
            if actual_count != expected_count:
                errors.append(
                    f"{dst.name}.{table}: expected {expected_count}, got {actual_count}"
                )

    if errors:
        print("Verification FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Verification passed: V11 database counts match migration report.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicit V10 -> V11 migration utility for Local Lucy."
    )
    parser.add_argument(
        "--v10-root",
        help="Path to the V10 installation root (containing state/lucy_state.db).",
    )
    parser.add_argument(
        "--v10-runtime-root",
        help="Path to the V10 runtime directory (containing state/memory.db, etc.).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("dry-run", help="List sources and destinations without writing.")
    migrate_parser = subparsers.add_parser("migrate", help="Copy V10 state into V11 paths.")
    migrate_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing V11 state without prompting (required for non-interactive use).",
    )
    subparsers.add_parser("verify", help="Verify migrated counts match the report.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "dry-run":
            return cmd_dry_run(args)
        if args.command == "migrate":
            return cmd_migrate(args)
        if args.command == "verify":
            return cmd_verify(args)
    except AmbiguousSourceError as exc:
        print(f"Ambiguous source: {exc}", file=sys.stderr)
        return 2
    except MigrationError as exc:
        print(f"Migration error: {exc}", file=sys.stderr)
        return 1

    # Should never reach here because subparsers are required.
    parser.print_help(file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
