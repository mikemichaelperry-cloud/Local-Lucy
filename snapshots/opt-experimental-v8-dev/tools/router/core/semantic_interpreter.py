#!/usr/bin/env python3
import json
import os
import re
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


ALLOWED_DOMAINS = {"news", "medical", "travel", "technical", "reference", "general", "unknown"}
ALLOWED_INTENT_FAMILIES = {
    "current_fact",
    "evidence_check",
    "local_knowledge",
    "technical_explanation",
    "url_reference",
    "clarify",
    "unknown",
}
DEFAULT_MODEL = "local-lucy"
DEFAULT_API_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_TIMEOUT_S = 8.0
DEFAULT_BACKEND_FAILURE_TTL_S = 300.0


def _append_latency(stage: str, ms: int, component: str = "semantic_interpreter") -> None:
    if (os.environ.get("LUCY_LATENCY_PROFILE_ACTIVE") or "0") != "1":
        return
    path = (os.environ.get("LUCY_LATENCY_PROFILE_FILE") or "").strip()
    run_id = (os.environ.get("LUCY_LATENCY_RUN_ID") or "").strip()
    if not path or not run_id:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"run={run_id}\tcomponent={component}\tstage={stage}\tms={int(ms)}\n")
    except OSError:
        return


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _state_root() -> Path:
    env_root = (os.environ.get("LUCY_ROOT") or "").strip()
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[3]


