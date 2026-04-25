#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from pathlib import Path

CITE_RE = re.compile(r"\[src:([a-z0-9\.\-]+)\s+sha:([0-9a-f]{64})\]", re.IGNORECASE)

def die(msg: str, code: int = 2) -> None:
    print(f"ERR: {msg}")
    raise SystemExit(code)

def load_meta_index(evidence_root: Path) -> dict:
    """
    Build a deterministic index:
      sha256 -> set(domains)
    from evidence/cache/by_url/*/meta.json.
    """
    by_url = evidence_root / "cache" / "by_url"
    if not by_url.is_dir():
        die("evidence cache missing (cache/by_url)")

    idx: dict[str, set[str]] = {}
    # Deterministic order
    for entry in sorted(by_url.iterdir(), key=lambda p: p.name):
        meta = entry / "meta.json"
        if not meta.is_file():
            continue
        try:
            j = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        sha = (j.get("sha256") or "").strip().lower()
        dom = (j.get("domain") or "").strip().lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            continue
        if not dom:
            continue
        idx.setdefault(sha, set()).add(dom)
    return idx

def split_paragraphs(text: str) -> list[str]:
    # Paragraphs separated by one or more blank lines
    parts = re.split(r"\n\s*\n", text.strip(), flags=re.MULTILINE)
    return [p.strip() for p in parts if p.strip()]

def is_text_paragraph(p: str) -> bool:
    # Ignore pure markdown dividers/headings if they have no real words.
    # If paragraph contains at least one alnum, treat as text that must be cited.
    return bool(re.search(r"[A-Za-z0-9]", p))


def policy_bounded_validation_allowed(text: str) -> bool:
    profile = os.environ.get("LUCY_POLICY_VALIDATION_PROFILE", "").strip()
    if profile != "policy_global_recent":
        return False
    if os.environ.get("LUCY_POLICY_VALIDATION_ALLOW_BOUNDED", "0").strip() not in {"1", "true", "TRUE"}:
        return False
    shape = os.environ.get("LUCY_POLICY_VALIDATION_SHAPE", "").strip()
    if shape not in {"single_ai", "single_climate", "compound_climate_ai"}:
        return False
    try:
        unique_domains = int(os.environ.get("LUCY_POLICY_VALIDATION_UNIQUE_DOMAINS", "0") or "0")
    except Exception:
        unique_domains = 0
    need_domains = 4 if shape == "compound_climate_ai" else 2
    if unique_domains < need_domains:
        return False

    low = text.lower()
    if "insufficient evidence from trusted sources" in low:
        return False
    if "summary:" not in low:
        return False
    if "sources:" not in low:
        return False
    if "based on current trusted sources" not in low and "current trusted sources" not in low:
        return False
    if re.search(r"\b(definitively|certainly|guaranteed?)\b", low):
        return False
    return True

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["single", "news"], default="single",
                    help="single=1 domain acceptable; news=2 independent domains required")
    ap.add_argument("--evidence-root", default=str(Path.home() / "lucy" / "evidence"))
    ap.add_argument("--min-domains", type=int, default=None,
                    help="override domain requirement (optional)")
    args = ap.parse_args()

    evidence_root = Path(args.evidence_root)
    idx = load_meta_index(evidence_root)

    text = sys.stdin.read()
    if not text.strip():
        die("empty answer", 10)

    if policy_bounded_validation_allowed(text):
        print("OK")
        return 0

    paragraphs = split_paragraphs(text)
    if not paragraphs:
        die("no paragraphs", 11)

    # Collect citations and validate paragraph coverage
    all_domains: set[str] = set()
    all_shas: set[str] = set()

    for i, p in enumerate(paragraphs, start=1):
        if not is_text_paragraph(p):
            continue

        cites = CITE_RE.findall(p)
        if not cites:
            die(f"missing citation in paragraph {i}", 20)

        for dom, sha in cites:
            dom_l = dom.strip().lower()
            sha_l = sha.strip().lower()

            # Must exist in evidence index
            if sha_l not in idx:
                die(f"unknown sha256 cited: {sha_l}", 21)

            # Domain must match one of the cached domains for that sha
            if dom_l not in idx[sha_l]:
                die(f"domain mismatch for sha {sha_l} (got {dom_l})", 22)

            all_domains.add(dom_l)
            all_shas.add(sha_l)

    if not all_shas:
        die("no citations found", 23)

    # Domain requirement
    if args.min_domains is not None:
        need_domains = int(args.min_domains)
    else:
        need_domains = 2 if args.mode == "news" else 1

    if len(all_domains) < need_domains:
        die(f"insufficient independent domains (have {len(all_domains)}, need {need_domains})", 24)

    print("OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
