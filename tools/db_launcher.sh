#!/bin/bash
# Local Lucy V11 Database Viewer
# Non-truncating: displays full text for questions, answers, memory turns, and request history.

LUCY_ROOT="${LUCY_ROOT:-/home/mike/lucy-v11}"
DB1="${XDG_DATA_HOME:-$HOME/.local/share}/local-lucy-v11/state/lucy_state.db"
DB2="${LUCY_ROOT}/data/tubes/tube_database.db"
DB3="${XDG_DATA_HOME:-$HOME/.local/share}/local-lucy-v11/state/memory.db"
HISTORY_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/local-lucy-v11/state/request_history.jsonl"

show_lucy_state() {
    echo ""
    echo "=== LUCY_STATE.DB — System State ==="
    echo ""

    echo "📊 Route Distribution (legacy telemetry — may be stale if Python path is active):"
    sqlite3 "$DB1" "SELECT COALESCE(json_extract(metadata,'\$.final_mode'),'(empty)') AS route, COUNT(*) AS count FROM routes GROUP BY json_extract(metadata,'\$.final_mode') ORDER BY count DESC;" -column -header
    echo ""

    echo "✅ Outcome Summary (legacy telemetry):"
    sqlite3 "$DB1" "SELECT CASE success WHEN 1 THEN 'SUCCESS' ELSE 'FAILED' END AS status, COUNT(*) AS count FROM outcomes GROUP BY success;" -column -header
    echo ""

    echo "📝 Recent 5 Requests from canonical request_history.jsonl:"
    recent_request_history_table 5
    echo ""

    echo "💬 Recent 5 Answers from canonical request_history.jsonl:"
    recent_answer_history_table 5
    echo ""

    echo "🐢 Slowest Recent Outcomes (legacy telemetry, top 5):"
    sqlite3 "$DB1" "SELECT COALESCE(json_extract(result,'\$.route.mode'),'?') AS route, duration_ms/1000.0 AS seconds, COALESCE(error_message,'') AS error FROM outcomes WHERE duration_ms > 0 ORDER BY duration_ms DESC LIMIT 5;" -line
    echo ""

    read -rp "Press Enter to run custom SQL, or 'q' to go back: " ans
    if [[ "$ans" == "q" ]]; then return; fi
    sqlite3 "$DB1"
}

recent_request_history_table() {
    local limit="${1:-5}"
    python3 - "$HISTORY_FILE" "$limit" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
limit = int(sys.argv[2])
if not path.exists():
    print("(request history file not found)")
    sys.exit(0)
lines = path.read_text(encoding="utf-8").strip().splitlines()
entries = [json.loads(line) for line in lines if line.strip()][-limit:]
if not entries:
    print("(no entries)")
    sys.exit(0)
print(f"{'Time':<20} {'Model':<24} {'Route':<10} {'Status':<10} {'RespLen':>8}  Question")
for e in reversed(entries):
    ts = e.get("completed_at", "")[:19].replace("T", " ")
    model = e.get("control_state", {}).get("model", "?")[:23]
    route = e.get("route", {}).get("mode", "?")[:9]
    status = e.get("status", "?")[:9]
    rlen = len(e.get("response_text", ""))
    q = e.get("request_text", "")[:80].replace("\n", " ")
    print(f"{ts:<20} {model:<24} {route:<10} {status:<10} {rlen:>8}  {q}")
PY
}

recent_answer_history_table() {
    local limit="${1:-5}"
    python3 - "$HISTORY_FILE" "$limit" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
limit = int(sys.argv[2])
if not path.exists():
    print("(request history file not found)")
    sys.exit(0)
lines = path.read_text(encoding="utf-8").strip().splitlines()
entries = [json.loads(line) for line in lines if line.strip()][-limit:]
if not entries:
    print("(no entries)")
    sys.exit(0)
print(f"{'Time':<20} {'Model':<24} {'Route':<10} {'Status':<10} Answer preview")
for e in reversed(entries):
    ts = e.get("completed_at", "")[:19].replace("T", " ")
    model = e.get("control_state", {}).get("model", "?")[:23]
    route = e.get("route", {}).get("mode", "?")[:9]
    status = e.get("status", "?")[:9]
    a = e.get("response_text", "")[:120].replace("\n", " ")
    print(f"{ts:<20} {model:<24} {route:<10} {status:<10} {a}")
PY
}

