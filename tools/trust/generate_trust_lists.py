#!/usr/bin/env python3
"""Generate deterministic trust allowlists from trust catalog + policy."""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Dict, List, Tuple


DOMAIN_RE = re.compile(r"^[a-z0-9.-]+$")
ALLOWED_TIERS = {1, 2, 3}
ALLOWED_PROBE_EXPECTATIONS = {"strict", "reachable", "connect_only"}
MIN_CATEGORIES = {
    "news_israel",
    "news_world",
    "policy_global",
    "geopolitics",
    "engineering",
    "electronics",
    "ai",
    "medical",
    "finance",
    "vet",
}


def fail(msg: str) -> None:
    print(f"ERR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def detect_root() -> str:
    env_root = os.environ.get("LUCY_ROOT", "").strip()
    if env_root:
        root = env_root
        if not os.path.isdir(root):
            fail(f"LUCY_ROOT does not exist: {root}")
        if not (
            os.path.isfile(os.path.join(root, "lucy_chat.sh"))
            or os.path.isdir(os.path.join(root, "tools"))
            or os.path.isdir(os.path.join(root, "snapshots"))
        ):
            fail(f"LUCY_ROOT failed marker check: {root}")
        return root
    script_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if (
        os.path.isdir(script_root)
        and (
            os.path.isfile(os.path.join(script_root, "lucy_chat.sh"))
            or os.path.isdir(os.path.join(script_root, "tools"))
            or os.path.isdir(os.path.join(script_root, "snapshots"))
        )
    ):
        return script_root
    home = os.path.expanduser("~")
    fallback = os.path.join(home, "lucy")
    if os.path.isdir(fallback):
        root = fallback
    else:
        fail("could not determine ROOT: neither active script root nor ~/lucy exists")
    if not (
        os.path.isfile(os.path.join(root, "lucy_chat.sh"))
        or os.path.isdir(os.path.join(root, "tools"))
        or os.path.isdir(os.path.join(root, "snapshots"))
    ):
        fail(f"ROOT failed marker check: {root}")
    return root


def _parse_scalar(raw: str):
    s = raw.strip()
    if not s:
        return ""
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s in ("true", "false"):
        return s == "true"
    if s.isdigit():
        return int(s)
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        out = []
        for p in inner.split(","):
            item = p.strip()
            if item.startswith('"') and item.endswith('"'):
                item = item[1:-1]
            out.append(item)
        return out
    return s


def load_catalog_yaml(path: str) -> Dict[str, Dict]:
    version = None
    in_domains = False
    current_domain = None
    domains: Dict[str, Dict] = {}

    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, 1):
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(line) - len(line.lstrip(" "))

            if indent == 0 and stripped.startswith("version:"):
                version = _parse_scalar(stripped.split(":", 1)[1])
                continue
            if indent == 0 and stripped == "domains:":
                in_domains = True
                continue
            if not in_domains:
                fail(f"{path}:{lineno}: unexpected content before domains block")

            if indent == 2 and stripped.endswith(":"):
                current_domain = stripped[:-1].strip()
                if current_domain in domains:
                    fail(f"{path}:{lineno}: duplicate domain key: {current_domain}")
                domains[current_domain] = {}
                continue

            if indent == 4 and ":" in stripped and current_domain:
                k, v = stripped.split(":", 1)
                key = k.strip()
                value = _parse_scalar(v)
                domains[current_domain][key] = value
                continue

            fail(f"{path}:{lineno}: unsupported YAML shape")

    if version != 1:
        fail(f"{path}: version must be 1")
    if not domains:
        fail(f"{path}: domains block is empty")
    return domains


def load_policy_yaml(path: str) -> Dict:
    data: Dict[str, object] = {}
    current_list_key = None
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, 1):
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent == 0 and ":" in stripped:
                k, v = stripped.split(":", 1)
                key = k.strip()
                rhs = v.strip()
                if rhs == "":
                    data[key] = []
                    current_list_key = key
                else:
                    data[key] = _parse_scalar(v)
                    current_list_key = None
                continue
            if indent >= 2 and stripped.startswith("- ") and current_list_key:
                data.setdefault(current_list_key, []).append(_parse_scalar(stripped[1:]))
                continue
            fail(f"{path}:{lineno}: unsupported policy YAML shape")
    return data


