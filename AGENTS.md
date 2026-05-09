# Local Lucy v8 — Codex Execution Rules

## Authority

- The authoritative working root is:
  /home/mike/lucy-v8
- Snapshot sync target:
  /home/mike/lucy-v8/snapshots/opt-experimental-v8-dev (mirror, not source)

- Do not modify:
  - launcher structure
  - HMI structure
  - unrelated subsystems

- Backend is authoritative. UI must not fabricate state.

## System Privileges

- **Never use `sudo`.** The system blocks external sudo requests and the shell crashes.
- Make changes only within `~/lucy-v8/` directories.
- For system-level changes (e.g., systemd, global env vars), use user-level alternatives:
  - Modify `START_LUCY.sh` to export env vars
  - Use per-user systemd overrides (`~/.config/systemd/user/`) if available
  - Never edit `/etc/systemd/system/` or other root-owned paths

## Operating Principles

- No optimistic behavior
- No silent side effects
- No hallucinated files
- Test every change
- Prefer Python over shell for logic
- Prefer `StrReplaceFile` over `WriteFile` for edits
- Sync all backend changes to `snapshots/opt-experimental-v8-dev/`

## Feedback Learning System (Conversational)

Local Lucy can learn from natural-language user feedback without CLI commands.

### How it works

When you react to a response, Lucy detects the feedback *before* routing it as a new query:

| You say | Detected as | Action |
|---|---|---|
| "that was wrong, it should have been LOCAL" | Route correction | Logs `{query, correct_route: LOCAL}` → rebuilds embeddings |
| "wrong route, that was NEWS" | Route correction | Same, with route=NEWS |
| "that was a bad answer" | Negative quality | Logs complaint (no auto-route guess) |
| "perfect, thank you" | Positive quality | Confirms/strengthens existing route |
| "forget that" | Retraction | Removes prior exchange from memory |

### Files

- `tools/router_py/feedback_buffer.py` — Ring buffer of last 5 exchanges (persisted to runtime namespace)
- `tools/router_py/feedback_parser.py` — Pattern-based NL feedback detection + logging
- `models/router/user_feedback.jsonl` — Logged corrections (ingested by background_learner.py)
- `models/router/background_learner.py` — Rebuilds embedding index from feedback + auto-feedback

### Attribution

Feedback is always attributed to the **most recent exchange** in the buffer. The buffer records:
- Query text
- Route chosen
- Intent family
- Response text (truncated)
- Confidence

### Learning trigger

After each logged correction, `maybe_auto_learn(min_entries=1)` is called. This starts a background thread that:
1. Reads `user_feedback.jsonl`
2. Deduplicates by query
3. Rebuilds `comprehensive_embeddings.npy` and `comprehensive_examples.json`
4. The next query uses the updated index immediately

### Adding new feedback patterns

Edit `feedback_parser.py`:
- `ROUTE_CORRECTION_PATTERNS` — regexes that extract route names
- `ANSWER_NEGATIVE_PATTERNS` — negative quality signals
- `ANSWER_POSITIVE_PATTERNS` — positive quality signals
- `RETRACTION_PATTERNS` — commands to forget/retract

Patterns are checked in order: route correction → retraction → negative → positive.

### Testing

```bash
cd ~/lucy-v8/ui-v8
.venv/bin/python3 -m pytest tests/ -q
```

Also run the fast routing stress test:
```bash
.venv/bin/python3 fast_routing_stress_test.py
```

### Sync rule

Any change to `tools/router_py/` or `models/router/` must be copied to:
```
snapshots/opt-experimental-v8-dev/tools/router_py/
snapshots/opt-experimental-v8-dev/models/router/
```
