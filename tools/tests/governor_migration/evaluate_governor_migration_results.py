#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


FAILURE_CATEGORIES = {
    "route_drift",
    "clarify_failure",
    "evidence_requirement_drift",
    "followup_context_failure",
    "mode_handling_failure",
    "policy_leakage_execution",
    "wording_drift_sensitive_domain",
    "fast_path_contract_bypass",
    "unexpected_fallback",
    "logging_or_contract_capture_failure",
}

ROOT_CAUSE_NOTES = {
    "route_drift": "Route selection or route-to-execution handoff drifted from the expected governor contract.",
    "clarify_failure": "Clarification requirement was missing, misplaced, or bypassed.",
    "evidence_requirement_drift": "Evidence/source requirement flags diverged from the expected contract.",
    "followup_context_failure": "Conversation continuity or contextual follow-up resolution did not preserve the intended subject.",
    "mode_handling_failure": "AUTO/ONLINE/OFFLINE behavior diverged across modes for the same semantic prompt.",
    "policy_leakage_execution": "Execution behavior suggests policy semantics are still being invented below the governor boundary.",
    "wording_drift_sensitive_domain": "Sensitive-domain wording drifted into a disallowed phrasing or presentation style.",
    "fast_path_contract_bypass": "Fast-path execution appears to have bypassed or altered the normalized execution contract.",
    "unexpected_fallback": "A fallback path handled the case, but not the expected one for the requested family.",
    "logging_or_contract_capture_failure": "Required structured traces or outcome metadata were missing or malformed.",
}

OUTCOME_FAMILY_MATCHERS = {
    "local_success": lambda route, code, response: route == "LOCAL" and code in {"answered", "knowledge_short_circuit_hit"},
    "local_guarded_medical": lambda route, code, response: route == "LOCAL" and code in {"answered", "knowledge_short_circuit_hit", "local_guard_fallback"},
    "local_guarded_safety": lambda route, code, response: route == "LOCAL" and code in {"answered", "knowledge_short_circuit_hit", "local_guard_fallback"},
    "clarify_needed": lambda route, code, response: route == "CLARIFY" and code == "clarification_requested",
    "news_success": lambda route, code, response: route == "NEWS" and code == "answered",
    "evidence_success": lambda route, code, response: route == "EVIDENCE" and code == "answered",
    "evidence_unavailable_offline": lambda route, code, response: route == "EVIDENCE" and code in {"requires_evidence_mode", "validated_insufficient"},
    "news_unavailable_offline": lambda route, code, response: route == "NEWS" and code in {"requires_evidence_mode", "validated_insufficient"},
}

MODE_MAP = {
    "AUTO": "AUTO",
    "ONLINE": "FORCED_ONLINE",
    "OFFLINE": "FORCED_OFFLINE",
}

SENSITIVE_WORDING_CATEGORIES = {"medical_offline", "medical_auto", "safety_offline"}


@dataclass
class SessionContext:
    key: str
    workspace_root: Path
    memory_file: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--category")
    parser.add_argument("--case")
    return parser.parse_args()


def require_yaml() -> Any:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit("ERROR: PyYAML is required for governor migration evaluation") from exc
    return yaml


def load_yaml(path: Path) -> Dict[str, Any]:
    yaml = require_yaml()
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR: suite file is not a mapping: {path}")
    return data


def sanitize_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)


def ensure_workspace(real_root: Path, workspaces_dir: Path, key: str) -> SessionContext:
    workspace_root = workspaces_dir / sanitize_name(key)
    workspace_root.mkdir(parents=True, exist_ok=True)
    for child in ("state", "tmp", "cache", "evidence"):
        (workspace_root / child).mkdir(exist_ok=True)
    links = {
        "tools": real_root / "tools",
        "config": real_root / "config",
        "lucy_chat.sh": real_root / "lucy_chat.sh",
    }
    for name, target in links.items():
        link_path = workspace_root / name
        if link_path.exists() or link_path.is_symlink():
            continue
        link_path.symlink_to(target)
    memory_file = workspace_root / "tmp" / "run" / "session_memory.txt"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    if not memory_file.exists():
        memory_file.write_text("", encoding="utf-8")
    return SessionContext(key=key, workspace_root=workspace_root, memory_file=memory_file)