show_request_history() {
    echo ""
    echo "=== REQUEST_HISTORY.JSONL — Canonical Recent Requests ==="
    echo ""

    python3 - "$HISTORY_FILE" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.exists():
    print("(request history file not found)")
    sys.exit(0)
lines = path.read_text(encoding="utf-8").strip().splitlines()
entries = [json.loads(line) for line in lines if line.strip()][-20:]
if not entries:
    print("(no entries)")
    sys.exit(0)
print(f"{'#':<3} {'Time':<20} {'Model':<24} {'Route':<10} {'Len':>6}")
for idx, e in enumerate(entries, start=1):
    ts = e.get("completed_at", "")[:19].replace("T", " ")
    model = e.get("control_state", {}).get("model", "?")[:23]
    route = e.get("route", {}).get("mode", "?")[:9]
    rlen = len(e.get("response_text", ""))
    q = e.get("request_text", "")[:60].replace("\n", " ")
    print(f"{idx:<3} {ts:<20} {model:<24} {route:<10} {rlen:>6}  {q}...")

print("\nEnter a number 1-20 to view the full request and response for that entry,")
print("or press Enter to go back.")
PY

    read -rp "Choice: " choice
    if [[ -z "$choice" ]]; then return; fi
    if ! [[ "$choice" =~ ^[0-9]+$ ]]; then
        echo "Invalid choice."
        return
    fi

    python3 - "$HISTORY_FILE" "$choice" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
idx = int(sys.argv[2])
if not path.exists():
    print("(request history file not found)")
    sys.exit(0)
lines = path.read_text(encoding="utf-8").strip().splitlines()
entries = [json.loads(line) for line in lines if line.strip()][-20:]
if idx < 1 or idx > len(entries):
    print("Invalid index.")
    sys.exit(0)
e = entries[idx - 1]
print(f"\nTime:     {e.get('completed_at', '')}")
print(f"Model:    {e.get('control_state', {}).get('model', '?')}")
print(f"Route:    {e.get('route', {}).get('mode', '?')}")
print(f"Reason:   {e.get('route', {}).get('reason', '?')}")
print(f"Status:   {e.get('status', '?')}")
print(f"Outcome:  {e.get('outcome', {}).get('outcome_code', '?')}")
print(f"\n--- FULL REQUEST ({len(e.get('request_text',''))} chars) ---")
print(e.get("request_text", ""))
print(f"\n--- FULL RESPONSE ({len(e.get('response_text',''))} chars) ---")
print(e.get("response_text", ""))
PY

    echo ""
    read -rp "Press Enter to go back..."
}

show_tubes() {
    echo ""
    echo "=== TUBE_DATABASE.DB — Vacuum Tubes ==="
    echo ""

    echo "📊 Total tubes:"
    sqlite3 "$DB2" "SELECT COUNT(*) AS total, SUM(verified) AS verified, COUNT(*)-SUM(verified) AS unverified FROM tubes;" -column -header
    echo ""

    echo "🔬 Top 10 Verified Tubes:"
    sqlite3 "$DB2" "SELECT type, construction, vplate, pplate, gm FROM tubes WHERE verified = 1 ORDER BY type LIMIT 10;" -column -header
    echo ""

    echo "🔍 Search for a tube:"
    read -rp "Enter tube type (e.g. 6V6, EL34, 12AX7, KT88) or press Enter to skip: " tube
    if [[ -n "$tube" ]]; then
        echo ""
        sqlite3 "$DB2" "SELECT type, construction, vplate, vscreen, pplate, gm, heater FROM tubes WHERE type LIKE '%${tube}%';" -column -header
        echo ""
    fi

    echo "📋 Construction types:"
    sqlite3 "$DB2" "SELECT construction, COUNT(*) AS count FROM tubes GROUP BY construction ORDER BY count DESC LIMIT 10;" -column -header
    echo ""

    read -rp "Press Enter to run custom SQL, or 'q' to go back: " ans
    if [[ "$ans" == "q" ]]; then return; fi
    sqlite3 "$DB2"
}

