#!/usr/bin/env python3
"""
OpenAI Batch Tube Extractor — extract multiple tubes per API call.

Usage:
    export OPENAI_API_KEY="sk-..."
    python3 openai_batch_extractor.py --from-file missing_tubes.txt --batch-size 20
    python3 openai_batch_extractor.py --from-file missing_tubes.txt --batch-size 20 --dry-run

This is much faster than single-tube extraction (~20x fewer API calls).
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

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
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)
    return OpenAI(api_key=key)


BATCH_PROMPT_TEMPLATE = """Extract vacuum tube parameters for the following tube types from manufacturer datasheets (RCA, GE, Mullard, Sylvania, Telefunken, Soviet GOST).

For EACH tube, provide a JSON object with these exact keys:
- type: exact tube type
- construction: one of [beam power tetrode, pentode, triode, dual triode, directly heated triode, triode-pentode, full-wave rectifier, unknown]
- vplate_max: integer or null (max plate voltage in V)
- vscreen_max: integer or null (max screen/grid2 voltage in V)
- pplate_max: float or null (max plate dissipation in W)
- transconductance_ma_v: float or null (transconductance in mA/V)
- typical_push_pull_watts: string or null (e.g. "12W @ 315V plate, 250V screen, 8kΩ primary")
- recommended_load_ohms: integer or null (typical push-pull primary impedance)
- heater_volts: float or null
- heater_amps: float or null
- notes: string under 200 chars (applications, famous amps, cautions)

Return a JSON array with one object per tube, in the SAME ORDER as listed below.
If a tube type is unknown or ambiguous, use null for all fields except type and construction="unknown".

Tubes to extract:
{tubes_list}

Rules:
- Use ONLY documented datasheet maximum ratings
- Keep notes under 200 characters
- Return ONLY a valid JSON array, no markdown code fences
"""


def extract_batch(client, tubes: list[str], model: str = "gpt-4o-mini") -> list[dict]:
    """Extract parameters for a batch of tubes. Returns list of records."""
    prompt = BATCH_PROMPT_TEMPLATE.format(tubes_list="\n".join(f"- {t}" for t in tubes))
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You extract precise vacuum tube parameters from manufacturer datasheets. Output valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        print(f"  API error: {e}")
        return []

    raw = response.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
        # The model might return {tubes: [...]} or just [...]
        if isinstance(parsed, dict):
            for key in parsed:
                if isinstance(parsed[key], list):
                    return parsed[key]
            return []
        elif isinstance(parsed, list):
            return parsed
        return []
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        print(f"  Raw: {raw[:500]}")
        return []


def sanitize_record(record: dict) -> dict | None:
    """Validate and sanitize a tube record."""
    tube_type = str(record.get("type", "")).strip().upper()
    if not tube_type:
        return None

    construction = str(record.get("construction", "unknown")).strip()

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

    return {
        "type": tube_type,
        "construction": construction,
        "vplate_max": to_int(record.get("vplate_max")),
        "vscreen_max": to_int(record.get("vscreen_max")),
        "pplate_max": to_float(record.get("pplate_max")),
        "transconductance_ma_v": to_float(record.get("transconductance_ma_v")),
        "typical_push_pull_watts": str(record["typical_push_pull_watts"]) if record.get("typical_push_pull_watts") else None,
        "recommended_load_ohms": to_int(record.get("recommended_load_ohms")),
        "heater_volts": to_float(record.get("heater_volts")),
        "heater_amps": to_float(record.get("heater_amps")),
        "notes": str(record.get("notes", ""))[:300] if record.get("notes") else None,
    }


def insert_record(conn: sqlite3.Connection, record: dict) -> bool:
    """Insert a record into the database. Returns True on success."""
    try:
        conn.execute(
            """
            INSERT INTO tubes
            (type, construction, vplate_max, vscreen_max, pplate_max,
             transconductance_ma_v, typical_push_pull_watts,
             recommended_load_ohms, heater_volts, heater_amps, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["type"],
                record["construction"],
                record["vplate_max"],
                record["vscreen_max"],
                record["pplate_max"],
                record["transconductance_ma_v"],
                record["typical_push_pull_watts"],
                record["recommended_load_ohms"],
                record["heater_volts"],
                record["heater_amps"],
                record["notes"],
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        print(f"  DB error for {record['type']}: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-file", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--max", type=int, default=None, help="Max tubes to process")
    args = parser.parse_args()

    text = args.from_file.read_text(encoding="utf-8")
    all_tubes = [t.strip().upper() for t in text.splitlines() if t.strip() and not t.strip().startswith("#")]

    if args.max:
        all_tubes = all_tubes[:args.max]

    conn = init_db(args.db)

    # Filter out already existing
    missing = []
    for t in all_tubes:
        if not lookup_tube(conn, t):
            missing.append(t)

    print(f"Total candidates: {len(all_tubes)}")
    print(f"Already in DB: {len(all_tubes) - len(missing)}")
    print(f"To extract: {len(missing)}")
    print(f"Batch size: {args.batch_size}")
    print(f"Estimated API calls: {(len(missing) + args.batch_size - 1) // args.batch_size}")
    print()

    if not missing:
        print("Nothing to do.")
        return 0

    if args.dry_run:
        print("(dry-run mode)")
        return 0

    client = get_openai_client()
    total_cost = 0.0
    success = 0
    fail = 0
    skip = 0

    batches = [missing[i:i + args.batch_size] for i in range(0, len(missing), args.batch_size)]

    for i, batch in enumerate(batches, 1):
        print(f"Batch {i}/{len(batches)}: {batch[0]}... ({len(batch)} tubes)")
        records = extract_batch(client, batch, model=args.model)

        if not records:
            print(f"  [FAIL] Empty response for batch {i}")
            fail += len(batch)
            time.sleep(args.delay)
            continue

        for rec in records:
            sanitized = sanitize_record(rec)
            if not sanitized:
                fail += 1
                continue

            tube_type = sanitized["type"]
            if not tube_type or tube_type == "UNKNOWN":
                fail += 1
                continue

            if insert_record(conn, sanitized):
                print(f"  [OK] {tube_type}: {sanitized['construction']}, {sanitized['vplate_max']}V, {sanitized['pplate_max']}W")
                success += 1
            else:
                print(f"  [SKIP] {tube_type}: already exists")
                skip += 1

        time.sleep(args.delay)

    conn.close()
    print(f"\n{'='*50}")
    print(f"Total processed: {len(missing)}")
    print(f"Inserted: {success}")
    print(f"Skipped: {skip}")
    print(f"Failed: {fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