def parse_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    data: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        data[key] = value
    return data


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text or "")


def read_json_file(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def append_memory(memory_file: Path, prompt: str, response: str) -> None:
    clean_response = " ".join(response.split())
    with memory_file.open("a", encoding="utf-8") as handle:
        handle.write(f"User: {prompt}\n")
        handle.write(f"Assistant: {clean_response[:500]}\n\n")


def actual_route_from(outcome: Dict[str, str], execution_contract: Optional[Dict[str, Any]]) -> str:
    if outcome.get("MODE"):
        return outcome["MODE"]
    if execution_contract:
        contract = execution_contract.get("execution_contract")
        if isinstance(contract, dict):
            route = contract.get("route")
            if isinstance(route, str):
                return route
    return ""


def actual_requires_sources_from(outcome: Dict[str, str], execution_contract: Optional[Dict[str, Any]]) -> Optional[bool]:
    if execution_contract:
        contract = execution_contract.get("execution_contract")
        if isinstance(contract, dict) and isinstance(contract.get("requires_sources"), bool):
            return bool(contract["requires_sources"])
    if outcome.get("GOVERNOR_REQUIRES_SOURCES"):
        return outcome["GOVERNOR_REQUIRES_SOURCES"].strip().lower() == "true"
    return None


def actual_requires_clarification_from(outcome: Dict[str, str], execution_contract: Optional[Dict[str, Any]]) -> Optional[bool]:
    if execution_contract:
        contract = execution_contract.get("execution_contract")
        if isinstance(contract, dict) and isinstance(contract.get("requires_clarification"), bool):
            return bool(contract["requires_clarification"])
    if outcome.get("GOVERNOR_REQUIRES_CLARIFICATION"):
        return outcome["GOVERNOR_REQUIRES_CLARIFICATION"].strip().lower() == "true"
    return None


def family_match(expected_family: str, actual_route: str, actual_outcome_code: str, response_text: str) -> bool:
    if actual_outcome_code.startswith(expected_family):
        return True
    matcher = OUTCOME_FAMILY_MATCHERS.get(expected_family)
    if matcher is None:
        return False
    return bool(matcher(actual_route, actual_outcome_code, response_text))


def collect_forbidden_hits(forbidden: Iterable[Dict[str, Any]], actual_route: str, response_text: str) -> List[str]:
    hits: List[str] = []
    response_norm = response_text.lower()
    for rule in forbidden:
        if not isinstance(rule, dict):
            continue
        route = rule.get("route")
        if isinstance(route, str) and route == actual_route:
            hits.append(f"forbidden_route:{route}")
        needle = rule.get("response_contains")
        if isinstance(needle, str) and needle.lower() in response_norm:
            hits.append(f"forbidden_response_contains:{needle}")
    return hits


def categorize_failure(
    case: Dict[str, Any],
    capture_ok: bool,
    governor_contract: Optional[Dict[str, Any]],
    execution_contract: Optional[Dict[str, Any]],
    actual_route: str,
    actual_requires_sources: Optional[bool],
    actual_requires_clarify: Optional[bool],
    actual_outcome_code: str,
    forbidden_hits: List[str],
    outcome_family_ok: bool,
) -> Optional[str]:
    expected = case["expected"]
    category = str(case.get("category") or "")
    if not capture_ok:
        return "logging_or_contract_capture_failure"

    gov_contract = governor_contract.get("execution_contract") if isinstance(governor_contract, dict) else None
    exe_contract = execution_contract.get("execution_contract") if isinstance(execution_contract, dict) else None
    if not isinstance(gov_contract, dict) or not isinstance(exe_contract, dict):
        return "logging_or_contract_capture_failure"

    contract_route = str(gov_contract.get("route") or "")
    execution_route = str(exe_contract.get("route") or "")
    if contract_route != execution_route:
        if actual_route == "LOCAL":
            return "fast_path_contract_bypass"
        return "policy_leakage_execution"
    if bool(gov_contract.get("requires_sources")) != bool(exe_contract.get("requires_sources")):
        return "policy_leakage_execution"
    if bool(gov_contract.get("requires_clarification")) != bool(exe_contract.get("requires_clarification")):
        return "policy_leakage_execution"

    if actual_route != expected["route"]:
        if category.startswith("followup_"):
            return "followup_context_failure"
        if category == "mode_handling":
            return "mode_handling_failure"
        return "route_drift"
    if actual_requires_sources is None or actual_requires_sources != bool(expected["requires_evidence"]):
        return "evidence_requirement_drift"
    if actual_requires_clarify is None or actual_requires_clarify != bool(expected["requires_clarify"]):
        return "clarify_failure"

    if forbidden_hits:
        if category in SENSITIVE_WORDING_CATEGORIES:
            return "wording_drift_sensitive_domain"
        if any(hit.startswith("forbidden_route:") for hit in forbidden_hits):
            if category.startswith("followup_"):
                return "followup_context_failure"
            if category == "mode_handling":
                return "mode_handling_failure"
            return "route_drift"
        return "wording_drift_sensitive_domain"

    if not outcome_family_ok:
        if category in SENSITIVE_WORDING_CATEGORIES:
            return "wording_drift_sensitive_domain"
        return "unexpected_fallback"
    if not actual_outcome_code:
        return "logging_or_contract_capture_failure"
    return None


def write_case_artifacts(
    case_artifact_dir: Path,
    stdout_text: str,
    stderr_text: str,
    classifier_payload: Optional[Dict[str, Any]],
    governor_payload: Optional[Dict[str, Any]],
    execution_payload: Optional[Dict[str, Any]],
    metadata: Dict[str, Any],
) -> None:
    case_artifact_dir.mkdir(parents=True, exist_ok=True)
    (case_artifact_dir / "response.txt").write_text(stdout_text, encoding="utf-8")
    (case_artifact_dir / "raw.log").write_text(
        f"STDOUT:\n{stdout_text}\n\nSTDERR:\n{stderr_text}\n",
        encoding="utf-8",
    )
    (case_artifact_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if classifier_payload is not None:
        (case_artifact_dir / "classifier_output.json").write_text(json.dumps(classifier_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if governor_payload is not None:
        (case_artifact_dir / "governor_contract.json").write_text(json.dumps(governor_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if execution_payload is not None:
        (case_artifact_dir / "execution_contract.json").write_text(json.dumps(execution_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_case(
    real_root: Path,
    artifacts_dir: Path,
    workspaces_dir: Path,
    case: Dict[str, Any],
    defaults: Dict[str, Any],
    sessions: Dict[str, SessionContext],
) -> Dict[str, Any]:
    case_id = str(case["id"])
    conversation_key = str(case.get("conversation") or f"case_{case_id}")
    reset_requested = bool(case.get("conversation_reset", defaults.get("conversation_reset", True)))
    reuse_session = bool(case.get("conversation"))
    if not reuse_session or reset_requested and conversation_key not in sessions:
        sessions[conversation_key] = ensure_workspace(real_root, workspaces_dir, conversation_key)
    session = sessions[conversation_key]

    case_artifact_dir = artifacts_dir / "cases" / sanitize_name(case_id)
    classifier_path = case_artifact_dir / "classifier_output.json"
    governor_path = case_artifact_dir / "governor_contract.json"
    execution_path = case_artifact_dir / "execution_contract.json"

    env = os.environ.copy()
    env["LUCY_ROOT"] = str(session.workspace_root)
    env["LUCY_ROUTE_CONTROL_MODE"] = MODE_MAP[str(case["mode"])]
    env["LUCY_SESSION_MEMORY"] = "1"
    env["LUCY_CHAT_MEMORY_FILE"] = str(session.memory_file)
    env["LUCY_CLASSIFIER_TRACE_FILE"] = str(classifier_path)
    env["LUCY_ROUTER_TRACE_FILE"] = str(governor_path)
    env["LUCY_EXECUTION_CONTRACT_TRACE_FILE"] = str(execution_path)
    env["LUCY_LOCAL_KEEP_ALIVE"] = env.get("LUCY_LOCAL_KEEP_ALIVE", "10m")
    env["LUCY_LOCAL_WORKER_TRANSPORT"] = env.get("LUCY_LOCAL_WORKER_TRANSPORT", "fifo")

    exec_plan = session.workspace_root / "tools" / "router" / "execute_plan.sh"
    proc = subprocess.run(
        [str(exec_plan), str(case["prompt"])],
        cwd=str(real_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    stdout_text = strip_ansi(proc.stdout).strip()
    stderr_text = strip_ansi(proc.stderr).strip()
    classifier_payload = read_json_file(classifier_path)
    governor_payload = read_json_file(governor_path)
    execution_payload = read_json_file(execution_path)
    last_outcome = parse_env_file(session.workspace_root / "state" / "last_outcome.env")
    last_route = parse_env_file(session.workspace_root / "state" / "last_route.env")

    if reuse_session and stdout_text:
        append_memory(session.memory_file, str(case["prompt"]), stdout_text)

    actual_route = actual_route_from(last_outcome, execution_payload)
    actual_requires_sources = actual_requires_sources_from(last_outcome, execution_payload)
    actual_requires_clarify = actual_requires_clarification_from(last_outcome, execution_payload)
    actual_outcome_code = last_outcome.get("OUTCOME_CODE", "")
    forbidden_hits = collect_forbidden_hits(case.get("forbidden", []), actual_route, stdout_text)

    capture_ok = all(payload is not None for payload in (classifier_payload, governor_payload, execution_payload)) and bool(actual_outcome_code)
    outcome_family_ok = family_match(str(case["expected"]["outcome_family"]), actual_route, actual_outcome_code, stdout_text)
    failure_category = categorize_failure(
        case=case,
        capture_ok=capture_ok,
        governor_contract=governor_payload,
        execution_contract=execution_payload,
        actual_route=actual_route,
        actual_requires_sources=actual_requires_sources,
        actual_requires_clarify=actual_requires_clarify,
        actual_outcome_code=actual_outcome_code,
        forbidden_hits=forbidden_hits,
        outcome_family_ok=outcome_family_ok,
    )
    if failure_category is not None and failure_category not in FAILURE_CATEGORIES:
        raise RuntimeError(f"invalid failure category: {failure_category}")

    result = {
        "test_id": case_id,
        "category": case["category"],
        "mode": case["mode"],
        "prompt": case["prompt"],
        "expected_route": case["expected"]["route"],
        "actual_route": actual_route,
        "expected_requires_evidence": bool(case["expected"]["requires_evidence"]),
        "actual_requires_evidence": actual_requires_sources,
        "expected_requires_clarify": bool(case["expected"]["requires_clarify"]),
        "actual_requires_clarify": actual_requires_clarify,
        "expected_outcome_family": case["expected"]["outcome_family"],
        "actual_outcome_code": actual_outcome_code,
        "governor_contract": governor_payload.get("execution_contract") if isinstance(governor_payload, dict) else None,
        "execution_received_contract": execution_payload.get("execution_contract") if isinstance(execution_payload, dict) else None,
        "response_text": stdout_text,
        "forbidden_hits": forbidden_hits,
        "pass": failure_category is None,
        "failure_category": failure_category,
    }

    metadata = {
        "returncode": proc.returncode,
        "stderr": stderr_text,
        "workspace_root": str(session.workspace_root),
        "memory_file": str(session.memory_file),
        "last_outcome": last_outcome,
        "last_route": last_route,
    }
    write_case_artifacts(case_artifact_dir, stdout_text, stderr_text, classifier_payload, governor_payload, execution_payload, metadata)
    return result


def summarize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    totals = {
        "total": len(results),
        "passed": sum(1 for item in results if item["pass"]),
        "failed": sum(1 for item in results if not item["pass"]),
    }
    by_category: Dict[str, int] = {}
    for item in results:
        key = item.get("failure_category") or "pass"
        by_category[key] = by_category.get(key, 0) + 1
    return {"totals": totals, "by_failure_category": by_category}


def write_jsonl(path: Path, results: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in results:
            handle.write(json.dumps(item, sort_keys=True) + "\n")


def write_report(path: Path, suite_name: str, results: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    lines: List[str] = []
    totals = summary["totals"]
    lines.append("# Governor Migration Validation Report")
    lines.append(f"Suite: {suite_name}")
    lines.append("")
    lines.append("## Totals")
    lines.append(f"- total: {totals['total']}")
    lines.append(f"- passed: {totals['passed']}")
    lines.append(f"- failed: {totals['failed']}")
    lines.append("")
    lines.append("## Failures By Category")
    for key in sorted(summary["by_failure_category"]):
        lines.append(f"- {key}: {summary['by_failure_category'][key]}")
    lines.append("")
    failures = [item for item in results if not item["pass"]]
    lines.append("## Failing Test Table")
    if not failures:
        lines.append("All cases passed.")
    else:
        lines.append("| test_id | category | failure_category | expected_route | actual_route | outcome |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for item in failures:
            lines.append(
                f"| {item['test_id']} | {item['category']} | {item['failure_category']} | "
                f"{item['expected_route']} | {item['actual_route']} | {item['actual_outcome_code']} |"
            )
    lines.append("")
    lines.append("## Likely Root Cause Notes")
    noted = sorted({item["failure_category"] for item in failures if item.get("failure_category")})
    if not noted:
        lines.append("- none")
    else:
        for category in noted:
            lines.append(f"- {category}: {ROOT_CAUSE_NOTES[category]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def stop_workers(sessions: Dict[str, SessionContext], real_root: Path) -> None:
    for session in sessions.values():
        worker = session.workspace_root / "tools" / "local_worker.py"
        if not worker.exists():
            continue
        env = os.environ.copy()
        env["LUCY_ROOT"] = str(session.workspace_root)
        env["LUCY_LOCAL_WORKER_TRANSPORT"] = env.get("LUCY_LOCAL_WORKER_TRANSPORT", "fifo")
        subprocess.run(
            [sys.executable, str(worker), "stop"],
            cwd=str(real_root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


def main() -> int:
    args = parse_args()
    suite_path = Path(args.suite).resolve()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    workspaces_dir = artifacts_dir / "workspaces"
    workspaces_dir.mkdir(exist_ok=True)
    shutil.copy2(suite_path, artifacts_dir / suite_path.name)

    suite = load_yaml(suite_path)
    real_root = Path(str(suite.get("snapshot_root") or "")).resolve()
    if not real_root.exists():
        raise SystemExit(f"ERROR: snapshot root missing: {real_root}")

    defaults = suite.get("defaults") or {}
    cases = suite.get("cases")
    if not isinstance(cases, list):
        raise SystemExit("ERROR: suite cases must be a list")

    filtered_cases: List[Dict[str, Any]] = []
    for raw_case in cases:
        if not isinstance(raw_case, dict):
            continue
        if args.category and raw_case.get("category") != args.category:
            continue
        if args.case and raw_case.get("id") != args.case:
            continue
        filtered_cases.append(raw_case)
    if not filtered_cases:
        raise SystemExit("ERROR: no cases matched the requested filters")

    sessions: Dict[str, SessionContext] = {}
    results: List[Dict[str, Any]] = []
    try:
        for case in filtered_cases:
            results.append(run_case(real_root, artifacts_dir, workspaces_dir, case, defaults, sessions))
    finally:
        stop_workers(sessions, real_root)

    write_jsonl(artifacts_dir / "results.jsonl", results)
    summary = summarize_results(results)
    write_report(artifacts_dir / "report.md", str(suite.get("suite") or "unknown_suite"), results, summary)
    print(json.dumps({"artifacts_dir": str(artifacts_dir), **summary["totals"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
