#!/usr/bin/env python3
"""
OpenAI Tube Extractor — bulk-import tube parameters from manufacturer datasheets.

Usage:
    export OPENAI_API_KEY="sk-..."
    python3 openai_tube_extractor.py --tubes 6V6GT,EL34,KT88
    python3 openai_tube_extractor.py --from-file missing_tubes.txt
    python3 openai_tube_extractor.py --tubes 6V6GT --dry-run

Requires:
    pip install openai
    OPENAI_API_KEY environment variable set

The script queries OpenAI with a carefully structured prompt asking for exact
parameter extraction from RCA/GE/Mullard datasheets.  Responses are parsed as
JSON and validated before insertion.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Import our local DB module
sys.path.insert(0, str(Path(__file__).parent))
from tube_database import init_db, lookup_tube


def get_openai_client():
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai")
        sys.exit(1)

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("ERROR: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='sk-...'")
        sys.exit(1)

    return OpenAI(api_key=key)


EXTRACTION_PROMPT = """You are a precise technical database extractor specializing in vacuum tube parameters.

Extract the following parameters for the tube type '{tube_type}' from manufacturer datasheets (RCA, GE, Mullard, Sylvania, Telefunken).

Return ONLY a JSON object with these exact keys:
{{
  "type": "exact tube type",
  "construction": "beam power tetrode | pentode | triode | dual triode | directly heated triode | triode-pentode | full-wave rectifier | etc.",
  "vplate_max": integer or null,
  "vscreen_max": integer or null,
  "pplate_max": float or null (watts),
  "transconductance_ma_v": float or null (mA/V),
  "typical_push_pull_watts": "string describing typical push-pull AB1 output with plate voltage and load impedance, or null",
  "recommended_load_ohms": integer or null (primary impedance for push-pull),
  "heater_volts": float or null,
  "heater_amps": float or null,
  "notes": "Brief notes on common applications, famous amplifiers using this tube, and any important cautions."
}}

