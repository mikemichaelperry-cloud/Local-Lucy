#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[2]
EXECUTE_PLAN = ROOT / "tools" / "router" / "execute_plan.sh"
ARTIFACT_ROOT = ROOT / "tmp" / "edge_prompt_sweep"
DESKTOP = Path("/home/mike/Desktop")
DEFAULT_REPORT_PREFIX = "LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT"
FAST_GATE_CASE_KEYS = {
    "current_events::What are the current tensions in the South China Sea?",
    "current_events::What happened in the stock market today?",
    "conceptual_local_boundary::What is a sanctions regime in international politics?",
    "conceptual_live_boundary::Is there currently a ceasefire in Gaza?",
    "url_input::https://www.who.int/health-topics/malaria",
    "mixed_intent::Tell me what RAM is and recommend a current laptop.",
    "mixed_intent::What is Reuters and show me today's Reuters headlines.",
    "ambiguous::Tell me more about it.",
    "ambiguous::Is it safe?",
    "context_followup::Is there a travel advisory for Egypt right now?",
    "context_followup::What about Jordan?",
    "context_followup::What does Lipitor do?",
    "context_followup::And grapefruit?",
}
KNOWN_MANIFEST_ROUTES = {"LOCAL", "NEWS", "EVIDENCE", "CLARIFY"}
REQUIRED_MANIFEST_FIELDS = (
    "MANIFEST_VERSION",
    "MANIFEST_SELECTED_ROUTE",
    "MANIFEST_ALLOWED_ROUTES",
    "MANIFEST_AUTHORITY_BASIS",
    "MANIFEST_CLARIFY_REQUIRED",
    "MANIFEST_CONTEXT_RESOLUTION_USED",
)


@dataclass
class SessionContext:
    key: str
    workspace_root: Path
    memory_file: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--category")
    parser.add_argument("--profile", choices=("fast", "full"))
    parser.add_argument("--timeout-s", type=int, default=120)
    parser.add_argument("--artifacts-dir")
    parser.add_argument("--report-prefix", default=DEFAULT_REPORT_PREFIX)
    parser.add_argument("--fail-on-gate", action="store_true")
    return parser.parse_args()


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


