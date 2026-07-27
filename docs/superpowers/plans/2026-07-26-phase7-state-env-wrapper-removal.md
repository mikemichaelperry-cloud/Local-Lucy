# Phase 7 — StateManager Legacy `.env` Wrapper Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the dead-code legacy `.env` migration and backup helpers from `tools/router_py/state_manager.py` now that SQLite is the authoritative state store.

**Architecture:** Remove the unused `migrate_from_env()` and `write_env_backup()` methods and update the module docstring. No callers exist, so the change is a straightforward deletion with no replacement interface.

**Tech Stack:** Python 3, pytest, ruff, git

## Global Constraints

- Scope is strictly `tools/router_py/state_manager.py`; do not touch `runtime_request.py`, `main.py`, `execution_engine.py`, or shell tests.
- The active shell `.env` state contract (`last_route.env`, `last_outcome.env`) is out of scope.
- Verify no remaining references to `migrate_from_env` or `write_env_backup` after deletion.
- Full `tools/router_py/` pytest suite must pass with no regressions.
- `ruff check tools/router_py/state_manager.py` must pass.

---

### Task 1: Update the module docstring

**Files:**
- Modify: `tools/router_py/state_manager.py:1-18`

**Interfaces:**
- No interface change; only documentation.

- [ ] **Step 1: Remove the `.env` migration narrative from the docstring**

Edit `tools/router_py/state_manager.py`:

```python
"""
State Manager - SQLite-backed state management for Lucy V8 Router.

Replaces shell-based state management with a robust SQLite backend.
Supports namespaces, concurrent access via WAL mode, and provides
transaction safety with automatic rollback on errors.

Example:
    >>> sm = StateManager(namespace="production")
    >>> sm.write_route({"intent": "search", "confidence": 0.95})
    >>> last_route = sm.read_last_route()
"""
```

- [ ] **Step 2: Commit the docstring change**

```bash
git add tools/router_py/state_manager.py
git commit -m "docs(state_manager): remove legacy .env migration narrative"
```

---

### Task 2: Delete `migrate_from_env()`

**Files:**
- Modify: `tools/router_py/state_manager.py:920-987`

**Interfaces:**
- Removes `StateManager.migrate_from_env(env_path: Optional[Path] = None) -> bool`.
- No replacement; no callers exist.

- [ ] **Step 1: Remove the legacy migration method and its section header**

Edit `tools/router_py/state_manager.py` to delete from the section header through the end of the method:

Old content:

```python
    # ---------------------------------------------------------------------
    # Migration from Legacy (.env files)
    # ---------------------------------------------------------------------

    def migrate_from_env(self, env_path: Optional[Path] = None) -> bool:
        """
        Migrate state from legacy .env files to SQLite.

        Reads existing .env files and imports their data.
        Safe to run multiple times (idempotent).

        Args:
            env_path: Path to .env file (default: router_root/.env)

        Returns:
            bool: True if migration succeeded or nothing to migrate
        """
        try:
            router_root = Path(__file__).parent.parent.parent

            # Check for legacy env files
            legacy_files = ["last_route.env", "last_outcome.env"]
            migrated = False

            for filename in legacy_files:
                file_path = router_root / filename
                if file_path.exists():
                    logger.info(f"Migrating legacy file: {filename}")

                    with open(file_path, "r") as f:
                        data = {}
                        for line in f:
                            line = line.strip()
                            if line and "=" in line and not line.startswith("#"):
                                key, value = line.split("=", 1)
                                data[key] = value

                    if filename == "last_route.env" and data:
                        self.write_route(
                            {
                                "intent": data.get("LAST_ROUTE_INTENT", "unknown"),
                                "confidence": float(data.get("LAST_ROUTE_CONFIDENCE", 0.0)),
                                "strategy": data.get("LAST_ROUTE_STRATEGY"),
                                "metadata": data,
                            }
                        )
                        migrated = True

                    elif filename == "last_outcome.env" and data:
                        self.write_outcome(
                            {
                                "success": data.get("LAST_OUTCOME_SUCCESS", "false").lower()
                                == "true",
                                "duration_ms": int(data.get("LAST_OUTCOME_DURATION_MS", 0)),
                                "result": data,
                            }
                        )
                        migrated = True

            if migrated:
                logger.info("Migration from .env files completed successfully")
            else:
                logger.debug("No legacy .env files found to migrate")

            return True
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return False
```

