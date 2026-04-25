#!/usr/bin/env python3
import json
import re
import sys


def clean(s: str) -> str:
    s = s.replace("\r", "")
    return "\n".join([ln.rstrip() for ln in s.splitlines()])


def parse(text: str):
    raw = clean(text)
    lines = raw.splitlines()
    out = {
        "parse_ok": False,
        "answer": "",
        "sources": [],
        "claims": [],
        "raw": raw,
    }

    try:
        if not lines:
            return out
        begin = next((i for i, ln in enumerate(lines) if ln.strip() == "BEGIN_VALIDATED"), None)
        end = next((i for i, ln in enumerate(lines) if ln.strip() == "END_VALIDATED"), None)
        if begin is None or end is None or end <= begin:
            return out

        body = lines[begin + 1 : end]
        answer_parts = []
        claims = []
        sources = []
        answer_started = False

        def add_sources_blob(blob: str):
            parts = [p.strip() for p in re.split(r"[,;]", blob or "") if p.strip()]
            for p in parts:
                d = re.sub(r"^https?://", "", p, flags=re.I).split("/")[0].lower()
                d = d[4:] if d.startswith("www.") else d
                sources.append({"domain": d or p, "url": p if p.startswith("http") else ""})

        for ln in body:
            s = ln.strip()
            if not s:
                continue

            if s in {"Evidence:", "[MEMORY PROPOSAL]", "---- BEGIN PROPOSAL ----"}:
                break

            if answer_started and re.match(r"^(type|subject|confidence):", s, flags=re.I):
                break

            if s.lower().startswith("sources:"):
                rest = s.split(":", 1)[1].strip()
                if rest:
                    add_sources_blob(rest)
                continue

            if " sources:" in s.lower():
                pre, post = re.split(r"\b[Ss]ources:\s*", s, maxsplit=1)
                s = pre.strip()
                if post.strip():
                    add_sources_blob(post.strip())

            if re.match(r"^-\s+", s):
                claims.append(re.sub(r"^-\s+", "", s))
                continue

            if s.lower().startswith("summary:"):
                answer_parts.append(s.split(":", 1)[1].strip())
                answer_started = True
                continue

            if s.lower().startswith("answer:"):
                answer_parts.append(s.split(":", 1)[1].strip())
                answer_started = True
                continue

            if re.match(r"^https?://", s):
                d = re.sub(r"^https?://", "", s, flags=re.I).split("/")[0].lower()
                d = d[4:] if d.startswith("www.") else d
                sources.append({"domain": d or s, "url": s})
                continue

            if s.startswith("ERROR:") or s.startswith("WARN:"):
                continue

            answer_parts.append(s)
            answer_started = True

        if not answer_parts and claims:
            answer_parts.append(claims[0])

        dedup = []
        seen = set()
        for src in sources:
            key = (src.get("domain", ""), src.get("url", ""))
            if key in seen:
                continue
            seen.add(key)
            dedup.append(src)

        out.update(
            {
                "parse_ok": True,
                "answer": " ".join([p for p in answer_parts if p]).strip(),
                "sources": dedup,
                "claims": claims,
            }
        )
        return out
    except Exception:
        return out


def main():
    text = sys.stdin.read()
    print(json.dumps(parse(text), separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
