#!/bin/bash
# Local Lucy V11 Database Viewer

LUCY_ROOT="${LUCY_ROOT:-/home/mike/lucy-v11}"
DB1="${XDG_DATA_HOME:-$HOME/.local/share}/local-lucy-v11/state/lucy_state.db"
DB2="${LUCY_ROOT}/data/tubes/tube_database.db"
DB3="${XDG_DATA_HOME:-$HOME/.local/share}/local-lucy-v11/state/memory.db"

show_lucy_state() {
    echo ""
    echo "=== LUCY_STATE.DB — System State ==="
    echo ""

    echo "📊 Route Distribution:"
    sqlite3 "$DB1" "SELECT COALESCE(json_extract(metadata,'\$.final_mode'),'(empty)') AS route, COUNT(*) AS count FROM routes GROUP BY json_extract(metadata,'\$.final_mode') ORDER BY count DESC;" -column -header
    echo ""

    echo "✅ Outcome Summary:"
    sqlite3 "$DB1" "SELECT CASE success WHEN 1 THEN 'SUCCESS' ELSE 'FAILED' END AS status, COUNT(*) AS count FROM outcomes GROUP BY success;" -column -header
    echo ""

    echo "📝 Recent 5 Queries:"
    sqlite3 "$DB1" "SELECT COALESCE(json_extract(metadata,'\$.question'),'?') AS question, COALESCE(json_extract(metadata,'\$.final_mode'),'?') AS route, substr(created_at,1,19) AS time FROM routes ORDER BY created_at DESC LIMIT 5;" -line
    echo ""

    echo "💬 Recent 5 Answers:"
    sqlite3 "$DB1" "SELECT substr(created_at,1,19) AS time, COALESCE(json_extract(result,'\$.response_text'),'(empty)') AS answer FROM outcomes WHERE success = 1 ORDER BY created_at DESC LIMIT 5;" -line
    echo ""

    echo "🐢 Slowest Recent Outcomes (top 5):"
    sqlite3 "$DB1" "SELECT COALESCE(json_extract(result,'\$.route.mode'),'?') AS route, duration_ms/1000.0 AS seconds, COALESCE(error_message,'') AS error FROM outcomes WHERE duration_ms > 0 ORDER BY duration_ms DESC LIMIT 5;" -line
    echo ""

    read -rp "Press Enter to run custom SQL, or 'q' to go back: " ans
    if [[ "$ans" == "q" ]]; then return; fi
    sqlite3 "$DB1"
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
    echo "=== MEMORY.DB — Conversation Memory ==="
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

    # Try to show turns if table exists
    if echo "$tables" | grep -qi "conversation_turns"; then
        echo "💬 Recent Conversation Turns:"
        sqlite3 "$DB3" "SELECT role, text, substr(created_at,1,19) AS time FROM conversation_turns ORDER BY created_at DESC LIMIT 8;" -line 2>/dev/null || echo "(Could not read conversation_turns table)"
    else
        echo "No 'conversation_turns' table found."
    fi
    echo ""

    # Show persistent facts
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
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║              LOCAL LUCY V11  —  DATABASE VIEWER              ║"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  1) lucy_state.db     — routes, outcomes, telemetry          ║"
    echo "║  2) tube_database.db  — 647 vacuum tube specs                ║"
    echo "║  3) memory.db         — conversation memory                  ║"
    echo "║  q) Quit                                                     ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    read -rp "Pick a number: " choice

    case "$choice" in
        1) show_lucy_state ;;
        2) show_tubes ;;
        3) show_memory ;;
        q|Q) exit 0 ;;
        *) echo "❌ Invalid choice: '$choice'" ;;
    esac
done