New content: empty (delete the entire block).

- [ ] **Step 2: Commit the deletion**

```bash
git add tools/router_py/state_manager.py
git commit -m "refactor(state_manager): remove migrate_from_env legacy wrapper"
```

---

### Task 3: Delete `write_env_backup()`

**Files:**
- Modify: `tools/router_py/state_manager.py:989-1029`

**Interfaces:**
- Removes `StateManager.write_env_backup(key: str, value: str) -> bool`.
- No replacement; no callers exist.

- [ ] **Step 1: Remove the legacy backup method**

Edit `tools/router_py/state_manager.py` to delete the entire method:

Old content:

```python
    def write_env_backup(self, key: str, value: str) -> bool:
        """
        Write to legacy .env file during transition period.

        Maintains backward compatibility while migrating.

        Args:
            key: Environment variable name
            value: Value to write

        Returns:
            bool: True if write succeeded
        """
        try:
            router_root = Path(__file__).parent.parent.parent
            env_file = router_root / "state_backup.env"

            # Read existing content
            lines = []
            if env_file.exists():
                with open(env_file, "r") as f:
                    lines = f.readlines()

            # Update or append key
            key_found = False
            for i, line in enumerate(lines):
                if line.startswith(f"{key}="):
                    lines[i] = f"{key}={value}\n"
                    key_found = True
                    break

            if not key_found:
                lines.append(f"{key}={value}\n")

            with open(env_file, "w") as f:
                f.writelines(lines)

            return True
        except Exception as e:
            logger.error(f"Failed to write .env backup: {e}")
            return False
```

New content: empty (delete the entire method).

- [ ] **Step 2: Commit the deletion**

```bash
git add tools/router_py/state_manager.py
git commit -m "refactor(state_manager): remove write_env_backup legacy wrapper"
```

---

### Task 4: Verify no remaining references

**Files:**
- None

**Interfaces:**
- Confirm `migrate_from_env` and `write_env_backup` no longer appear in code or tests.

- [ ] **Step 1: Search the repository**

```bash
cd /home/mike/lucy-v11
grep -R "migrate_from_env\|write_env_backup" --include="*.py" --include="*.sh" tools/ ui-v10/ models/ || true
```

Expected: only matches in `docs/superpowers/specs/` and `docs/superpowers/plans/` (this plan and the design spec).

- [ ] **Step 2: Commit the verification log (optional)**

No commit required; just confirm in the task notes.

---

### Task 5: Run tests and lint

**Files:**
- None

**Interfaces:**
- Confirm no regressions from the deletions.

- [ ] **Step 1: Run ruff on the modified file**

```bash
cd /home/mike/lucy-v11
python3 -m ruff check tools/router_py/state_manager.py
```

Expected: `All checks passed!`

- [ ] **Step 2: Run the router_py test suite**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/ -q --tb=line
```

Expected: `931 passed, 12 skipped, 178 subtests passed` (or the current baseline; no failures).

- [ ] **Step 3: Note the final counts**

Record the exact pytest summary in the Phase 7 report.

---

### Task 6: Write the Phase 7 completion report

**Files:**
- Create: `lucy-v11-prep/reports/phase7_state_env_wrapper_removal_2026-07-26.md`

**Interfaces:**
- No code interface; report documents the change.

- [ ] **Step 1: Write the report**

The report should include:

- Date, branch, V10 preservation statement.
- Objective: remove StateManager legacy `.env` wrappers.
- Files changed: `tools/router_py/state_manager.py`.
- Methods removed: `migrate_from_env()`, `write_env_backup()`.
- Verification: grep results, ruff result, pytest summary.
- Gate assessment table.
- Next steps (Phase 8 or other pending work).

- [ ] **Step 2: Commit the report**

```bash
git add lucy-v11-prep/reports/phase7_state_env_wrapper_removal_2026-07-26.md
git commit -m "docs: Phase 7 report for StateManager legacy .env wrapper removal"
```

---

## Self-review checklist

- [ ] Spec coverage: docstring update, `migrate_from_env` deletion, `write_env_backup` deletion, verification, tests, lint, report.
- [ ] Placeholder scan: no TBD/TODO/"fill in details".
- [ ] Type consistency: only deletions; no new types.
- [ ] Scope: no mention of modifying `runtime_request.py`, `main.py`, `execution_engine.py`, or shell tests.
