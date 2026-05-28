#!/usr/bin/env python3
"""
Wikipedia tube parameter scraper.

Uses the MediaWiki API to fetch tube article infobox data.
Many tube articles (e.g. "6V6", "EL34", "12AX7") have structured infoboxes
with electrical parameters that can be extracted programmatically.

Usage:
    python3 wikipedia_tube_scraper.py --tubes 6V6,EL34,KT88
    python3 wikipedia_tube_scraper.py --from-file missing_tubes.txt
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import urllib.request
import urllib.parse

sys.path.insert(0, str(Path(__file__).parent))
from tube_database import init_db, lookup_tube

WIKI_API = "https://en.wikipedia.org/w/api.php"


def fetch_wiki_page(title: str) -> dict:
    """Fetch a Wikipedia page via API with structured infobox data."""
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "rvprop": "content",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
    }
    url = f"{WIKI_API}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def extract_infobox_params(wikitext: str) -> dict[str, str]:
    """Parse a Wikipedia infobox from wikitext. Returns key-value dict."""
    params: dict[str, str] = {}
    # Find the infobox template
    match = re.search(r"\{\{Infobox[^}]+vacuum tube[^}]*\}(.*?)\}\}", wikitext, re.IGNORECASE | re.DOTALL)
    if not match:
        # Try broader match
        match = re.search(r"\{\{Infobox[^}]+tube[^}]*\}(.*?)\}\}", wikitext, re.IGNORECASE | re.DOTALL)
    if not match:
        return params

    infobox = match.group(1)
    # Extract key = value pairs
    for line in infobox.split("\n"):
        line = line.strip()
        if "=" not in line:
            continue
        if line.startswith("|"):
            line = line[1:].strip()
        key, _, val = line.partition("=")
        key = key.strip().lower()
        val = val.strip()
        # Remove wiki markup
        val = re.sub(r"\[\[([^\]|]+)\|?[^\]]*\]\]", r"\1", val)
        val = re.sub(r"\{\{[^}]+\}\}", "", val)
        val = re.sub(r"<[^>]+>", "", val)
        val = val.strip()
        if key and val:
            params[key] = val
    return params


def parse_numeric(value: str) -> float | int | None:
    """Extract a number from a string like '315 V' or '12.5 W'."""
    if not value:
        return None
    # Remove units and annotations
    cleaned = re.sub(r"\[.*?\]", "", value)
    cleaned = re.sub(r"\(.*\)", "", cleaned)
    cleaned = cleaned.replace(",", "").strip()
    m = re.search(r"([0-9]+\.?[0-9]*)", cleaned)
    if not m:
        return None
    num_str = m.group(1)
    try:
        if "." in num_str:
            return float(num_str)
        return int(num_str)
    except ValueError:
        return None


def infobox_to_tube_record(tube_type: str, params: dict[str, str]) -> dict[str, Any] | None:
    """Convert Wikipedia infobox params to a tube database record."""
    if not params:
        return None

    # Determine construction type
    construction = "unknown"
    class_val = params.get("class", "").lower()
    desc = params.get("description", "").lower()
    if "beam power tetrode" in class_val or "beam power tetrode" in desc:
        construction = "beam power tetrode"
    elif "pentode" in class_val or "pentode" in desc:
        construction = "pentode"
    elif "triode" in class_val or "triode" in desc:
        if "directly heated" in class_val or "directly heated" in desc:
            construction = "directly heated triode"
        else:
            construction = "triode"
    elif "dual triode" in class_val or "dual triode" in desc:
        construction = "dual triode"
    elif "rectifier" in class_val or "rectifier" in desc:
        construction = "full-wave rectifier"
    elif "tetrode" in class_val:
        construction = "beam power tetrode"

    vplate = parse_numeric(params.get("max anode voltage", "") or params.get("max plate voltage", ""))
    vscreen = parse_numeric(params.get("max screen voltage", "") or params.get("max grid 2 voltage", ""))
    pplate = parse_numeric(params.get("max anode dissipation", "") or params.get("max plate dissipation", ""))
    gm = parse_numeric(params.get("transconductance", ""))
    heater_v = parse_numeric(params.get("heater voltage", ""))
    heater_a = parse_numeric(params.get("heater current", ""))

    # Build notes from description + applications
    notes_parts = []
    if params.get("description"):
        notes_parts.append(params["description"])
    if params.get("used_in"):
        notes_parts.append(f"Used in: {params['used_in']}")
    if params.get("manufacturer"):
        notes_parts.append(f"Manufacturer: {params['manufacturer']}")
    notes = " ".join(notes_parts)[:300] if notes_parts else None

    record = {
        "type": tube_type,
        "construction": construction,
        "vplate_max": vplate,
        "vscreen_max": vscreen,
        "pplate_max": pplate,
        "transconductance_ma_v": gm,
        "typical_push_pull_watts": None,
        "recommended_load_ohms": None,
        "heater_volts": heater_v,
        "heater_amps": heater_a,
        "notes": notes,
    }

    # Only return if we got at least some meaningful data
    if vplate or pplate or gm:
        return record
    return None


def scrape_tube(tube_type: str) -> dict[str, Any] | None:
    """Scrape a single tube from Wikipedia. Returns record or None."""
    data = fetch_wiki_page(tube_type + " (vacuum tube)")
    if "error" in data:
        # Try without suffix
        data = fetch_wiki_page(tube_type)
        if "error" in data:
            return None

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None

    page = pages[0]
    if "missing" in page:
        return None

    revisions = page.get("revisions", [])
    if not revisions:
        return None

    wikitext = revisions[0].get("slots", {}).get("main", {}).get("*", "")
    if not wikitext:
        return None

    params = extract_infobox_params(wikitext)
    return infobox_to_tube_record(tube_type, params)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tubes", help="Comma-separated tube types")
    parser.add_argument("--from-file", type=Path)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tube_list = []
    if args.tubes:
        tube_list = [t.strip().upper() for t in args.tubes.split(",") if t.strip()]
    if args.from_file:
        text = args.from_file.read_text(encoding="utf-8")
        tube_list = [t.strip().upper() for t in text.splitlines() if t.strip() and not t.strip().startswith("#")]

    if not tube_list:
        parser.print_help()
        return 1

    conn = init_db(args.db)
    success = 0
    fail = 0
    skip = 0

    for tube in tube_list:
        if lookup_tube(conn, tube):
            skip += 1
            continue

        record = scrape_tube(tube)
        if not record:
            fail += 1
            print(f"  [FAIL] {tube}: no Wikipedia data")
            time.sleep(args.delay)
            continue

        if args.dry_run:
            print(f"  [DRY] {tube}: {record['construction']}, {record['vplate_max']}V, {record['pplate_max']}W")
            success += 1
            time.sleep(args.delay)
            continue

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
        success += 1
        print(f"  [OK] {tube}: {record['construction']}, {record['vplate_max']}V, {record['pplate_max']}W")
        time.sleep(args.delay)

    conn.close()
    print(f"\nTotal: {len(tube_list)} | Inserted: {success} | Failed: {fail} | Skipped: {skip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