Rules:
- Use ONLY documented maximum ratings from datasheets, not anecdotes.
- If a parameter is not available in standard datasheets, use null.
- For typical_push_pull_watts, give the approximate wattage and conditions (e.g. "12W @ 315V plate, 250V screen, 8kΩ primary").
- Keep notes under 200 characters.
- Do NOT include markdown code fences, ONLY raw JSON.
- If the tube type is unknown or ambiguous, return {{"error": "unknown tube type"}}.
"""


@dataclass
class ExtractionResult:
    tube_type: str
    raw_json: str
    parsed: dict[str, Any] | None
    error: str | None
    cost_estimate_usd: float


def extract_tube(client, tube_type: str, model: str = "gpt-4o-mini") -> ExtractionResult:
    """Call OpenAI to extract tube parameters."""
    prompt = EXTRACTION_PROMPT.format(tube_type=tube_type)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You extract precise technical parameters from vacuum tube datasheets. Output valid JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        return ExtractionResult(
            tube_type=tube_type,
            raw_json="",
            parsed=None,
            error=f"OpenAI API error: {e}",
            cost_estimate_usd=0.0,
        )

    raw = response.choices[0].message.content or ""

    # Cost estimate: gpt-4o-mini ~ $0.15 / 1M input tokens, $0.60 / 1M output
    input_tok = response.usage.prompt_tokens if response.usage else 0
    output_tok = response.usage.completion_tokens if response.usage else 0
    cost = (input_tok * 0.15 + output_tok * 0.60) / 1_000_000

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return ExtractionResult(
            tube_type=tube_type,
            raw_json=raw,
            parsed=None,
            error=f"JSON parse error: {e}",
            cost_estimate_usd=cost,
        )

    if "error" in parsed:
        return ExtractionResult(
            tube_type=tube_type,
            raw_json=raw,
            parsed=None,
            error=parsed["error"],
            cost_estimate_usd=cost,
        )

    return ExtractionResult(
        tube_type=tube_type,
        raw_json=raw,
        parsed=parsed,
        error=None,
        cost_estimate_usd=cost,
    )


def validate_and_insert(
    conn: sqlite3.Connection, result: ExtractionResult, dry_run: bool = False
) -> bool:
    """Validate extraction result and insert into DB. Returns True on success."""
    if result.error:
        print(f"  [FAIL] {result.tube_type}: {result.error}")
        return False

    p = result.parsed
    assert p is not None

    # Type check / sanitize
    tube_type = str(p.get("type", result.tube_type)).strip().upper()
    if not tube_type:
        print(f"  [FAIL] {result.tube_type}: missing type field")
        return False

    # Check for existing
    existing = lookup_tube(conn, tube_type)
    if existing:
        print(f"  [SKIP] {tube_type}: already in database")
        return False

    # Sanitize numeric fields
    def to_int(v):
        try:
            return int(v) if v is not None else None
        except (ValueError, TypeError):
            return None

    def to_float(v):
        try:
            return float(v) if v is not None else None
        except (ValueError, TypeError):
            return None

    row = (
        tube_type,
        str(p.get("construction", "unknown")),
        to_int(p.get("vplate_max")),
        to_int(p.get("vscreen_max")),
        to_float(p.get("pplate_max")),
        to_float(p.get("transconductance_ma_v")),
        str(p.get("typical_push_pull_watts")) if p.get("typical_push_pull_watts") else None,
        to_int(p.get("recommended_load_ohms")),
        to_float(p.get("heater_volts")),
        to_float(p.get("heater_amps")),
        str(p.get("notes", ""))[:300],
    )

    if dry_run:
        print(f"  [DRY-RUN] {tube_type}: {row}")
        return True

    conn.execute(
        """
        INSERT INTO tubes
        (type, construction, vplate_max, vscreen_max, pplate_max,
         transconductance_ma_v, typical_push_pull_watts,
         recommended_load_ohms, heater_volts, heater_amps, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        row,
    )
    conn.commit()
    print(f"  [OK] {tube_type} inserted (${result.cost_estimate_usd:.4f})")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk-extract tube parameters via OpenAI")
    parser.add_argument("--tubes", help="Comma-separated list of tube types")
    parser.add_argument("--from-file", type=Path, help="File with one tube type per line")
    parser.add_argument(
        "--model", default="gpt-4o-mini", help="OpenAI model (default: gpt-4o-mini)"
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, help="Seconds between API calls (default: 1.0)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be inserted without writing"
    )
    parser.add_argument("--db", type=Path, default=None, help="Path to SQLite DB")
    args = parser.parse_args()

    if not args.tubes and not args.from_file:
        parser.print_help()
        return 1

    tube_list: list[str] = []
    if args.tubes:
        tube_list = [t.strip() for t in args.tubes.split(",") if t.strip()]
    if args.from_file:
        text = args.from_file.read_text(encoding="utf-8")
        tube_list.extend(
            [t.strip() for t in text.splitlines() if t.strip() and not t.strip().startswith("#")]
        )

    if not tube_list:
        print("No tube types provided.")
        return 1

    print(f"Extracting {len(tube_list)} tube(s) using {args.model}...")
    if args.dry_run:
        print("(dry-run mode — no DB writes)")

    client = get_openai_client()
    conn = init_db(args.db)

    total_cost = 0.0
    success = 0
    fail = 0
    skip = 0

    for tube in tube_list:
        print(f"\nQuerying: {tube}")
        result = extract_tube(client, tube, model=args.model)
        total_cost += result.cost_estimate_usd

        if result.error:
            fail += 1
            print(f"  ERROR: {result.error}")
        elif lookup_tube(conn, tube):
            skip += 1
            print("  SKIP: already in database")
        else:
            if validate_and_insert(conn, result, dry_run=args.dry_run):
                success += 1
            else:
                fail += 1

        if not args.dry_run:
            time.sleep(args.delay)

    conn.close()

    print(f"\n{'=' * 50}")
    print(f"Total tubes: {len(tube_list)}")
    print(f"Inserted:    {success}")
    print(f"Skipped:     {skip}")
    print(f"Failed:      {fail}")
    print(f"Est. cost:   ${total_cost:.4f} USD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