def validate_catalog(domains: Dict[str, Dict]) -> None:
    seen_categories = set()
    for domain, meta in domains.items():
        if domain != domain.lower():
            fail(f"domain must be lowercase: {domain}")
        if "://" in domain:
            fail(f"domain must not include scheme: {domain}")
        if "/" in domain:
            fail(f"domain must not include path: {domain}")
        if not DOMAIN_RE.match(domain):
            fail(f"domain contains invalid characters: {domain}")

        tier = meta.get("tier")
        if tier not in ALLOWED_TIERS:
            fail(f"{domain}: tier must be one of 1,2,3")

        categories = meta.get("categories")
        if not isinstance(categories, list) or not categories or not all(
            isinstance(c, str) and c for c in categories
        ):
            fail(f"{domain}: categories must be a non-empty list of strings")
        seen_categories.update(categories)

        req = meta.get("requires_corroboration")
        if tier == 3:
            if req is not True:
                fail(f"{domain}: tier 3 must set requires_corroboration: true")
        elif req is not None and not isinstance(req, bool):
            fail(f"{domain}: requires_corroboration must be boolean when present")

        probe_paths = meta.get("probe_paths")
        if probe_paths is not None:
            if not isinstance(probe_paths, list) or not all(
                isinstance(p, str) and p.startswith("/") for p in probe_paths
            ):
                fail(f"{domain}: probe_paths must be a list of absolute paths")

        probe_expectation = meta.get("probe_expectation")
        if probe_expectation is not None:
            if not isinstance(probe_expectation, str) or probe_expectation not in ALLOWED_PROBE_EXPECTATIONS:
                fail(
                    f"{domain}: probe_expectation must be one of "
                    + ", ".join(sorted(ALLOWED_PROBE_EXPECTATIONS))
                )

        unstable = meta.get("unstable")
        if unstable is not None and not isinstance(unstable, bool):
            fail(f"{domain}: unstable must be boolean when present")

        probe_host = meta.get("probe_host")
        if probe_host is not None:
            if not isinstance(probe_host, str) or not probe_host:
                fail(f"{domain}: probe_host must be a non-empty string when present")
            if probe_host != probe_host.lower():
                fail(f"{domain}: probe_host must be lowercase")
            if "://" in probe_host or "/" in probe_host or not DOMAIN_RE.match(probe_host):
                fail(f"{domain}: probe_host must be a hostname without scheme/path")

        allowed_paths = meta.get("allowed_paths")
        if allowed_paths is not None:
            if not isinstance(allowed_paths, list) or not all(
                isinstance(p, str) and p.startswith("/") for p in allowed_paths
            ):
                fail(f"{domain}: allowed_paths must be a list of absolute paths")

    missing = sorted(MIN_CATEGORIES - seen_categories)
    if missing:
        fail("catalog missing minimum categories: " + ", ".join(missing))


def validate_policy(policy: Dict) -> List[int]:
    if policy.get("version") != 1:
        fail("policy version must be 1")
    tiers = policy.get("fetch_allow_tiers")
    if not isinstance(tiers, list) or not tiers:
        fail("policy fetch_allow_tiers must be a non-empty list")
    out: List[int] = []
    for t in tiers:
        if isinstance(t, int):
            tier = t
        elif isinstance(t, str) and t.isdigit():
            tier = int(t)
        else:
            fail("policy fetch_allow_tiers must contain only 1,2,3")
        if tier not in ALLOWED_TIERS:
            fail("policy fetch_allow_tiers must contain only 1,2,3")
        out.append(tier)
    if len(set(out)) != len(out):
        fail("policy fetch_allow_tiers contains duplicates")
    min_src = policy.get("evidence_min_sources_high_stakes")
    if not isinstance(min_src, int) or min_src < 1:
        fail("policy evidence_min_sources_high_stakes must be integer >= 1")
    return out


def render_outputs(domains: Dict[str, Dict], fetch_allow_tiers: List[int]) -> Dict[str, str]:
    outputs: Dict[str, str] = {}
    fetch_tiers = set(fetch_allow_tiers)

    def with_www_variant(vals: set[str]) -> List[str]:
        expanded: set[str] = set()
        for v in vals:
            s = str(v).strip().lower()
            if not s:
                continue
            s = s.rstrip(".")
            expanded.add(s)
            if not s.startswith("www."):
                expanded.add(f"www.{s}")
        return sorted(expanded)

    def make(name: str, matcher) -> None:
        vals = with_www_variant({d for d, meta in domains.items() if matcher(meta)})
        outputs[name] = "\n".join(vals) + "\n"

    def make_runtime(name: str, matcher) -> None:
        vals = with_www_variant(
            {
                d
                for d, meta in domains.items()
                if matcher(meta) and int(meta["tier"]) in fetch_tiers
            }
        )
        outputs[name] = "\n".join(vals) + "\n"

    make("allowlist_tier1.txt", lambda d: d["tier"] == 1)
    make("allowlist_tier2.txt", lambda d: d["tier"] == 2)
    make("allowlist_tier3.txt", lambda d: d["tier"] == 3)
    make("allowlist_all_tier12.txt", lambda d: d["tier"] in (1, 2))
    make("allowlist_all.txt", lambda d: d["tier"] in (1, 2, 3))
    make("allowlist_fetch.txt", lambda d: d["tier"] in fetch_tiers)

    make("news_israel.txt", lambda d: "news_israel" in d["categories"])
    make("news_world.txt", lambda d: "news_world" in d["categories"])
    make("policy_global.txt", lambda d: "policy_global" in d["categories"])
    make(
        "engineering.txt",
        lambda d: "engineering" in d["categories"] or "electronics" in d["categories"],
    )
    make("medical.txt", lambda d: "medical" in d["categories"])
    make("finance.txt", lambda d: "finance" in d["categories"])
    make("vet.txt", lambda d: "vet" in d["categories"])
    make("ai.txt", lambda d: "ai" in d["categories"])

    # Runtime-effective category lists (clarity): same categories, but filtered to
    # fetch-allowed tiers so router allowlists match what fetch/search can use.
    make_runtime("news_israel_runtime.txt", lambda d: "news_israel" in d["categories"])
    make_runtime("news_world_runtime.txt", lambda d: "news_world" in d["categories"])
    make_runtime("policy_global_runtime.txt", lambda d: "policy_global" in d["categories"])
    make_runtime(
        "engineering_runtime.txt",
        lambda d: "engineering" in d["categories"] or "electronics" in d["categories"],
    )
    make_runtime("medical_runtime.txt", lambda d: "medical" in d["categories"])
    make_runtime("finance_runtime.txt", lambda d: "finance" in d["categories"])
    make_runtime("vet_runtime.txt", lambda d: "vet" in d["categories"])
    make_runtime("ai_runtime.txt", lambda d: "ai" in d["categories"])

    return outputs