show_memory() {
    echo ""
    echo "=== MEMORY.DB — Conversation Memory (non-truncating) ==="
    echo ""

    tables=$(sqlite3 "$DB3" ".tables" 2>/dev/null)
    if [[ -z "$tables" ]]; then
        echo "No tables found — memory database is empty or uninitialized."
        echo ""
        read -rp "Press Enter to go back..."
        return
    fi

    echo "Tables: $tables"
    echo ""

    if echo "$tables" | grep -qi "conversation_turns"; then
        echo "💬 Active Recent Conversation Turns (full text):"
        sqlite3 "$DB3" "SELECT role, text, datetime(created_at, 'localtime') AS time FROM conversation_turns ORDER BY created_at DESC LIMIT 6;" -line 2>/dev/null || echo "(Could not read conversation_turns table)"
    else
        echo "No 'conversation_turns' table found."
    fi
    echo ""

    if echo "$tables" | grep -qi "archived_turns"; then
        echo "🗃️ Recently Archived Turns (full text preserved in DB; previews shown):"
        sqlite3 "$DB3" "SELECT id, role, length(text) AS chars, substr(text,1,120) AS preview, datetime(archived_at, 'localtime') AS archived FROM archived_turns ORDER BY archived_at DESC LIMIT 6;" -line 2>/dev/null || echo "(Could not read archived_turns table)"
        echo ""
        read -rp "Enter an archived turn id to view its FULL TEXT, or press Enter to skip: " arch_id
        if [[ "$arch_id" =~ ^[0-9]+$ ]]; then
            echo ""
            echo "--- FULL ARCHIVED TURN ---"
            sqlite3 "$DB3" "SELECT role, text FROM archived_turns WHERE id = ${arch_id};" -line 2>/dev/null || echo "(Could not read archived turn id ${arch_id})"
            echo ""
            read -rp "Press Enter to continue..."
        fi
    else
        echo "No 'archived_turns' table found."
    fi
    echo ""

    if echo "$tables" | grep -qi "session_summaries"; then
        echo "📝 Session Summaries:"
        sqlite3 "$DB3" "SELECT session_id, summary_text, summarized_turn_count, datetime(created_at, 'localtime') AS time FROM session_summaries ORDER BY created_at DESC LIMIT 5;" -line 2>/dev/null || echo "(Could not read session_summaries table)"
    else
        echo "No 'session_summaries' table found."
    fi
    echo ""

    if echo "$tables" | grep -qi "persistent_facts"; then
        echo "📌 Persistent Facts:"
        sqlite3 "$DB3" "SELECT fact_text AS fact, category FROM persistent_facts ORDER BY id;" -line 2>/dev/null || echo "(Could not read persistent_facts table)"
    else
        echo "No 'persistent_facts' table found."
    fi
    echo ""

    read -rp "Press Enter to run custom SQL, or 'q' to go back: " ans
    if [[ "$ans" == "q" ]]; then return; fi
    sqlite3 "$DB3"
}

while true; do
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║              LOCAL LUCY V11  —  DATABASE VIEWER                  ║"
    echo "╠══════════════════════════════════════════════════════════════════╣"
    echo "║  1) lucy_state.db     — legacy telemetry + recent request history ║"
    echo "║  2) tube_database.db  — 647 vacuum tube specs                     ║"
    echo "║  3) memory.db         — conversation memory (active + archived)   ║"
    echo "║  4) request_history.jsonl — canonical full Q&A viewer             ║"
    echo "║  q) Quit                                                          ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""
    read -rp "Pick a number: " choice

    case "$choice" in
        1) show_lucy_state ;;
        2) show_tubes ;;
        3) show_memory ;;
        4) show_request_history ;;
        q|Q) exit 0 ;;
        *) echo "❌ Invalid choice: '$choice'" ;;
    esac
done
