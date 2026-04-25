#!/usr/bin/env python3
"""Minimal local pre-processor for Codex tasks.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import textwrap
from typing import Iterable, Sequence

IGNORE_CASE = re.compile("[A-Za-z0-9_]+", re.ASCII)

@dataclasses.dataclass
class BootstrapState:
    active_root: str
    current_task: str
    open_gaps: str
    first_steps: Sequence[str]
    baseline_status: str
    handoff_path: str

POLITE_PREFIXES = [
    r"(please\s+)?(can you|could you|would you|kindly|i need you to|i'd like you to|can we|could we)(\s+)?",
    r"(please\s+)?(fix|update|solve|investigate|look into|address)(\s+)?",
]
DEFAULT_CONSTRAINTS = [
    "Do not modify router",
    "Preserve test coverage",
]
EXCLUDED_PATHS_DEFAULT = ["tests/", "snapshots/stable/"]
TOP_LEVEL_LAUNCHER = pathlib.Path("/home/mike/codex_launcher_gui.sh")
PRIMARY_LIMIT = 3
SECONDARY_LIMIT = 4
SECONDARY_TEST_HINT_LIMIT = 2
VALIDATION_LIMIT = 10
PRIORITY_TOKENS = {
    "diff",
    "gate",
    "patch",
    "plan",
    "prompt",
    "scope",
    "sanity",
    "surface",
    "launch",
    "launcher",
    "preprocess",
    "validation",
}
STOPWORDS = {
    "about",
    "active",
    "add",
    "before",
    "broad",
    "chain",
    "cheap",
    "cleaned",
    "codex",
    "current",
    "determine",
    "edit",
    "existing",
    "extend",
    "file",
    "files",
    "goal",
    "have",
    "issue",
    "keep",
    "layer",
    "local",
    "lucy",
    "mode",
    "need",
    "only",
    "output",
    "relevant",
    "required",
    "router",
    "safe",
    "system",
    "task",
    "test",
    "tests",
    "touched",
    "under",
    "update",
    "use",
    "when",
}


def find_latest_handoff(root: pathlib.Path) -> pathlib.Path:
    dev_notes = root / "dev_notes"
    if not dev_notes.is_dir():
        raise FileNotFoundError(f"missing dev_notes under {root}")
    files = sorted(dev_notes.glob("SESSION_HANDOFF_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError("no session handoff notes found")
    return files[0]


def parse_quick_resume(lines: Sequence[str]) -> dict[str, str | list[str]]:
    info: dict[str, str | list[str]] = {}
    start = None
    for idx, line in enumerate(lines):
        if line.startswith("## Quick Resume"):
            start = idx + 1
            break
    if start is None:
        return info
    first_steps: list[str] = []
    capture_first_steps = False
    for line in lines[start:]:
        if line.startswith("## ") and not line.startswith("## Quick Resume"):
            break
        focus_match = re.match(r"- \*\*Current task focus\*\*: (.*)", line)
        if focus_match:
            info["current_task"] = focus_match.group(1).strip()
        if "**First commands to run**" in line:
            capture_first_steps = True
            continue
        if capture_first_steps:
            step_match = re.match(r"\s*\d+\. (.*)", line)
            if step_match:
                first_steps.append(step_match.group(1).strip())
            elif line.strip() == "":
                continue
            else:
                capture_first_steps = False
        if "**Open gaps**" in line or "**Open gaps**" in line:
            pass
    if first_steps:
        info["first_steps"] = first_steps
    return info


def parse_final_verification(lines: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    start = None
    for idx, line in enumerate(lines):
        if line.startswith("## Final Verification"):
            start = idx + 1
            break
    if start is None:
        return result
    for line in lines[start:]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        result[key.strip()] = val.strip()
    return result


def build_bootstrap_state(lines: Sequence[str], root: pathlib.Path) -> BootstrapState:
    quick = parse_quick_resume(lines)
    final = parse_final_verification(lines)
    active_root = final.get("ACTIVE_ROOT", str(root))
    current_task = quick.get("current_task") or final.get("CURRENT_TASK") or "[task not documented]"
    open_gaps = final.get("OPEN_GAPS", "")
    first_steps = quick.get("first_steps") or []
    baseline_status = final.get("BASELINE_STATUS", "UNKNOWN")
    handoff_path = final.get("HANDOFF_PATH", "")
    return BootstrapState(
        active_root=active_root,
        current_task=current_task,
        open_gaps=open_gaps,
        first_steps=tuple(first_steps),
        baseline_status=baseline_status,
        handoff_path=handoff_path,
    )


def classify_task(task: str, files: Sequence[str]) -> str:
    lower_task = task.lower()
    codex_keywords = [
        "manifest",
        "governor",
        "router",
        "policy",
        "route",
        "execute_plan",
        "shared state",
        "concurrency",
        "architecture",
        "multi-file",
    ]
    local_only_keywords = [
        "README",
        "typo",
        "format",
        "grep",
        "search",
        "list",
        "print",
        "debug",
        "syntax",
        "hygiene",
        "baseline status",
    ]
    for kw in codex_keywords:
        if kw in lower_task:
            return "codex_needed"
    for kw in local_only_keywords:
        if kw.lower() in lower_task:
            return "local_only"
    if len(files) > 3:
        return "codex_needed"
    return "local_patch"


def recommend_model(decision: str, task: str) -> tuple[str, str]:
    if decision == "codex_needed":
        if any(k in task.lower() for k in ("architecture", "policy", "governor")):
            return "gpt-5.2", "medium"
        return "gpt-5.1-codex-mini", "low"
    return "local-lucy", "low"


def clean_task(task: str) -> str:
    cleaned = task.strip()
    for prefix in POLITE_PREFIXES:
        cleaned = re.sub(fr"^{prefix}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip(" ?!.")
    if not cleaned:
        return "Describe the intended change in precise engineering terms."
    return cleaned[0].upper() + cleaned[1:]


def dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def normalize_output_path(path: pathlib.Path | str, root: pathlib.Path) -> str:
    text = str(path)
    if not text:
        return ""
    candidate = pathlib.Path(text)
    if candidate.is_absolute():
        try:
            return str(candidate.relative_to(root))
        except ValueError:
            return str(candidate)
    return str(pathlib.PurePosixPath(text))


def resolve_candidate_path(entry: str, root: pathlib.Path) -> pathlib.Path:
    token = entry.strip()
    if not token:
        return root
    if token == "codex_launcher_gui.sh":
        return TOP_LEVEL_LAUNCHER
    candidate = pathlib.Path(token)
    if candidate.is_absolute():
        return candidate
    return (root / candidate).resolve()


def extract_explicit_paths(task: str, files: Sequence[str], root: pathlib.Path) -> list[str]:
    explicit = list(files)
    for match in re.findall(r"\b[\w./-]+\.\w+\b", task):
        explicit.append(match)
    if "codex_launcher_gui.sh" in task and "codex_launcher_gui.sh" not in explicit:
        explicit.append("codex_launcher_gui.sh")
    return dedupe_keep_order(normalize_output_path(resolve_candidate_path(item, root), root) for item in explicit)


def collect_patch_hint_files(task: str, root: pathlib.Path) -> list[str]:
    lower_task = task.lower()
    hints: list[str] = []
    if any(token in lower_task for token in ("codex", "preprocess", "patch surface", "validation plan", "sanity", "scope")):
        hints.extend(
            [
                "tools/codex_gate.py",
                "tools/codex_gate.sh",
                "codex_launcher_gui.sh",
            ]
        )
    if any(token in lower_task for token in ("launcher", "prompt", "launch")):
        hints.extend(
            [
                "codex_launcher_gui.sh",
                "tools/start_local_lucy_opt_experimental_v7_dev.sh",
                "tools/start_local_lucy_opt_experimental_v3_dev.sh",
            ]
        )
    if "launcher chain" in lower_task or "local lucy" in lower_task:
        hints.extend(
            [
                "tools/start_local_lucy_opt_experimental_v7_dev.sh",
                "tools/start_local_lucy_opt_experimental_v3_dev.sh",
            ]
        )
    if any(token in lower_task for token in ("test", "validation")):
        hints.append("tools/tests/test_codex_prompt_integrity.sh")
    return dedupe_keep_order(normalize_output_path(resolve_candidate_path(item, root), root) for item in hints)


def keyword_tokens(text: str) -> list[str]:
    words = []
    for token in IGNORE_CASE.findall(text.lower()):
        if token in STOPWORDS:
            continue
        if len(token) < 5 and token not in PRIORITY_TOKENS:
            continue
        words.append(token)
    deduped = dedupe_keep_order(words)
    ordered = [token for token in deduped if token in PRIORITY_TOKENS]
    ordered.extend(token for token in deduped if token not in PRIORITY_TOKENS)
    return ordered[:5]


def is_launcher_ui_candidate(candidate: str) -> bool:
    lowered = candidate.lower()
    name = pathlib.PurePosixPath(lowered).name
    return (
        name == "codex_launcher_gui.sh"
        or "launcher" in name
        or name.endswith(".desktop")
        or "start_local_lucy_opt_experimental" in lowered
    )


def is_gate_script_candidate(candidate: str) -> bool:
    pure = pathlib.PurePosixPath(candidate.lower())
    return pure.suffix in {".py", ".sh"} and "gate" in pure.name


def candidate_role_rank(candidate: str) -> int:
    if is_gate_script_candidate(candidate):
        return 1
    if candidate.startswith("tools/tests/"):
        return 2
    if is_launcher_ui_candidate(candidate):
        return 3
    return 0


def has_function_class_relevance(candidate: str, task: str, root: pathlib.Path) -> bool:
    resolved = resolve_candidate_path(candidate, root)
    if not resolved.is_file():
        return False
    tokens = keyword_tokens(task)
    if not tokens:
        return False
    try:
        content = resolved.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    signature_lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("def ")
            or stripped.startswith("class ")
            or re.match(r"[A-Za-z_][A-Za-z0-9_]*\(\)\s*\{", stripped)
            or stripped.startswith("export ")
        ):
            signature_lines.append(stripped)
    haystack = " ".join(signature_lines).lower()
    if not haystack:
        haystack = f"{resolved.name.lower()} {resolved.stem.lower()}"
    return any(token in haystack for token in tokens)


def targeted_grep_hits(root: pathlib.Path, task: str, candidates: Sequence[str]) -> list[str]:
    if not candidates:
        return []
    if not shutil.which("rg"):
        return []
    search_terms = keyword_tokens(task)
    if not search_terms:
        return []
    search_paths = []
    for item in candidates:
        resolved = resolve_candidate_path(item, root)
        if resolved.exists():
            search_paths.append(str(resolved))
    if not search_paths:
        return []
    hits: list[str] = []
    for token in search_terms:
        try:
            proc = subprocess.run(
                ["rg", "-l", "-m", "1", "-S", token, *search_paths],
                check=False,
                capture_output=True,
                text=True,
                timeout=0.35,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode not in (0, 1):
            continue
        for line in proc.stdout.splitlines():
            normalized = normalize_output_path(pathlib.Path(line.strip()), root)
            if normalized:
                hits.append(normalized)
    return dedupe_keep_order(hits)


def nearby_tests_for_files(files: Sequence[str]) -> list[str]:
    tests: list[str] = []
    joined = " ".join(files)
    if any(item.endswith("tools/codex_gate.py") or item.endswith("tools/codex_gate.sh") for item in files):
        tests.extend(
            [
                "tools/tests/test_codex_gate.sh",
                "tools/tests/test_codex_scope_reduction.sh",
                "tools/tests/test_codex_sanity_filter.sh",
                "tools/tests/test_codex_patch_surface.sh",
                "tools/tests/test_codex_validation_plan.sh",
                "tools/tests/test_codex_patch_surface_fallback.sh",
            ]
        )
    if "codex_launcher_gui.sh" in joined:
        tests.extend(
            [
                "tools/tests/test_codex_prompt_integrity.sh",
                "tools/tests/test_codex_scope_prompt.sh",
                "tools/tests/test_codex_launcher_gui_preprocess.sh",
                "tools/tests/test_launcher_preprocess_autorun.sh",
                "tools/tests/test_launcher_preprocess_escalation.sh",
            ]
        )
    if any("start_local_lucy_opt_experimental" in item for item in files):
        tests.extend(
            [
                "tools/tests/test_codex_preprocess_launcher.sh",
                "tools/tests/test_launcher_preprocess_task_alias.sh",
            ]
        )
    return dedupe_keep_order(tests)


def score_patch_candidates(
    task: str,
    explicit_paths: Sequence[str],
    hint_paths: Sequence[str],
    grep_hits: Sequence[str],
    root: pathlib.Path,
) -> list[dict[str, object]]:
    candidates = dedupe_keep_order([*explicit_paths, *hint_paths, *grep_hits])
    scored: list[dict[str, object]] = []
    grep_hit_set = set(grep_hits)
    explicit_set = set(explicit_paths)
    for candidate in candidates:
        nearby_tests = nearby_tests_for_files([candidate])
        score = 0
        reasons: list[str] = []
        if candidate in explicit_set:
            score += 3
            reasons.append("+3 explicit task mention")
        if has_function_class_relevance(candidate, task, root):
            score += 2
            reasons.append("+2 function/class relevance")
        if candidate in grep_hit_set:
            score += 2
            reasons.append("+2 grep-hit relevance")
        if nearby_tests:
            score += 1
            reasons.append("+1 nearby test linkage")
        if is_launcher_ui_candidate(candidate) and candidate not in explicit_set:
            score -= 2
            reasons.append("-2 launcher/UI file unless explicitly targeted")
        scored.append(
            {
                "path": candidate,
                "score": score,
                "reasons": tuple(reasons),
                "nearby_tests": tuple(nearby_tests),
                "role_rank": candidate_role_rank(candidate),
            }
        )
    scored.sort(
        key=lambda item: (
            -(max(int(item["score"]), 0) // 2),
            int(item["role_rank"]),
            -int(item["score"]),
            str(item["path"]),
        )
    )
    return scored


def infer_patch_surface(
    task: str,
    cleaned_task: str,
    files: Sequence[str],
    state: BootstrapState,
    root: pathlib.Path,
) -> dict[str, object]:
    explicit_paths = extract_explicit_paths(task, files, root)
    hint_paths = collect_patch_hint_files(cleaned_task, root)
    grep_hits = targeted_grep_hits(root, cleaned_task, explicit_paths + hint_paths)
    scored_candidates = score_patch_candidates(cleaned_task, explicit_paths, hint_paths, grep_hits, root)

    ranked_files = [
        item for item in scored_candidates if int(item["score"]) > 0 and not str(item["path"]).startswith("tools/tests/")
    ]
    explicit_set = set(explicit_paths)
    primary_candidates = [
        item for item in ranked_files if int(item["role_rank"]) <= 1 or str(item["path"]) in explicit_set
    ]
    primary_files = [str(item["path"]) for item in primary_candidates[:PRIMARY_LIMIT]]

    non_launcher_leftovers = [
        str(item["path"])
        for item in ranked_files
        if str(item["path"]) not in primary_files and not is_launcher_ui_candidate(str(item["path"]))
    ]
    launcher_leftovers = [
        str(item["path"])
        for item in ranked_files
        if str(item["path"]) not in primary_files and is_launcher_ui_candidate(str(item["path"]))
    ]
    nearby_tests = dedupe_keep_order(
        test
        for item in ranked_files[: PRIMARY_LIMIT + 1]
        for test in item["nearby_tests"]
    )
    secondary_pool = list(non_launcher_leftovers)
    secondary_pool.extend(nearby_tests[:SECONDARY_TEST_HINT_LIMIT])
    secondary_pool.extend(launcher_leftovers)
    secondary_pool.extend(nearby_tests[SECONDARY_TEST_HINT_LIMIT:])
    secondary_files = dedupe_keep_order(secondary_pool)[:SECONDARY_LIMIT]

    lower_task = cleaned_task.lower()
    # V8 ISOLATION: Only avoid files within v8 namespace
    avoid_files = [
        # No old version references - v8 is self-contained
    ]
    if "router" not in lower_task:
        avoid_files.append("tools/router/")
    if "governor" not in lower_task:
        avoid_files.append("tools/governor/")

    reasoning_parts: list[str] = []
    if ranked_files:
        summaries = []
        for item in ranked_files[:PRIMARY_LIMIT]:
            summaries.append(f"{item['path']}={item['score']} ({'; '.join(item['reasons'])})")
        reasoning_parts.append(f"ranked ownership candidates: {' | '.join(summaries)}")
    if hint_paths:
        reasoning_parts.append(f"candidate seeds: {', '.join(hint_paths[:3])}")
    nearby_tests = [item for item in secondary_files if item.startswith("tools/tests/")]
    if nearby_tests:
        reasoning_parts.append(f"nearby tests: {', '.join(nearby_tests[:3])}")
    if not reasoning_parts:
        reasoning_parts.append("No safe patch surface inferred from explicit targets, cheap symbol relevance, grep hits, or nearby tests.")

    return {
        "primary_files": primary_files,
        "secondary_files": secondary_files,
        "avoid_files": dedupe_keep_order(avoid_files),
        "reasoning_basis": " | ".join(reasoning_parts),
    }


def infer_validation_plan(patch_surface: dict[str, object]) -> list[str]:
    files = [
        *patch_surface.get("primary_files", []),
        *patch_surface.get("secondary_files", []),
    ]
    commands: list[str] = []
    if any(item.startswith("tools/router/") or "route_manifest" in item or "execute_plan" in item for item in files):
        commands.append("bash tools/router_regression.sh")
    if any(item.endswith("tools/codex_gate.py") or item.endswith("tools/codex_gate.sh") for item in files):
        commands.extend(
            [
                "bash tools/tests/test_codex_gate.sh",
                "bash tools/tests/test_codex_scope_reduction.sh",
                "bash tools/tests/test_codex_sanity_filter.sh",
                "bash tools/tests/test_codex_patch_surface.sh",
                "bash tools/tests/test_codex_validation_plan.sh",
                "bash tools/tests/test_codex_patch_surface_fallback.sh",
            ]
        )
    if any("codex_launcher_gui.sh" in item for item in files):
        commands.extend(
            [
                "bash tools/tests/test_codex_prompt_integrity.sh",
                "bash tools/tests/test_codex_scope_prompt.sh",
                "bash tools/tests/test_codex_launcher_gui_preprocess.sh",
                "bash tools/tests/test_launcher_preprocess_autorun.sh",
                "bash tools/tests/test_launcher_preprocess_escalation.sh",
            ]
        )
    if any("start_local_lucy_opt_experimental" in item for item in files):
        commands.extend(
            [
                "bash tools/tests/test_launcher_preprocess_task_alias.sh",
                "bash tools/tests/test_codex_preprocess_launcher.sh",
            ]
        )
    return dedupe_keep_order(commands)[:VALIDATION_LIMIT]


def reduce_scope_structured(
    task: str,
    files: Sequence[str],
    state: BootstrapState,
    patch_surface: dict[str, object] | None = None,
) -> dict[str, Sequence[str]]:
    target_files: list[str] = [item for item in files if item]
    matches = re.findall(r"\b[\w./-]+\.\w+\b", task)
    for match in matches:
        if match not in target_files:
            target_files.append(match)
    primary_files = list((patch_surface or {}).get("primary_files", []))
    secondary_files = list((patch_surface or {}).get("secondary_files", []))
    if not target_files and primary_files:
        target_files.extend(item for item in primary_files if not item.startswith("tools/tests/"))
    if not target_files:
        target_files = [state.active_root]

    allowed_paths: list[str] = []

    def add_scope_path(entry: str) -> None:
        normalized = entry.strip()
        if not normalized:
            return
        allowed_paths.append(normalized)
        if normalized.startswith("/"):
            return
        if "/" in normalized:
            allowed_paths.append(normalized.rsplit("/", 1)[0])

    for entry in target_files:
        add_scope_path(entry)
    for entry in primary_files:
        add_scope_path(entry)
    for entry in secondary_files:
        if entry.startswith("tools/tests/") or not is_launcher_ui_candidate(entry):
            add_scope_path(entry)

    allowed_paths = dedupe_keep_order(allowed_paths)
    if not allowed_paths:
        allowed_paths = [state.active_root]
    excluded_paths = EXCLUDED_PATHS_DEFAULT.copy()
    return {
        "target_files": dedupe_keep_order(target_files),
        "allowed_paths": allowed_paths,
        "excluded_paths": excluded_paths,
    }


def analyze_sanity_flags(cleaned_task: str, target_files: Sequence[str], patch_surface: dict[str, object] | None = None) -> dict[str, object]:
    task_lower = cleaned_task.lower()
    primary_files = list((patch_surface or {}).get("primary_files", []))
    contradiction = bool(
        re.search(r"\b(and|but)\b.*\bnot\b", task_lower)
        or re.search(r"\bnot\b.*\b(and|but)\b", task_lower)
    )
    underspecified = len(primary_files) == 0 or (len(cleaned_task.split()) < 5 and len(target_files) == 0)
    dangerous = bool(
        re.search(r"(rm\s+-rf|sudo\s+rm|dd\s+if=|format\s+disk|shutdown|reboot|mkfs|poweroff)", task_lower)
    )
    notes = []
    if contradiction:
        notes.append("Conflicting instructions detected.")
    if underspecified:
        notes.append("Need more detail or explicit target files.")
    if dangerous:
        notes.append("Risky command mentioned.")
    return {
        "contradiction": contradiction,
        "underspecified": underspecified,
        "dangerous": dangerous,
        "notes": " ".join(notes) if notes else "None",
    }


def build_prompt(
    state: BootstrapState,
    classification: str,
    cleaned_task: str,
    scope: dict[str, Sequence[str]],
    patch_surface: dict[str, object],
    validation_plan: Sequence[str],
    constraints: Sequence[str],
    sanity_flags: dict[str, object],
    validation: Sequence[str],
    source_text: str,
    escalation_reason: str | None = None,
) -> str:
    lines: list[str] = [
        "SYSTEM CONTEXT:",
        "You are operating under strict scoped execution.",
        "",
        "TASK:",
        cleaned_task,
        "",
        "SCOPE:",
        f"- Allowed files: {', '.join(scope['target_files'])}",
        f"- Allowed paths: {', '.join(scope['allowed_paths'])}",
        f"- Excluded paths: {', '.join(scope['excluded_paths'])}",
        "",
        "PATCH SURFACE:",
        f"- Primary files: {', '.join(patch_surface.get('primary_files', [])) or 'None'}",
        f"- Secondary files: {', '.join(patch_surface.get('secondary_files', [])) or 'None'}",
        f"- Avoid files: {', '.join(patch_surface.get('avoid_files', [])) or 'None'}",
        f"- Reasoning basis: {patch_surface.get('reasoning_basis', 'None')}",
        "",
        "VALIDATION PLAN:",
    ]
    if validation_plan:
        lines.extend(f"- {step}" for step in validation_plan)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
        "CONSTRAINTS:",
        ]
    )
    if constraints:
        lines.extend(f"- {constraint}" for constraint in constraints)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "SANITY CHECK:",
        ]
    )
    for key in ("contradiction", "underspecified", "dangerous", "notes"):
        lines.append(f"- {key}: {sanity_flags.get(key)}")
    lines.extend(
        [
            "",
            "RULES:",
            "- Do not touch files outside scope",
            "- Do not expand task scope",
            "- Prefer minimal changes",
            "",
            "SOURCE ANALYSIS:",
        ]
    )
    if escalation_reason:
        lines.append(f"Escalation reason: {escalation_reason}")
    lines.append(f"Gate decision: {classification}")
    lines.append("")
    if source_text:
        lines.append(source_text)
    if validation:
        lines.append("")
        lines.append("VALIDATION STEPS:")
        lines.extend(f"- {step}" for step in validation)
    if state.open_gaps:
        lines.append("")
        lines.append(f"OPEN GAPS: {state.open_gaps}")
    prompt = "\n".join(lines)
    if len(prompt) > 4000:
        prompt = prompt[:4000] + "\n[truncated]"
    return prompt


def prompt_dest(root: pathlib.Path, path_hint: str | None) -> pathlib.Path:
    if path_hint:
        return pathlib.Path(path_hint)
    target_dir = root / "tmp" / "codex_gate"
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return target_dir / f"compact_prompt_{timestamp}.txt"


def print_kvs(entries: Iterable[tuple[str, str]]) -> None:
    for key, val in entries:
        print(f"{key}={val}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local pre-processing gate for Codex workflows")
    parser.add_argument("--task", required=True, help="User-described task for Codex")
    parser.add_argument("--files", nargs="*", default=[], help="Optional files or paths mentioned in the request")
    parser.add_argument("--prompt-path", help="Explicit path where the compact prompt should be written")
    parser.add_argument("--root", help="Override the Lucy root path")
    args = parser.parse_args()

    root = pathlib.Path(args.root or os.environ.get("LUCY_ROOT", ".")).resolve()
    handoff_path = find_latest_handoff(root)
    lines = handoff_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    state = build_bootstrap_state(lines, root)
    classification = classify_task(args.task, args.files)
    model, effort = recommend_model(classification, args.task)
    cleaned = clean_task(args.task)
    patch_surface = infer_patch_surface(args.task, cleaned, args.files, state, root)
    scope_struct = reduce_scope_structured(args.task, args.files, state, patch_surface)
    validation_plan = infer_validation_plan(patch_surface)
    sanity_flags = analyze_sanity_flags(cleaned, scope_struct["target_files"], patch_surface)
    constraint_notes = DEFAULT_CONSTRAINTS
    source_lines = [
        f"Active root: {state.active_root}",
        f"Task: {args.task.strip()}",
    ]
    if args.files:
        source_lines.append(f"Likely files: {', '.join(args.files)}")
    source_text = "\n".join(source_lines)
    prompt_text = build_prompt(
        state=state,
        classification=classification,
        cleaned_task=cleaned,
        scope=scope_struct,
        patch_surface=patch_surface,
        validation_plan=validation_plan,
        constraints=constraint_notes,
        sanity_flags=sanity_flags,
        validation=state.first_steps,
        source_text=source_text,
    )
    prompt_file = prompt_dest(root, args.prompt_path)
    prompt_file.write_text(prompt_text, encoding="utf-8")
    entries = [
        ("DECISION", classification),
        ("CLEANED_TASK", cleaned),
        ("TARGET_FILES", json.dumps(scope_struct["target_files"])),
        ("ALLOWED_PATHS", json.dumps(scope_struct["allowed_paths"])),
        ("EXCLUDED_PATHS", json.dumps(scope_struct["excluded_paths"])),
        ("PATCH_SURFACE", json.dumps(patch_surface)),
        ("VALIDATION_PLAN", json.dumps(validation_plan)),
        ("CONSTRAINTS", json.dumps(constraint_notes)),
        ("SANITY_FLAGS", json.dumps(sanity_flags)),
        ("MODEL_HINT", model),
        ("EFFORT_HINT", effort),
        ("ACTIVE_ROOT", state.active_root),
        ("CURRENT_TASK", state.current_task),
        ("OPEN_GAPS", state.open_gaps),
        ("FIRST_STEPS", " | ".join(state.first_steps) if state.first_steps else ""),
        ("BASELINE_STATUS", state.baseline_status),
        ("HANDOFF_PATH", state.handoff_path or str(handoff_path)),
        ("FILES_HINT", ", ".join(args.files) if args.files else ""),
        ("COMPACT_PROMPT", prompt_text.replace("\n", " / ")),
        ("PROMPT_PATH", str(prompt_file)),
    ]
    if classification == "codex_needed":
        entries.append(("PROMPT_SUMMARY", textwrap.shorten(prompt_text, width=200, placeholder="...")))
    print_kvs(entries)


if __name__ == "__main__":
    main()