def parse_kv_lines(text: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def parse_diag_file(path: Path, run_id: str) -> Dict[str, str]:
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = {}
        for item in raw.split("\t"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            parts[key] = value
        if parts.get("run") != run_id:
            continue
        metric = parts.get("metric")
        if metric:
            out[metric] = parts.get("value", "")
    return out


def case_selector_key(case: Dict[str, Any]) -> str:
    return f"{case['category']}::{case['prompt']}"


def select_cases_for_profile(cases: List[Dict[str, Any]], profile: Optional[str]) -> List[Dict[str, Any]]:
    if not profile or profile == "full":
        return cases
    if profile != "fast":
        raise ValueError(f"unsupported profile: {profile}")
    selected = [case for case in cases if case_selector_key(case) in FAST_GATE_CASE_KEYS]
    found_keys = {case_selector_key(case) for case in selected}
    missing = sorted(FAST_GATE_CASE_KEYS - found_keys)
    if missing:
        raise ValueError(f"fast gate definition is stale; missing cases: {', '.join(missing)}")
    return selected


def append_memory(memory_file: Path, prompt: str, response: str) -> None:
    clean_response = " ".join(response.split())
    with memory_file.open("a", encoding="utf-8") as handle:
        handle.write(f"User: {prompt}\n")
        handle.write(f"Assistant: {clean_response[:500]}\n\n")


def classify_response(prompt: str, route: str, outcome_code: str, response_text: str) -> str:
    prompt_norm = prompt.strip().lower()
    looks_like_url = prompt_norm.startswith("http://") or prompt_norm.startswith("https://")
    route = route or ""
    outcome_code = outcome_code or ""
    if route == "CLARIFY" or outcome_code == "clarification_requested":
        return "clarify"
    if route == "LOCAL":
        if outcome_code in {"answered", "knowledge_short_circuit_hit", "local_guard_fallback"}:
            return "local_answer"
        if outcome_code in {"requires_evidence_mode", "validated_insufficient"}:
            return "evidence_insufficiency"
        return "execution_error"
    if route == "NEWS":
        if outcome_code == "answered":
            return "news_result"
        return "news_insufficiency"
    if route == "EVIDENCE":
        if looks_like_url:
            if outcome_code == "answered":
                return "doc_result"
            return "doc_insufficiency"
        if outcome_code == "answered":
            return "evidence_answer"
        return "evidence_insufficiency"
    if route == "DOC":
        if outcome_code == "answered":
            return "doc_result"
        return "doc_insufficiency"
    if outcome_code == "answered" and response_text.strip():
        return "answered_unclassified"
    return "execution_error"


def normalization_occurred(outcome: Dict[str, str], prompt: str) -> bool:
    prompt_norm = prompt.strip()
    checks = [
        outcome.get("EVIDENCE_NORMALIZER_DETECTOR_FIRED", "").lower() == "true",
        outcome.get("SEMANTIC_INTERPRETER_FIRED", "").lower() == "true"
        and outcome.get("SEMANTIC_INTERPRETER_SELECTED_NORMALIZED_QUERY", "") not in {"", prompt_norm},
        outcome.get("EVIDENCE_NORMALIZER_SELECTED_QUERY", "") not in {"", prompt_norm},
        outcome.get("MEDICATION_DETECTOR_FIRED", "").lower() == "true"
        and outcome.get("MEDICATION_DETECTOR_NORMALIZED_QUERY", "") not in {"", prompt_norm},
    ]
    return any(checks)


def provenance_preserved(prompt: str, outcome: Dict[str, str]) -> bool:
    if outcome.get("QUERY") != prompt:
        return False
    semantic_fired = outcome.get("SEMANTIC_INTERPRETER_FIRED", "").lower() == "true"
    if semantic_fired and outcome.get("SEMANTIC_INTERPRETER_ORIGINAL_QUERY") != prompt:
        return False
    med_fired = outcome.get("MEDICATION_DETECTOR_FIRED", "").lower() == "true"
    if med_fired and outcome.get("MEDICATION_DETECTOR_ORIGINAL_QUERY") != prompt:
        return False
    return True


def _manifest_field_issues(fields: Dict[str, str], observed_route: str, source: str) -> List[str]:
    reasons: List[str] = []
    if not fields:
        return [f"{source}_manifest_missing_block"]
    for field in REQUIRED_MANIFEST_FIELDS:
        if not (fields.get(field) or "").strip():
            reasons.append(f"{source}_{field.lower()}_missing")

    manifest_version = (fields.get("MANIFEST_VERSION") or "").strip()
    if manifest_version and manifest_version != "v1":
        reasons.append(f"{source}_manifest_version_invalid:{manifest_version}")

    selected_route = (fields.get("MANIFEST_SELECTED_ROUTE") or "").strip().upper()
    if selected_route and selected_route not in KNOWN_MANIFEST_ROUTES:
        reasons.append(f"{source}_manifest_selected_route_invalid:{selected_route}")

    allowed_routes = [
        item.strip().upper()
        for item in (fields.get("MANIFEST_ALLOWED_ROUTES") or "").split(",")
        if item.strip()
    ]
    if fields.get("MANIFEST_ALLOWED_ROUTES") and not allowed_routes:
        reasons.append(f"{source}_manifest_allowed_routes_invalid")
    if selected_route and allowed_routes and selected_route not in allowed_routes:
        reasons.append(f"{source}_manifest_selected_route_not_allowed:{selected_route}")

    clarify_required = (fields.get("MANIFEST_CLARIFY_REQUIRED") or "").strip().lower()
    if clarify_required and clarify_required not in {"true", "false"}:
        reasons.append(f"{source}_manifest_clarify_required_invalid:{clarify_required}")

    context_resolution_used = (fields.get("MANIFEST_CONTEXT_RESOLUTION_USED") or "").strip().lower()
    if context_resolution_used and context_resolution_used not in {"true", "false"}:
        reasons.append(f"{source}_manifest_context_resolution_invalid:{context_resolution_used}")

    if observed_route and selected_route and observed_route.strip().upper() != selected_route:
        reasons.append(f"{source}_manifest_route_mismatch:{selected_route}->{observed_route.strip().upper()}")
    return reasons


def validate_manifest(
    dry_fields: Dict[str, str],
    live_fields: Dict[str, str],
    route: str,
    dry: subprocess.CompletedProcess[str],
    live: subprocess.CompletedProcess[str],
) -> List[str]:
    reasons: List[str] = []
    reasons.extend(_manifest_field_issues(dry_fields, dry_fields.get("PIPELINE", ""), "dryrun"))
    reasons.extend(_manifest_field_issues(live_fields, route, "live"))

    dry_text = f"{dry.stdout}\n{dry.stderr}".lower()
    live_text = f"{live.stdout}\n{live.stderr}".lower()
    if "malformed route manifest:" in dry_text:
        reasons.append("dryrun_manifest_runtime_error")
    if "malformed route manifest:" in live_text:
        reasons.append("live_manifest_runtime_error")
    return reasons


def evaluate_expectation(case: Dict[str, Any], route: str, response_class: str) -> tuple[bool, List[str], bool]:
    reasons: List[str] = []
    expected_routes = case.get("expected_routes") or []
    must_not_routes = case.get("must_not_routes") or []
    route_ok = True
    if expected_routes and route not in expected_routes:
        route_ok = False
        reasons.append(f"expected_routes={','.join(expected_routes)} actual={route or 'none'}")
    if route in must_not_routes:
        route_ok = False
        reasons.append(f"forbidden_route={route}")
    boundary_violation = bool(case.get("must_not_local")) and route == "LOCAL" and response_class == "local_answer"
    if boundary_violation:
        reasons.append("authority_boundary_violation:nonlocal_prompt_answered_locally")
    return route_ok and not boundary_violation, reasons, boundary_violation


def make_case(case_id: str, category: str, prompt: str, expected_routes: Iterable[str], *,
              must_not_routes: Optional[Iterable[str]] = None,
              must_not_local: bool = False,
              conversation_key: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": case_id,
        "category": category,
        "prompt": prompt,
        "expected_routes": list(expected_routes),
        "must_not_routes": list(must_not_routes or []),
        "must_not_local": must_not_local,
        "conversation_key": conversation_key,
    }


def build_corpus() -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    idx = defaultdict(int)

    def add(category: str, prompt: str, expected_routes: Iterable[str], *,
            must_not_routes: Optional[Iterable[str]] = None,
            must_not_local: bool = False,
            conversation_key: Optional[str] = None) -> None:
        idx[category] += 1
        case_id = f"{category}_{idx[category]:03d}"
        cases.append(
            make_case(
                case_id,
                category,
                prompt,
                expected_routes,
                must_not_routes=must_not_routes,
                must_not_local=must_not_local,
                conversation_key=conversation_key,
            )
        )

    for prompt in [
        "What was the purpose of the Antikythera mechanism?",
        "Explain the law of Biot-Savart.",
        "Where is Svalbard located?",
        "What is the Titius-Bode law?",
        "What is the difference between basalt and gabbro?",
        "What was the Bayeux Tapestry?",
        "What does an isthmus mean in geography?",
        "What is the Chandrasekhar limit?",
        "Who were the Phoenicians?",
        "What is the Fermi paradox?",
        "What was the historical significance of the Rosetta Stone?",
        "What is an oxbow lake?",
    ]:
        add("obscure_fact", prompt, ["LOCAL"])

    for prompt in [
        "What is a thixotropic fluid?",
        "Explain the difference between a klystron and a magnetron.",
        "What does a helioseismologist study?",
        "What is a cryotron?",
        "What is a geoid?",
        "What is a zeugma in rhetoric?",
        "What does a luthier do?",
        "What is the difference between a moraine and a drumlin?",
        "What is a Faraday cage?",
        "What is a pelagic zone?",
        "What is a barycenter?",
        "What does endothermic mean in chemistry?",
    ]:
        add("niche_topic", prompt, ["LOCAL"])

    for prompt in [
        "What are the side effects of ibuprofen?",
        "Does tadalafil interact with alcohol?",
        "Is Lipitor safe with grapefruit?",
        "What is Tadalifil?",
        "What does amoxycillin do?",
        "Can sildenafil interact with nitrates?",
        "Side effects of metformin?",
        "Is Panadol the same as acetaminophen?",
        "Dose of Panadol?",
        "Can ibuprofen affect blood pressure?",
        "Is amoxicillin safe with alcohol?",
        "What are the contraindications of Cialis?",
        "Does tadalafil raise heart rate?",
        "Can Lipitor interact with other drugs?",
    ]:
        add("medication_health", prompt, ["EVIDENCE"], must_not_routes=["LOCAL"], must_not_local=True)

    for prompt in [
        "What is happening in Israel today?",
        "Latest news about SpaceX Starship.",
        "What are the current tensions in the South China Sea?",
        "What's the latest on Nvidia earnings?",
        "Any major headlines from Europe today?",
        "What is the current situation in Gaza?",
        "What happened in the stock market today?",
        "What is the latest on the US election?",
        "Current wildfire situation in California?",
        "What are today's top technology headlines?",
        "Is there breaking news about OpenAI today?",
        "Latest updates on the Ukraine war.",
    ]:
        add("current_events", prompt, ["NEWS", "EVIDENCE"], must_not_routes=["LOCAL"], must_not_local=True)

    for prompt in [
        "What is a travel advisory?",
        "What is a ceasefire?",
        "What is a sanctions regime in international politics?",
        "What does a product recall mean?",
        "What is inflation?",
        "What is a filing deadline?",
    ]:
        add("conceptual_local_boundary", prompt, ["LOCAL"])

    for prompt in [
        "Is there a travel advisory for Egypt right now?",
        "Is there a recall on Toyota vehicles right now?",
        "What is the current inflation rate in the US?",
        "Has the filing deadline for US taxes changed this year?",
        "Is there currently a ceasefire in Gaza?",
        "Are there sanctions on Iran right now?",
    ]:
        add("conceptual_live_boundary", prompt, ["EVIDENCE", "NEWS"], must_not_routes=["LOCAL"], must_not_local=True)

    for prompt in [
        "https://reuters.com",
        "https://www.who.int/health-topics/malaria",
        "https://en.wikipedia.org/wiki/Antikythera_mechanism",
        "https://www.bbc.com/news",
        "https://www.fda.gov/drugs",
        "https://www.cdc.gov/flu/",
        "https://pubmed.ncbi.nlm.nih.gov/",
        "https://www.nasa.gov/",
        "https://www.ft.com/",
        "https://boi.org.il/",
        "https://www.mayoclinic.org/drugs-supplements",
        "https://jamanetwork.com/",
    ]:
        add("url_input", prompt, ["EVIDENCE", "NEWS", "DOC"], must_not_routes=["LOCAL"], must_not_local=True)

    for prompt, expected_routes, must_not_local in [
        ("Tadalifil?", ["EVIDENCE"], True),
        ("side effects ibuprofen??", ["EVIDENCE"], True),
        ("cpu stand for", ["LOCAL"], False),
        ("explain ram vs storage quickly pls", ["LOCAL"], False),
        ("whats antikythera mechanism", ["LOCAL"], False),
        ("latest israel news rn", ["NEWS", "EVIDENCE"], True),
        ("does cialis + alcohol bad?", ["EVIDENCE"], True),
        ("travel advisory egypt now?", ["EVIDENCE", "NEWS"], True),
        ("reuters dot com", ["LOCAL"], False),
        ("why sky blue short", ["LOCAL"], False),
        ("amoxycillin + booze?", ["EVIDENCE"], True),
        ("svalbard where is it", ["LOCAL"], False),
        ("what happening south china sea rn", ["NEWS", "EVIDENCE"], True),
        ("lipitor grapefruit ok?", ["EVIDENCE"], True),
    ]:
        add("messy_human", prompt, expected_routes, must_not_routes=["LOCAL"] if must_not_local else None, must_not_local=must_not_local)

    for prompt, expected_routes, must_not_local in [
        ("What does ibuprofen do and is there any current warning about it?", ["EVIDENCE", "NEWS"], True),
        ("Explain Ohm's law and show a real example.", ["LOCAL"], False),
        ("What is a travel advisory and is there one for Egypt right now?", ["EVIDENCE", "NEWS"], True),
        ("Tell me what RAM is and recommend a current laptop.", ["EVIDENCE", "NEWS"], True),
        ("What is malaria and what is the latest WHO advice on it?", ["EVIDENCE", "NEWS"], True),
        ("Explain inflation and tell me the current US rate.", ["EVIDENCE", "NEWS"], True),
        ("What is Reuters and show me today's Reuters headlines.", ["EVIDENCE", "NEWS"], True),
        ("What is a transistor and why is Nvidia in the news?", ["EVIDENCE", "NEWS"], True),
        ("What does Lipitor do and can it interact with grapefruit?", ["EVIDENCE"], True),
        ("Explain the Fermi paradox and mention whether there was any new SETI news today.", ["EVIDENCE", "NEWS"], True),
        ("What is a ceasefire and is there one in Gaza today?", ["EVIDENCE", "NEWS"], True),
        ("Explain what a klystron is and give one real-world use.", ["LOCAL"], False),
    ]:
        add("mixed_intent", prompt, expected_routes, must_not_routes=["LOCAL"] if must_not_local else None, must_not_local=must_not_local)

    for prompt in [
        "What about that one?",
        "Tell me more about it.",
        "Can you check that?",
        "Is it safe?",
        "What do you mean?",
        "And the other one?",
        "Which one is better?",
        "How about now?",
        "Explain it again.",
        "What should I do then?",
        "Is that still true?",
        "Can you continue?",
    ]:
        add("ambiguous", prompt, ["CLARIFY"])

    for prompt, expected_routes, must_not_local in [
        ('"What is a klystron?"', ["LOCAL"], False),
        ("Explain Ohm's law (short answer)", ["LOCAL"], False),
        ("LAW OF OHM?", ["LOCAL"], False),
        ("[What is a travel advisory?]", ["LOCAL"], False),
        ("{What is RAM?}", ["LOCAL"], False),
        ("(((What is a ceasefire?)))", ["LOCAL"], False),
        ('"Is there a travel advisory for Egypt right now?"', ["EVIDENCE", "NEWS"], True),
        ("[https://reuters.com]", ["EVIDENCE", "NEWS", "DOC"], True),
        ("(side effects ibuprofen)", ["EVIDENCE"], True),
        ("<<What is happening in Israel today?>>", ["EVIDENCE", "NEWS"], True),
        ("`What is a Faraday cage?`", ["LOCAL"], False),
        ("--What is Reuters?--", ["LOCAL"], False),
    ]:
        add("edge_formatting", prompt, expected_routes, must_not_routes=["LOCAL"] if must_not_local else None, must_not_local=must_not_local)

    for prompt, expected_routes, must_not_local in [
        ("WHAT is RAM???", ["LOCAL"], False),
        ("explain... ohm's law", ["LOCAL"], False),
        ("WhAt iS SvAlBaRd???", ["LOCAL"], False),
        ("LIPITOR + GRAPEFRUIT???", ["EVIDENCE"], True),
        ("WHAT IS HAPPENING IN ISRAEL TODAY???", ["EVIDENCE", "NEWS"], True),
        ("TRAVEL ADVISORY egypt NOW??", ["EVIDENCE", "NEWS"], True),
        ("WHAT does CPU stand for??", ["LOCAL"], False),
        ("side...effects...ibuprofen", ["EVIDENCE"], True),
        ("WHAT IS A TRAVEL ADVISORY??", ["LOCAL"], False),
        ("https://REUTERS.COM", ["EVIDENCE", "NEWS", "DOC"], True),
        ("WHAT IS A KLYSTRON???", ["LOCAL"], False),
        ("TADALIFIL!!!", ["EVIDENCE"], True),
    ]:
        add("caps_punct", prompt, expected_routes, must_not_routes=["LOCAL"] if must_not_local else None, must_not_local=must_not_local)

    for prompt, expected_routes, must_not_local in [
        ("Explain RAM vs ROM and which one is faster.", ["LOCAL"], False),
        ("What does ibuprofen do and can it interact with alcohol?", ["EVIDENCE"], True),
        ("Explain the Antikythera mechanism and where it was found.", ["LOCAL"], False),
        ("What is a travel advisory and who issues them in the US?", ["LOCAL"], False),
        ("What is a travel advisory and is there one for Lebanon right now?", ["EVIDENCE", "NEWS"], True),
        ("Explain the difference between a magnetron and a klystron and give one use for each.", ["LOCAL"], False),
        ("What is Reuters and is Reuters reporting on Israel today?", ["EVIDENCE", "NEWS"], True),
        ("Explain Ohm's law and compare voltage to water pressure.", ["LOCAL"], False),
        ("What is a thixotropic fluid and give one example.", ["LOCAL"], False),
        ("What does Cialis do and what are its contraindications?", ["EVIDENCE"], True),
        ("Where is Svalbard and what's the current temperature there?", ["EVIDENCE", "NEWS"], True),
        ("What is malaria and link me to a current source about it.", ["EVIDENCE"], True),
    ]:
        add("multi_part", prompt, expected_routes, must_not_routes=["LOCAL"] if must_not_local else None, must_not_local=must_not_local)

    add("context_followup", "Tell me about the Antikythera mechanism.", ["LOCAL"], conversation_key="ctx_antiky")
    add("context_followup", "What about where it was found?", ["LOCAL"], conversation_key="ctx_antiky")
    add("context_followup", "What is Reuters?", ["LOCAL"], conversation_key="ctx_reuters")
    add("context_followup", "How reliable is it?", ["LOCAL"], conversation_key="ctx_reuters")
    add("context_followup", "Is there a travel advisory for Egypt right now?", ["EVIDENCE", "NEWS"], must_not_routes=["LOCAL"], must_not_local=True, conversation_key="ctx_travel")
    add("context_followup", "What about Jordan?", ["EVIDENCE", "NEWS"], must_not_routes=["LOCAL"], must_not_local=True, conversation_key="ctx_travel")
    add("context_followup", "What does Lipitor do?", ["EVIDENCE"], must_not_routes=["LOCAL"], must_not_local=True, conversation_key="ctx_lipitor")
    add("context_followup", "And grapefruit?", ["EVIDENCE"], must_not_routes=["LOCAL"], must_not_local=True, conversation_key="ctx_lipitor")

    return cases


def run_subprocess(args: List[str], env: Dict[str, str], timeout_s: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_case(
    case: Dict[str, Any],
    session: SessionContext,
    artifacts_dir: Path,
    timeout_s: int,
) -> Dict[str, Any]:
    case_dir = artifacts_dir / "cases" / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    prompt = case["prompt"]
    run_id = case["id"]
    diag_file = case_dir / "local_diag.tsv"
    env = os.environ.copy()
    env["LUCY_ROOT"] = str(session.workspace_root)
    env["LUCY_ROUTE_CONTROL_MODE"] = "AUTO"
    env["LUCY_LOCAL_DIAG_FILE"] = str(diag_file)
    env["LUCY_LOCAL_DIAG_RUN_ID"] = run_id

    dry_env = env.copy()
    dry_env["LUCY_ROUTER_DRYRUN"] = "1"
    dry = run_subprocess([str(session.workspace_root / "tools" / "router" / "execute_plan.sh"), prompt], dry_env, timeout_s)
    write_text(case_dir / "dryrun.stdout.txt", dry.stdout)
    write_text(case_dir / "dryrun.stderr.txt", dry.stderr)
    dry_fields = parse_kv_lines(dry.stdout)

    live = run_subprocess([str(session.workspace_root / "tools" / "router" / "execute_plan.sh"), prompt], env, timeout_s)
    write_text(case_dir / "live.stdout.txt", live.stdout)
    write_text(case_dir / "live.stderr.txt", live.stderr)

    last_outcome = parse_env_file(session.workspace_root / "state" / "last_outcome.env")
    last_route = parse_env_file(session.workspace_root / "state" / "last_route.env")
    diag = parse_diag_file(diag_file, run_id)

    route = last_outcome.get("MODE") or last_outcome.get("GOVERNOR_ROUTE") or dry_fields.get("PIPELINE", "")
    governor_route = last_outcome.get("GOVERNOR_ROUTE") or dry_fields.get("GOVERNOR_ROUTE", "")
    output_mode = dry_fields.get("OUTPUT_MODE", "")
    response_text = live.stdout.strip()
    outcome_code = last_outcome.get("OUTCOME_CODE", "")
    response_class = classify_response(prompt, route, outcome_code, response_text)
    rule_ok, rule_reasons, boundary_violation = evaluate_expectation(case, route, response_class)
    provenance_ok = provenance_preserved(prompt, last_outcome)
    if not provenance_ok:
        rule_reasons.append("original_query_provenance_not_preserved")
    route_mismatch = bool(dry_fields.get("PIPELINE")) and dry_fields.get("PIPELINE") != route
    if route_mismatch:
        rule_reasons.append(f"dryrun_live_route_mismatch:{dry_fields.get('PIPELINE')}->{route}")
    manifest_reasons = validate_manifest(dry_fields, last_outcome, route, dry, live)
    manifest_ok = not manifest_reasons
    if not manifest_ok:
        rule_reasons.extend(manifest_reasons)
    execution_error = dry.returncode != 0 or live.returncode != 0
    if execution_error:
        rule_reasons.append(f"execute_plan_return_code:dry={dry.returncode},live={live.returncode}")

    planner_fired = last_outcome.get("EVIDENCE_PLANNER_FIRED", "").lower() == "true"
    semantic_fired = last_outcome.get("SEMANTIC_INTERPRETER_FIRED", "").lower() == "true"
    med_fired = last_outcome.get("MEDICATION_DETECTOR_FIRED", "").lower() == "true"
    normalizer_fired = last_outcome.get("EVIDENCE_NORMALIZER_DETECTOR_FIRED", "").lower() == "true"
    normalized = normalization_occurred(last_outcome, prompt)

    result = {
        "id": case["id"],
        "category": case["category"],
        "conversation_key": case.get("conversation_key"),
        "prompt": prompt,
        "dryrun_pipeline": dry_fields.get("PIPELINE", ""),
        "dryrun_governor_route": dry_fields.get("GOVERNOR_ROUTE", ""),
        "pipeline": route,
        "governor_route": governor_route,
        "output_mode": output_mode,
        "semantic_interpreter_fired": semantic_fired,
        "semantic_interpreter_use_reason": last_outcome.get("SEMANTIC_INTERPRETER_USE_REASON", ""),
        "semantic_interpreter_original_query": last_outcome.get("SEMANTIC_INTERPRETER_ORIGINAL_QUERY", ""),
        "semantic_interpreter_resolved_execution_query": last_outcome.get("SEMANTIC_INTERPRETER_RESOLVED_EXECUTION_QUERY", ""),
        "medication_detector_fired": med_fired,
        "medication_detector_source": last_outcome.get("MEDICATION_DETECTOR_DETECTION_SOURCE", ""),
        "medication_detector_original_query": last_outcome.get("MEDICATION_DETECTOR_ORIGINAL_QUERY", ""),
        "medication_detector_resolved_execution_query": last_outcome.get("MEDICATION_DETECTOR_RESOLVED_EXECUTION_QUERY", ""),
        "evidence_planner_fired": planner_fired,
        "evidence_normalizer_fired": normalizer_fired,
        "normalization_occurred": normalized,
        "response_classification": response_class,
        "outcome_code": outcome_code,
        "response_text": response_text,
        "response_preview": response_text[:240],
        "rc": live.returncode,
        "dryrun_rc": dry.returncode,
        "rule_ok": rule_ok and provenance_ok and not route_mismatch and manifest_ok and not execution_error,
        "rule_reasons": rule_reasons,
        "boundary_violation": boundary_violation,
        "provenance_preserved": provenance_ok,
        "route_mismatch": route_mismatch,
        "manifest_ok": manifest_ok,
        "manifest_reasons": manifest_reasons,
        "manifest_version": last_outcome.get("MANIFEST_VERSION", ""),
        "manifest_selected_route": last_outcome.get("MANIFEST_SELECTED_ROUTE", ""),
        "manifest_allowed_routes": last_outcome.get("MANIFEST_ALLOWED_ROUTES", ""),
        "manifest_authority_basis": last_outcome.get("MANIFEST_AUTHORITY_BASIS", ""),
        "execution_error": execution_error,
        "query_field": last_outcome.get("QUERY", ""),
        "generation_profile": diag.get("generation_profile", ""),
        "generation_num_predict": diag.get("generation_num_predict", ""),
        "response_est_tokens": diag.get("response_est_tokens", ""),
        "local_direct_used": last_outcome.get("LOCAL_DIRECT_USED", ""),
        "local_direct_path": last_outcome.get("LOCAL_DIRECT_PATH", ""),
        "resolved_execution_query": last_outcome.get("SEMANTIC_INTERPRETER_RESOLVED_EXECUTION_QUERY")
        or last_outcome.get("MEDICATION_DETECTOR_RESOLVED_EXECUTION_QUERY")
        or dry_fields.get("RESOLVED_QUESTION", ""),
        "last_outcome_path": str(session.workspace_root / "state" / "last_outcome.env"),
        "last_route_path": str(session.workspace_root / "state" / "last_route.env"),
        "case_dir": str(case_dir),
        "last_outcome": last_outcome,
        "last_route": last_route,
        "diag": diag,
    }

    if case.get("conversation_key"):
        append_memory(session.memory_file, prompt, response_text)

    write_text(case_dir / "result.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def choose_notable_successes(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for result in results:
        if not result["rule_ok"]:
            continue
        if result["category"] in {"messy_human", "edge_formatting", "caps_punct", "context_followup", "mixed_intent"}:
            out.append(result)
        elif result["semantic_interpreter_fired"] or result["medication_detector_fired"] or result["evidence_planner_fired"]:
            out.append(result)
        if len(out) >= 10:
            break
    return out


def choose_interesting_edges(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for result in results:
        if result["route_mismatch"] or result["boundary_violation"]:
            continue
        if result["category"] == "context_followup":
            out.append(result)
        elif result["semantic_interpreter_fired"] and result["category"] in {"messy_human", "mixed_intent"}:
            out.append(result)
        elif result["medication_detector_fired"] and result["category"] in {"messy_human", "medication_health"}:
            out.append(result)
        if len(out) >= 8:
            break
    return out


def build_suggestions(results: List[Dict[str, Any]]) -> List[str]:
    suggestions: List[str] = []
    anomalies = [r for r in results if not r["rule_ok"]]
    if not anomalies:
        suggestions.append("Keep this sweep in the regression toolbox and rerun it after major router/interpreter changes.")
    current_event_evidence = sum(1 for r in results if r["category"] == "current_events" and r["pipeline"] == "EVIDENCE")
    current_event_news = sum(1 for r in results if r["category"] == "current_events" and r["pipeline"] == "NEWS")
    if current_event_evidence and current_event_news == 0:
        suggestions.append("Current-events prompts skewed toward EVIDENCE rather than NEWS; review whether NEWS recall should be broadened for headline-style wording.")
    url_non_doc = sum(1 for r in results if r["category"] == "url_input" and r["pipeline"] not in {"DOC", "EVIDENCE"})
    if url_non_doc:
        suggestions.append("Some URL prompts did not land on a doc-style non-local path; inspect URL surface detection and doc routing.")
    provenance_misses = sum(1 for r in results if not r["provenance_preserved"])
    if provenance_misses:
        suggestions.append("Some cases lost original-query provenance in traces; inspect QUERY/original-query propagation before further semantic changes.")
    boundary_violations = sum(1 for r in results if r["boundary_violation"])
    if boundary_violations:
        suggestions.append("At least one evidence-required family was answered from LOCAL; prioritize that boundary leak before further tuning.")
    med_detector_weird = sum(
        1 for r in results
        if not r["medication_detector_fired"]
        and r["last_outcome"].get("MEDICATION_DETECTOR_CANDIDATE_MEDICATION")
    )
    if med_detector_weird:
        suggestions.append("Medication detector emits candidate strings even when not fired; consider clearing non-fired candidate fields to reduce trace noise.")
    if not suggestions:
        suggestions.append("No urgent behavioral issues were discovered in this sweep; focus next on adding this corpus to a repeatable nightly validation pass.")
    return suggestions[:5]


def build_summary(
    results: List[Dict[str, Any]],
    artifacts_dir: Path,
    corpus_path: Path,
    results_path: Path,
    report_path: Path,
    profile: str,
) -> Dict[str, Any]:
    prompts_tested = len(results)
    rule_consistent_count = sum(1 for result in results if result["rule_ok"])
    provenance_preserved_count = sum(1 for result in results if result["provenance_preserved"])
    anomalies = sum(1 for result in results if not result["rule_ok"])
    authority_boundary_violations = sum(1 for result in results if result["boundary_violation"])
    route_mismatches = sum(1 for result in results if result["route_mismatch"])
    manifest_failures = sum(1 for result in results if not result["manifest_ok"])
    execution_errors = sum(1 for result in results if result["execution_error"])
    gate_failed = any(
        (
            anomalies,
            authority_boundary_violations,
            route_mismatches,
            manifest_failures,
            prompts_tested - provenance_preserved_count,
            execution_errors,
        )
    )
    return {
        "profile": profile,
        "gate_status": "FAIL" if gate_failed else "PASS",
        "prompts_tested": prompts_tested,
        "rule_consistent_count": rule_consistent_count,
        "rule_consistent_ratio": f"{rule_consistent_count}/{prompts_tested}",
        "provenance_preserved_count": provenance_preserved_count,
        "provenance_preserved_ratio": f"{provenance_preserved_count}/{prompts_tested}",
        "anomalies": anomalies,
        "authority_boundary_violations": authority_boundary_violations,
        "route_mismatches": route_mismatches,
        "manifest_failures": manifest_failures,
        "execution_errors": execution_errors,
        "artifacts_dir": str(artifacts_dir),
        "corpus_path": str(corpus_path),
        "results_path": str(results_path),
        "report_path": str(report_path),
    }


def render_report(
    results: List[Dict[str, Any]],
    artifacts_dir: Path,
    desktop_report: Path,
    corpus_path: Path,
    results_path: Path,
    summary: Dict[str, Any],
) -> str:
    total = len(results)
    pipeline_counts = Counter(result["pipeline"] or "UNKNOWN" for result in results)
    response_counts = Counter(result["response_classification"] for result in results)
    semantic_hits = sum(1 for result in results if result["semantic_interpreter_fired"])
    med_hits = sum(1 for result in results if result["medication_detector_fired"])
    planner_hits = sum(1 for result in results if result["evidence_planner_fired"])
    normalizer_hits = sum(1 for result in results if result["normalization_occurred"])
    local_direct_hits = sum(1 for result in results if str(result["local_direct_used"]).lower() == "true")
    provenance_hits = sum(1 for result in results if result["provenance_preserved"])
    ok_count = sum(1 for result in results if result["rule_ok"])
    anomalies = [result for result in results if not result["rule_ok"]]
    boundary_violations = [result for result in results if result["boundary_violation"]]
    notable_successes = choose_notable_successes(results)
    interesting_edges = choose_interesting_edges(results)
    suggestions = build_suggestions(results)

    lines: List[str] = []
    lines.append("# LOCAL_LUCY_ROUTER_REGRESSION_GATE_REPORT")
    lines.append(f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append(f"Active root: `{ROOT}`")
    lines.append("")
    lines.append("## Gate summary")
    lines.append(f"- profile: `{summary['profile']}`")
    lines.append(f"- gate status: `{summary['gate_status']}`")
    lines.append(f"- prompts tested: {summary['prompts_tested']}")
    lines.append(f"- rule-consistent count: {summary['rule_consistent_count']}")
    lines.append(f"- provenance preserved count: {summary['provenance_preserved_count']}")
    lines.append(f"- anomalies: {summary['anomalies']}")
    lines.append(f"- authority-boundary violations: {summary['authority_boundary_violations']}")
    lines.append(f"- route mismatches: {summary['route_mismatches']}")
    lines.append(f"- manifest failures: {summary['manifest_failures']}")
    lines.append("")
    lines.append("## Artifacts")
    lines.append(f"- prompt corpus: `{corpus_path}`")
    lines.append(f"- results jsonl: `{results_path}`")
    lines.append(f"- case logs root: `{artifacts_dir / 'cases'}`")
    lines.append("")
    lines.append("## Summary statistics")
    lines.append(f"- prompts tested: {total}")
    lines.append(f"- rule-consistent cases: {ok_count}/{total}")
    lines.append(f"- provenance preserved: {provenance_hits}/{total}")
    lines.append(f"- semantic interpreter activation rate: {semantic_hits}/{total} ({(semantic_hits / total * 100):.1f}%)")
    lines.append(f"- medication detector activation rate: {med_hits}/{total} ({(med_hits / total * 100):.1f}%)")
    lines.append(f"- evidence planner activation rate: {planner_hits}/{total} ({(planner_hits / total * 100):.1f}%)")
    lines.append(f"- normalization observed: {normalizer_hits}/{total} ({(normalizer_hits / total * 100):.1f}%)")
    lines.append(f"- LOCAL_DIRECT used: {local_direct_hits}/{total}")
    lines.append("")
    lines.append("Pipeline distribution:")
    for key, count in sorted(pipeline_counts.items()):
        lines.append(f"- {key}: {count}")
    lines.append("")
    lines.append("Response classification distribution:")
    for key, count in sorted(response_counts.items()):
        lines.append(f"- {key}: {count}")
    lines.append("")
    lines.append("## Notable successes")
    if notable_successes:
        for result in notable_successes:
            lines.append(
                f"- [{result['category']}] `{result['prompt']}` -> {result['pipeline']} / {result['response_classification']}"
                f" | semantic={str(result['semantic_interpreter_fired']).lower()}"
                f" medication={str(result['medication_detector_fired']).lower()}"
                f" planner={str(result['evidence_planner_fired']).lower()}"
            )
    else:
        lines.append("- None singled out beyond the overall pass set.")
    lines.append("")
    lines.append("## Potential routing anomalies")
    if anomalies:
        for result in anomalies[:20]:
            reason = "; ".join(result["rule_reasons"]) or "unexpected_behavior"
            lines.append(
                f"- [{result['category']}] `{result['prompt']}` expected={','.join(result['expected_routes']) or 'non-local'}"
                f" actual={result['pipeline'] or 'UNKNOWN'} response={result['response_classification']} reason={reason}"
            )
    else:
        lines.append("- No rule mismatches were detected in this sweep.")
    lines.append("")
    lines.append("## Authority boundary violations")
    if boundary_violations:
        for result in boundary_violations:
            lines.append(
                f"- `{result['prompt']}` routed LOCAL and produced `{result['response_classification']}` even though the case was marked non-local."
            )
    else:
        lines.append("- None detected.")
    lines.append("")
    lines.append("## Interesting edge cases")
    if interesting_edges:
        for result in interesting_edges:
            resolved = result["resolved_execution_query"] or result["prompt"]
            lines.append(
                f"- [{result['category']}] `{result['prompt']}` -> pipeline={result['pipeline']} output_mode={result['output_mode'] or 'unknown'}"
                f" resolved=`{resolved}`"
            )
    else:
        lines.append("- No additional edge cases stood out beyond the anomalies list.")
    lines.append("")
    lines.append("## Suggestions")
    for suggestion in suggestions:
        lines.append(f"- {suggestion}")
    lines.append("")
    lines.append("## Boundary confirmation")
    lines.append("- governor/router remained the owner of routing decisions")
    lines.append("- execution remained policy-blind; the sweep only observed existing behavior")
    lines.append("- evidence/news/doc authority boundaries were preserved unless explicitly listed above")
    lines.append("- original query provenance was checked against structured traces")
    lines.append("")
    text = "\n".join(lines) + "\n"
    desktop_report.write_text(text, encoding="utf-8")
    (artifacts_dir / "report.md").write_text(text, encoding="utf-8")
    return text


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_summary_json(path: Path, summary: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    cases = build_corpus()
    cases = select_cases_for_profile(cases, args.profile)
    if args.category:
        cases = [case for case in cases if case["category"] == args.category]
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        print("ERROR: no cases selected", file=sys.stderr)
        return 2

    ts_file = datetime.now().astimezone().strftime("%Y-%m-%dT%H-%M-%S%z")
    artifacts_dir = Path(args.artifacts_dir) if args.artifacts_dir else (ARTIFACT_ROOT / ts_file)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    workspaces_dir = artifacts_dir / "workspaces"
    workspaces_dir.mkdir(exist_ok=True)
    corpus_path = artifacts_dir / "prompt_corpus.jsonl"
    results_path = artifacts_dir / "results.jsonl"
    summary_path = artifacts_dir / "summary.json"
    report_prefix = (args.report_prefix or DEFAULT_REPORT_PREFIX).strip() or DEFAULT_REPORT_PREFIX
    desktop_report = DESKTOP / f"{report_prefix}_{ts_file}.md"

    write_jsonl(corpus_path, cases)

    sessions: Dict[str, SessionContext] = {}
    results: List[Dict[str, Any]] = []
    for case in cases:
        session_key = case.get("conversation_key") or case["id"]
        session = sessions.get(session_key)
        if session is None:
            session = ensure_workspace(ROOT, workspaces_dir, session_key)
            sessions[session_key] = session
        result = run_case(case, session, artifacts_dir, args.timeout_s)
        result["expected_routes"] = case["expected_routes"]
        write_jsonl(results_path, results + [result])
        results.append(result)

    summary = build_summary(
        results,
        artifacts_dir=artifacts_dir,
        corpus_path=corpus_path,
        results_path=results_path,
        report_path=desktop_report,
        profile=args.profile or "full",
    )
    render_report(results, artifacts_dir, desktop_report, corpus_path, results_path, summary)
    write_summary_json(summary_path, summary)
    print(json.dumps(summary))
    return 1 if args.fail_on_gate and summary["gate_status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
