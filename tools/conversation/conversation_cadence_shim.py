#!/usr/bin/env python3
import hashlib
import json
import os
import re
import sys
from pathlib import Path

BANNED_OPENERS = [
    "sure",
    "great question",
    "happy to help",
    "let me know if",
    "if you need anything else",
    "i'm here to provide information and support",
]

BANNED_CLOSERS = [
    "let me know if you want",
    "let me know if you'd like",
    "hope that helps",
    "anything else",
    "if you need anything else",
]

THERAPY_SENTENCE_DROP_PATTERNS = [
    r"^would you like to\b",
    r"^how does that make you feel\b",
]

PROFANITY = ["idiot", "idiots", "stupid", "dumb", "moron", "morons"]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _read_profile() -> dict:
    defaults = {
        "style": "calibrated_sharp",
        "hedge_reduction": True,
        "therapy_language_filter": True,
        "force_conclusion": True,
        "min_specificity": True,
        "max_balance_sentences": 1,
        "contrarian_probability": 0.4,
    }
    root = Path(__file__).resolve().parent.parent.parent
    profile_file = root / "config" / "conversation_profile.json"
    try:
        data = json.loads(profile_file.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    if not isinstance(data, dict):
        return defaults
    merged = dict(defaults)
    merged.update(data)
    return merged


def _strip_banned_line_start(line: str) -> str:
    s = line.lstrip()
    lowered = s.lower()
    for phrase in BANNED_OPENERS:
        if lowered.startswith(phrase):
            s = s[len(phrase) :]
            s = re.sub(r"^[\s,.:;!\-]+", "", s)
            return s
    return line


def _remove_banned_openers(text: str) -> str:
    lines = text.splitlines()
    non_empty = [i for i, ln in enumerate(lines) if ln.strip()]
    for idx in non_empty[:2]:
        lines[idx] = _strip_banned_line_start(lines[idx])
    return "\n".join(lines)


def _is_banned_closer_line(line: str) -> bool:
    s = line.strip().lower()
    if not s:
        return False
    for phrase in BANNED_CLOSERS:
        if s.startswith(phrase):
            return True
    return False


def _remove_banned_closers(text: str) -> str:
    lines = text.splitlines()
    while True:
        non_empty = [i for i, ln in enumerate(lines) if ln.strip()]
        if not non_empty:
            break
        last = non_empty[-1]
        if _is_banned_closer_line(lines[last]):
            del lines[last]
            continue
        break
    return "\n".join(lines)


def _collapse_bullets_to_paragraph(text: str) -> str:
    parts = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        s = re.sub(r"^[-*]\s+", "", s)
        s = re.sub(r"^\d+[\.)]\s+", "", s)
        parts.append(s)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _split_sentences(text: str):
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s:
        return []
    parts = re.split(r"(?<=[.!?])\s+", s)
    return [p.strip() for p in parts if p.strip()]


def _join_sentences(sentences):
    return " ".join([s.strip() for s in sentences if s.strip()]).strip()


def _apply_therapy_filter_sentence(sent: str) -> str:
    s = sent.strip()
    low = s.lower().replace("’", "'")

    if re.search(r"^it sounds like\b", low):
        s = re.sub(r"(?i)^it sounds like\s+", "", s).strip()
    if re.search(r"^it seems like\b", low):
        s = re.sub(r"(?i)^it seems like\s+", "", s).strip()
    if re.search(r"^consider taking a step\b", low):
        s = re.sub(r"(?i)^consider taking a step\s*", "Take a step ", s).strip()
    if re.search(r"^you might want to explore\b", low):
        s = re.sub(r"(?i)^you might want to explore\s*", "Explore ", s).strip()
    if re.search(r"^it(?:'|’)s important to acknowledge\b", low):
        s = re.sub(r"(?i)^it(?:'|’)s important to acknowledge\s*", "Acknowledge ", s).strip()
    if re.search(r"^it(?:'|’)s valid to feel\b", low):
        s = re.sub(r"(?i)^it(?:'|’)s valid to feel\s*", "You feel ", s).strip()

    low2 = s.lower().replace("’", "'")
    for pat in THERAPY_SENTENCE_DROP_PATTERNS:
        if re.search(pat, low2):
            return ""

    s = re.sub(r"\s+", " ", s).strip()
    if s and not re.search(r"[.!?]$", s):
        s += "."
    return s


def _apply_therapy_filter(text: str) -> str:
    out = []
    for sent in _split_sentences(text):
        fixed = _apply_therapy_filter_sentence(sent)
        if fixed:
            out.append(fixed)
    return _join_sentences(out)


def _limit_hedges(text: str, max_hedges: int = 1) -> str:
    if max_hedges < 0:
        max_hedges = 0
    replacements = [
        (r"\bcan be\b", "is"),
        (r"\bmay\b", "can"),
        (r"\bmight\b", "can"),
        (r"\boften\b", ""),
        (r"\bsometimes\b", ""),
        (r"\bin some cases\b", "under specific conditions"),
        (r"\bit depends\b", "the outcome depends on conditions"),
    ]
    counter = {"count": 0}

    def _repl_factory(rep: str):
        def _repl(match):
            counter["count"] += 1
            if counter["count"] <= max_hedges:
                return match.group(0)
            return rep

        return _repl

    out = text
    for pat, rep in replacements:
        out = re.sub(pat, _repl_factory(rep), out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip()
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    return out


def _is_broad_emotional_prompt(prompt: str) -> bool:
    p = (prompt or "").lower()
    return bool(
        re.search(r"\b(people are idiots|everyone is|nobody|always|never|annoyed|furious|hate people|people are stupid)\b", p)
    )


def _deterministic_pick(prompt: str, probability: float) -> bool:
    try:
        p = float(probability)
    except Exception:
        p = 0.0
    p = max(0.0, min(1.0, p))
    if p <= 0.0:
        return False
    if p >= 1.0:
        return True
    digest = hashlib.sha256((prompt or "").encode("utf-8", errors="ignore")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return bucket < int(round(p * 100.0))


def _apply_contrarian_layer(text: str, prompt: str, probability: float) -> str:
    if not _is_broad_emotional_prompt(prompt):
        return text
    if not _deterministic_pick(prompt, probability):
        return text
    mechanism = "Usually this points to misaligned incentives or unclear constraints, not raw intelligence."
    alt = "A better read is to ask which rule, pressure, or reward is driving the behavior."
    sents = _split_sentences(text)
    if not sents:
        return f"{mechanism} {alt}".strip()
    if any("incentive" in s.lower() or "constraint" in s.lower() for s in sents):
        return text
    return _join_sentences([sents[0], mechanism, alt] + sents[1:])


def _has_conclusion(text: str) -> bool:
    sents = _split_sentences(text)
    if not sents:
        return False
    tail = sents[-1].lower()
    markers = ["bottom line", "so", "therefore", "the takeaway", "you should", "focus on", "do this"]
    if any(m in tail for m in markers):
        return True
    return bool(re.search(r"\b(should|matters|requires|works best|focus on)\b", tail))


def _ensure_conclusion(text: str) -> str:
    if _has_conclusion(text):
        return text
    return _join_sentences(_split_sentences(text) + ["Bottom line: choose one clear action and execute it this week."])


def _has_concrete_example(text: str) -> bool:
    t = (text or "").lower()
    if re.search(r"\b\d+\b", t):
        return True
    if re.search(r"\b(for example|example:|for instance|when\s+\w+|if\s+\w+)\b", t):
        return True
    if re.search(r"\b(deadline|meeting|budget|week|month|team|project|task)\b", t):
        return True
    return False


def _ensure_concrete_example(text: str) -> str:
    if _has_concrete_example(text):
        return text
    example = "Example: when priorities are vague, teams revisit the same decision and lose a full day of execution."
    return _join_sentences(_split_sentences(text) + [example])


def _is_direct_yes_no(text: str) -> bool:
    first = (_split_sentences(text) or [""])[0].lower().strip()
    return bool(re.match(r"^(yes|no)[.!?]?$", first))


def _enforce_substance_floor(text: str) -> str:
    sents = _split_sentences(text)
    if not sents or _is_direct_yes_no(text) or len(sents) >= 3:
        return text
    if len(sents) == 1:
        sents.append("Mechanism: clarity on criteria reduces second-guessing and prevents decision loops.")
        sents.append("Consequence: without that clarity, stress rises and execution slows.")
    elif len(sents) == 2:
        sents.append("Consequence: if you skip this step, you keep revisiting the same choice.")
    return _join_sentences(sents)


def _reduce_balance_structure(text: str, max_balance_sentences: int) -> str:
    sents = _split_sentences(text)
    if not sents:
        return text
    max_balance_sentences = max(0, int(max_balance_sentences))
    kept = []
    balance_count = 0
    for s in sents:
        low = s.lower()
        is_balance = bool(re.search(r"\b(on the one hand|on the other hand|however|alternatively|conversely)\b", low))
        if is_balance:
            balance_count += 1
            if balance_count > max_balance_sentences:
                continue
        kept.append(s)
    return _join_sentences(kept)


def _soften_aggressive_language(text: str) -> str:
    out = text
    for word in PROFANITY:
        out = re.sub(rf"\b{re.escape(word)}\b", "misaligned", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _truncate_clean(text: str, max_chars: int) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars]
    sentence_end = [m.end() for m in re.finditer(r"[.!?](?:\s|$)", cut)]
    if sentence_end:
        return cut[: sentence_end[-1]].rstrip()
    return cut.rstrip()


def _normalize_spacing(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _apply_growth_guard(original: str, transformed: str) -> str:
    orig_len = len((original or "").strip())
    out = (transformed or "").strip()
    if orig_len < 120:
        return out
    max_len = int(orig_len * 1.25)
    if len(out) <= max_len:
        return out
    return _truncate_clean(out, max_len)


def _is_dismissal_prompt(prompt: str) -> bool:
    p = (prompt or "").strip().lower()
    return re.search(r"^(not necessary|no thanks|never mind)[.!?]?$", p) is not None


def _is_short_phatic_prompt(prompt: str) -> bool:
    p = re.sub(r"\s+", " ", (prompt or "").strip().lower())
    if not p:
        return False
    if re.search(r"^(hmm+|hm+|uh+h*|uh-?huh|huh+|ok|okay|k|right|sure|thanks|thank you|cool|nice|interesting|weird|ugh|meh)[.!?]*$", p):
        return True
    if re.search(r"^(consider my last question|consider my las question|last question)[.!?]*$", p):
        return True
    if _word_count(p) <= 4 and re.search(r"\b(my dog|my dogs name|my dog's name)\b", p):
        return True
    return False


def _is_coaching_prompt(prompt: str) -> bool:
    p = re.sub(r"\s+", " ", (prompt or "").strip().lower())
    if not p:
        return False
    coaching_patterns = [
        r"\boverthink(ing)?\b",
        r"\bdiscipline\b",
        r"\bannoyed\b",
        r"\bpeople are idiots\b",
        r"\bshould i invest\b",
        r"\bambition\b",
        r"\bovercommitting\b",
        r"\bpersistence\b.*\bstubbornness\b",
        r"\bhelp me decide\b",
        r"\bwhat should i do about\b",
        r"\bhow should i handle\b",
        r"\bmy (friend|partner|family|boss)\b",
        r"\b(advice|motivation|burnout|anxious|stressed|overwhelmed)\b",
    ]
    return any(re.search(pat, p) for pat in coaching_patterns)


def _should_apply_heavy_shape(user_prompt: str, intent: str) -> bool:
    explicit = os.environ.get("LUCY_CONV_HEAVY_SHAPING", "").strip().lower()
    if explicit in {"1", "true", "yes", "on"}:
        return True
    if explicit in {"0", "false", "no", "off"}:
        return False
    if _is_coaching_prompt(user_prompt):
        return True
    i = (intent or "").strip().upper()
    if i == "LOCAL_CHAT":
        return False
    return False


def main() -> int:
    raw = sys.stdin.read()
    user_prompt = os.environ.get("LUCY_USER_PROMPT", "")
    intent = os.environ.get("LUCY_CONV_INTENT", "")
    max_short = int(os.environ.get("LUCY_CONV_MAX_CHARS_SHORT", "600") or "600")
    max_med = int(os.environ.get("LUCY_CONV_MAX_CHARS_MED", "1200") or "1200")
    profile = _read_profile()

    if _is_dismissal_prompt(user_prompt):
        return 0

    out = raw
    out = _remove_banned_openers(out)
    out = _remove_banned_closers(out)

    if profile.get("therapy_language_filter", True):
        out = _apply_therapy_filter(out)
    if profile.get("hedge_reduction", True):
        out = _limit_hedges(out, max_hedges=1)

    out = _apply_contrarian_layer(out, user_prompt, float(profile.get("contrarian_probability", 0.4) or 0.0))
    out = _reduce_balance_structure(out, int(profile.get("max_balance_sentences", 1) or 1))
    out = _soften_aggressive_language(out)

    apply_heavy_shape = (not _is_short_phatic_prompt(user_prompt)) and _should_apply_heavy_shape(user_prompt, intent)
    if profile.get("min_specificity", True) and apply_heavy_shape:
        out = _ensure_concrete_example(out)
        out = _enforce_substance_floor(out)
    if profile.get("force_conclusion", True) and apply_heavy_shape:
        out = _ensure_conclusion(out)

    out = _apply_growth_guard(raw, out)

    if _word_count(user_prompt) <= 12:
        out = _collapse_bullets_to_paragraph(out)
        cap = max_short
    else:
        cap = max_med

    out = _truncate_clean(out, cap)
    out = _normalize_spacing(out)

    warn_enabled = os.environ.get("LUCY_CONV_SHIM_WARN_STDERR", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if warn_enabled and out and not _has_conclusion(out):
        print("WARN: conclusion missing", file=sys.stderr)

    sys.stdout.write(out)
    if out and not out.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