def render_stable_legacy_outputs(domains: Dict[str, Dict]) -> Dict[str, str]:
    outputs: Dict[str, str] = {}
    tier12 = sorted({d for d, meta in domains.items() if meta.get("tier") in (1, 2)})
    td_lines = [
        "version: 1",
        "https_only: true",
        "exact:",
    ]
    td_lines.extend([f"  - {d}" for d in tier12])
    td_lines.extend(["subdomains: []", "ports:", "  - 443", ""])
    outputs["../../trusted_domains.yaml"] = "\n".join(td_lines)

    rows = [
        "# GENERATED FILE - DO NOT EDIT",
        "# source of truth: config/trust/trust_catalog.yaml",
        "# tier\tcategory\tsource\tnotes",
    ]
    for domain in sorted(domains.keys()):
        meta = domains[domain]
        tier = f"TIER{int(meta.get('tier', 2))}"
        cats = meta.get("categories") or ["news_world"]
        notes = str(meta.get("notes", "")).replace("\t", " ").strip()
        for cat in sorted({str(c).strip() for c in cats if str(c).strip()}):
            rows.append(f"{tier}\t{cat}\t{domain}\t{notes}")
    rows.append("")
    outputs["../../trusted_sources_catalog.tsv"] = "\n".join(rows)

    readme = (
        "# Trusted Sources Catalog (Generated)\n\n"
        "This file is generated from `config/trust/trust_catalog.yaml`.\n"
        "Do not edit `config/trusted_sources_catalog.tsv` manually.\n"
        "Run `python3 tools/trust/generate_trust_lists.py` and `tools/trust/verify_trust_lists.sh`.\n"
    )
    outputs["../../trusted_sources_catalog.README.md"] = readme
    return outputs


def write_outputs(out_dir: str, outputs: Dict[str, str]) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for fname in sorted(outputs.keys()):
        path = os.path.normpath(os.path.join(out_dir, fname))
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(outputs[fname])


def check_outputs(out_dir: str, outputs: Dict[str, str]) -> None:
    mismatches: List[str] = []
    for fname in sorted(outputs.keys()):
        path = os.path.normpath(os.path.join(out_dir, fname))
        expected = outputs[fname]
        try:
            with open(path, "r", encoding="utf-8") as f:
                current = f.read()
        except FileNotFoundError:
            mismatches.append(f"{fname} (missing)")
            continue
        if current != expected:
            mismatches.append(fname)
    if mismatches:
        fail("generated files not up to date: " + ", ".join(mismatches))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if generated files differ")
    args = ap.parse_args()

    root = detect_root()
    catalog = os.path.join(root, "config", "trust", "trust_catalog.yaml")
    policy_path = os.path.join(root, "config", "trust", "policy.yaml")
    out_dir = os.path.join(root, "config", "trust", "generated")
    if not os.path.isfile(catalog):
        fail(f"missing trust catalog: {catalog}")
    if not os.path.isfile(policy_path):
        fail(f"missing trust policy: {policy_path}")

    domains = load_catalog_yaml(catalog)
    validate_catalog(domains)
    policy = load_policy_yaml(policy_path)
    fetch_allow_tiers = validate_policy(policy)
    outputs = render_outputs(domains, fetch_allow_tiers)
    if os.path.exists(os.path.join(root, "config", "trusted_sources_catalog.tsv")):
        outputs.update(render_stable_legacy_outputs(domains))

    if args.check:
        check_outputs(out_dir, outputs)
    else:
        write_outputs(out_dir, outputs)
        print(f"OK: wrote {len(outputs)} generated trust lists to {out_dir}")


if __name__ == "__main__":
    main()