def _sanitize_namespace(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    cleaned = cleaned.strip("_")
    if cleaned:
        return cleaned
    if (value or "").strip():
        return "unnamed"
    return ""


def _state_namespace() -> str:
    return _sanitize_namespace(os.environ.get("LUCY_SHARED_STATE_NAMESPACE") or "")


def _backend_state_path() -> Path:
    override = (os.environ.get("LUCY_SEMANTIC_INTERPRETER_STATE_FILE") or "").strip()
    if override:
        return Path(override)
    namespace = _state_namespace()
    if namespace:
        return _state_root() / "state" / "namespaces" / namespace / "semantic_interpreter_backend.json"
    return _state_root() / "state" / "semantic_interpreter_backend.json"


@contextmanager
def _backend_state_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_backend_state() -> Dict[str, Any]:
    path = _backend_state_path()
    with _backend_state_lock(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _write_backend_state(payload: Dict[str, Any]) -> None:
    path = _backend_state_path()
    with _backend_state_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
            tmp_path = Path(handle.name)
        tmp_path.replace(path)


def _clear_backend_unavailable_state() -> None:
    path = _backend_state_path()
    with _backend_state_lock(path):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def _backend_unavailable_cached(url: str, model: str) -> bool:
    ttl_s = _float_env("LUCY_SEMANTIC_INTERPRETER_FAILURE_TTL_S", DEFAULT_BACKEND_FAILURE_TTL_S)
    if ttl_s <= 0:
        return False
    state = _read_backend_state()
    if str(state.get("status") or "") != "unavailable":
        return False
    if str(state.get("url") or "") not in {"", url}:
        return False
    if str(state.get("model") or "") not in {"", model}:
        return False
    try:
        recorded_at = float(state.get("recorded_at") or 0.0)
    except (TypeError, ValueError):
        return False
    return (time.time() - recorded_at) < ttl_s


def _default_trace(question: str) -> Dict[str, Any]:
    normalized = _normalize_space(question)
    return {
        "original_query": normalized,
        "resolved_execution_query": normalized,
        "interpreter_fired": False,
        "inferred_domain": "unknown",
        "inferred_intent_family": "unknown",
        "normalized_candidates": [],
        "retrieval_candidates": [],
        "ambiguity_flag": False,
        "confidence": 0.0,
        "provenance_notes": [],
        "gate_reason": "not_invoked",
        "invocation_attempted": False,
        "result_status": "not_invoked",
        "use_reason": "not_invoked",
        "used_for_routing": False,
        "forward_candidates": False,
        "selected_normalized_query": normalized,
        "selected_retrieval_query": "",
    }


def _candidate_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    cleaned: List[str] = []
    seen = set()
    for raw in values:
        candidate = _normalize_space(str(raw))
        if not candidate:
            continue
        if len(candidate) > 180:
            candidate = candidate[:180].rstrip()
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(candidate)
        if len(cleaned) >= 3:
            break
    return cleaned


def _notes_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    cleaned: List[str] = []
    for raw in values:
        note = _normalize_space(str(raw))
        if not note:
            continue
        if len(note) > 120:
            note = note[:120].rstrip()
        cleaned.append(note)
        if len(cleaned) >= 3:
            break
    return cleaned


def _sanitize_payload(question: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    trace = _default_trace(question)
    domain = str(payload.get("inferred_domain") or "unknown").strip().lower()
    intent_family = str(payload.get("inferred_intent_family") or "unknown").strip().lower()
    try:
        confidence = round(max(0.0, min(1.0, float(payload.get("confidence") or 0.0))), 3)
    except (TypeError, ValueError):
        confidence = 0.0
    trace.update(
        {
            "interpreter_fired": True,
            "inferred_domain": domain if domain in ALLOWED_DOMAINS else "unknown",
            "inferred_intent_family": intent_family if intent_family in ALLOWED_INTENT_FAMILIES else "unknown",
            "normalized_candidates": _candidate_list(payload.get("normalized_candidates")),
            "retrieval_candidates": _candidate_list(payload.get("retrieval_candidates")),
            "ambiguity_flag": bool(payload.get("ambiguity_flag")),
            "confidence": confidence,
            "provenance_notes": _notes_list(payload.get("provenance_notes")),
            "use_reason": "advisory_available",
        }
    )
    if trace["normalized_candidates"]:
        trace["selected_normalized_query"] = trace["normalized_candidates"][0]
    if trace["retrieval_candidates"]:
        trace["selected_retrieval_query"] = trace["retrieval_candidates"][0]
    return trace


def _extract_json_object(text: str) -> Dict[str, Any]:
    stripped = (text or "").strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(stripped[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _load_prompt_template() -> str:
    conf_dir = Path(os.environ.get("LUCY_CONF_DIR") or str(Path(__file__).resolve().parents[3] / "config"))
    template_path = conf_dir / "local_semantic_interpreter_prompt_v1.txt"
    try:
        return template_path.read_text(encoding="utf-8")
    except OSError:
        return (
            "You are Local Lucy's semantic interpreter.\n"
            "Return JSON only.\n"
            "Question: {question}\n"
            "surface={surface}\n"
            "intent_class={intent_class}\n"
            "subcategory={subcategory}\n"
            "confidence={confidence}\n"
            "candidate_routes={candidate_routes}\n"
            "has_url={has_url}\n"
            "has_current_terms={has_current_terms}\n"
            "has_source_terms={has_source_terms}\n"
        )


def _should_invoke(plan: Dict[str, Any]) -> Tuple[bool, str]:
    if not _bool_env("LUCY_SEMANTIC_INTERPRETER_ENABLED", True):
        return False, "disabled"
    if os.environ.get("LUCY_ROUTER_DRYRUN") == "1" and not (
        os.environ.get("LUCY_SEMANTIC_INTERPRETER_FIXTURE")
        or os.environ.get("LUCY_SEMANTIC_INTERPRETER_INLINE_JSON")
    ):
        return False, "dryrun_without_fixture"
    intent_class = str(plan.get("intent_class") or "").strip().lower()
    subcategory = str(plan.get("subcategory") or "").strip().lower()
    try:
        confidence = float(plan.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    tokens = plan.get("tokens") or []
    token_count = len(tokens) if isinstance(tokens, list) else 0
    if intent_class in {"command_control", "identity_personal", "conversational"}:
        return False, "deterministic_nonsemantic"
    if intent_class == "technical_explanation" and confidence >= 0.86:
        return False, "strong_technical_local"
    if intent_class == "evidence_check" and subcategory in {"medical", "url_reference", "primary_doc"} and confidence >= 0.9:
        return False, "strong_high_stakes_deterministic"
    if intent_class == "current_fact" and subcategory.startswith("news") and confidence >= 0.9:
        return False, "strong_news_deterministic"
    if intent_class == "current_fact" and subcategory == "current_fact" and confidence >= 0.82:
        return False, "strong_current_fact_deterministic"
    if intent_class == "mixed":
        return True, "ambiguous_route"
    if intent_class == "local_knowledge" and subcategory == "general" and confidence <= 0.75 and token_count >= 6:
        return True, "weak_general_local"
    if intent_class == "current_fact" and confidence < 0.86:
        return True, "weak_current_fact"
    if intent_class == "evidence_check" and subcategory == "web_lookup" and confidence < 0.9:
        return True, "weak_evidence_lookup"
    return False, "deterministic_sufficient"


def _fixture_payload(question: str) -> Dict[str, Any]:
    start = time.perf_counter()
    fixture_path = (os.environ.get("LUCY_SEMANTIC_INTERPRETER_FIXTURE") or "").strip()
    inline = (os.environ.get("LUCY_SEMANTIC_INTERPRETER_INLINE_JSON") or "").strip()
    payload: Dict[str, Any] = {}
    if fixture_path:
        try:
            payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    elif inline:
        payload = _extract_json_object(inline)
    result = _sanitize_payload(question, payload) if payload else {}
    _append_latency("fixture_lookup", max(1, int(round((time.perf_counter() - start) * 1000))))
    return result


def _build_prompt(question: str, plan: Dict[str, Any]) -> str:
    start = time.perf_counter()
    template = _load_prompt_template()
    replacements = {
        "{question}": _normalize_space(question),
        "{surface}": str(plan.get("surface") or "cli").strip().lower() or "cli",
        "{intent_class}": str(plan.get("intent_class") or "unknown"),
        "{subcategory}": str(plan.get("subcategory") or "general"),
        "{confidence}": str(plan.get("confidence") or 0.0),
        "{candidate_routes}": ",".join(str(item) for item in (plan.get("candidate_routes") or [])),
        "{has_url}": "true" if plan.get("has_url") else "false",
        "{has_current_terms}": "true" if plan.get("has_current_terms") else "false",
        "{has_source_terms}": "true" if plan.get("has_source_terms") else "false",
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    _append_latency("prompt_build", max(1, int(round((time.perf_counter() - start) * 1000))))
    return rendered


def _call_local_model(prompt: str) -> Tuple[Dict[str, Any], str]:
    total_start = time.perf_counter()
    url = os.environ.get("LUCY_OLLAMA_API_URL") or DEFAULT_API_URL
    model = os.environ.get("LUCY_LOCAL_MODEL") or DEFAULT_MODEL
    timeout_s = _float_env("LUCY_SEMANTIC_INTERPRETER_TIMEOUT_S", DEFAULT_TIMEOUT_S)
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": os.environ.get("LUCY_LOCAL_KEEP_ALIVE") or "5m",
        "options": {
            "temperature": 0,
            "top_p": 1,
            "seed": 7,
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    network_start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError):
        _append_latency("model_call", max(1, int(round((time.perf_counter() - network_start) * 1000))))
        _append_latency("total", max(1, int(round((time.perf_counter() - total_start) * 1000))))
        return {}, "transport_error"
    _append_latency("model_call", max(1, int(round((time.perf_counter() - network_start) * 1000))))
    parse_start = time.perf_counter()
    payload = _extract_json_object(raw)
    if payload:
        _append_latency("response_parse", max(1, int(round((time.perf_counter() - parse_start) * 1000))))
        _append_latency("total", max(1, int(round((time.perf_counter() - total_start) * 1000))))
        return payload, "ok"
    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        _append_latency("response_parse", max(1, int(round((time.perf_counter() - parse_start) * 1000))))
        _append_latency("total", max(1, int(round((time.perf_counter() - total_start) * 1000))))
        return {}, "empty_payload"
    response_text = outer.get("response") if isinstance(outer, dict) else ""
    extracted = _extract_json_object(str(response_text))
    if extracted:
        _append_latency("response_parse", max(1, int(round((time.perf_counter() - parse_start) * 1000))))
        _append_latency("total", max(1, int(round((time.perf_counter() - total_start) * 1000))))
        return extracted, "ok"
    _append_latency("response_parse", max(1, int(round((time.perf_counter() - parse_start) * 1000))))
    _append_latency("total", max(1, int(round((time.perf_counter() - total_start) * 1000))))
    return {}, "empty_payload"


def maybe_interpret_question(question: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    total_start = time.perf_counter()
    trace = _default_trace(question)
    gate_start = time.perf_counter()
    should_invoke, reason = _should_invoke(plan)
    _append_latency("gate", max(1, int(round((time.perf_counter() - gate_start) * 1000))))
    trace["gate_reason"] = reason
    trace["use_reason"] = reason
    if not should_invoke:
        trace["result_status"] = "skipped"
        _append_latency("maybe_total", max(1, int(round((time.perf_counter() - total_start) * 1000))))
        return trace

    fixture = _fixture_payload(question)
    if fixture:
        fixture["gate_reason"] = reason
        fixture["invocation_attempted"] = False
        fixture["result_status"] = "fixture_payload"
        fixture["use_reason"] = reason
        _append_latency("maybe_total", max(1, int(round((time.perf_counter() - total_start) * 1000))))
        return fixture

    url = os.environ.get("LUCY_OLLAMA_API_URL") or DEFAULT_API_URL
    model = os.environ.get("LUCY_LOCAL_MODEL") or DEFAULT_MODEL
    cache_start = time.perf_counter()
    if _backend_unavailable_cached(url, model):
        _append_latency("backend_cache_check", max(1, int(round((time.perf_counter() - cache_start) * 1000))))
        trace["use_reason"] = "backend_unavailable_cached"
        trace["result_status"] = "backend_unavailable_cached"
        _append_latency("maybe_total", max(1, int(round((time.perf_counter() - total_start) * 1000))))
        return trace
    _append_latency("backend_cache_check", max(1, int(round((time.perf_counter() - cache_start) * 1000))))

    trace["invocation_attempted"] = True
    prompt = _build_prompt(question, plan)
    payload, call_status = _call_local_model(prompt)
    if not payload:
        trace["use_reason"] = "model_unavailable"
        trace["result_status"] = "model_unavailable" if call_status == "transport_error" else call_status
        if call_status == "transport_error":
            _write_backend_state(
                {
                    "status": "unavailable",
                    "recorded_at": round(time.time(), 3),
                    "url": url,
                    "model": model,
                }
            )
        _append_latency("maybe_total", max(1, int(round((time.perf_counter() - total_start) * 1000))))
        return trace
    clear_start = time.perf_counter()
    _clear_backend_unavailable_state()
    _append_latency("backend_cache_clear", max(1, int(round((time.perf_counter() - clear_start) * 1000))))
    sanitize_start = time.perf_counter()
    interpreted = _sanitize_payload(question, payload)
    _append_latency("sanitize_payload", max(1, int(round((time.perf_counter() - sanitize_start) * 1000))))
    interpreted["gate_reason"] = reason
    interpreted["invocation_attempted"] = True
    interpreted["result_status"] = "advisory_available"
    interpreted["use_reason"] = reason
    _append_latency("maybe_total", max(1, int(round((time.perf_counter() - total_start) * 1000))))
    return interpreted
