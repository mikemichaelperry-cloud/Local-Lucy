# Voice Text-Display Issue — Investigation Record

## Reported symptom

During live HMI use with voice enabled:
- A question was asked and the answer was spoken, but neither the request nor the answer text appeared in the HMI conversation panel.
- A follow-up question was also answered by voice with no text shown.
- The request had been typed in while voice mode was active.

## Existing artefacts

- `SESSION_HANDOFF.md` lists "Voice text display" as known limitation #3.
- No log file, case ID, or reproducible scenario was attached to the original report.

## Reproduction attempts

### 1. Backend voice-path test harness

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_voice_request_parity.py -v --tb=short
python3 -m pytest tools/router_py/test_e2e_hmi_voice.py -m "slow and live" -v --tb=short
```

Results:
- `test_voice_request_parity.py`: 7 passed.
- `test_e2e_hmi_voice.py`: 15 passed.

These tests exercise the full `ExecutionEngine` + `StateWriter` stack for both `voice` and `hmi` surfaces and verify that:
- state JSON files contain `request_text` and `response_text`;
- SQLite outcome records contain the same fields;
- voice-surface metadata is propagated.

No failure was observed in the backend path.

### 2. Stage 18 voice smoke

```bash
cd /home/mike/lucy-v11
python3 tools/router_py/stage_18_voice_smoke.py
```

Result: skipped because `LUCY_ENABLE_VOICE_TESTS=1` is not set. The smoke test requires live microphone input and TTS; running it non-interactively is not practical in this session.

### 3. UI offscreen tests

```bash
cd /home/mike/lucy-v11
python3 -m pytest ui-v10/tests/test_offscreen_smoke.py -v --tb=short
```

Result: 6 passed. The offscreen harness can instantiate the HMI widgets, but none of the existing offscreen tests cover the conversation-panel refresh path after a voice turn completes.

## Findings

- The backend voice pipeline writes request/answer text to the same state stores used by the HMI text path.
- The `ConversationPanel._format_operator_entry` method already renders `request_text` and `response_text` for all statuses (`processing`, `responding`, `completed`).
- The most likely remaining causes are in the UI refresh layer:
  - the main window not calling `set_history_entries()` after a voice turn transitions from `responding` to `completed`;
  - a race between the voice subprocess writing state and the UI polling interval;
  - the typed request being submitted through a path that bypasses the conversation history update.

## Status

**UNREPRODUCED** in automated tests.

## Risk assessment

- Severity: MEDIUM — user-visible text may be missing for voice answers, but the backend state is still persisted.
- Safety/privacy impact: none.
- Workaround: use the text path or wait for the HMI to refresh.

## Recommended next step

Add an interactive HMI regression step to the live-qualification runbook: after a voice turn, verify that the conversation panel shows both the request and the response. Once a deterministic reproduction exists, add an offscreen regression test and apply the smallest UI fix.
