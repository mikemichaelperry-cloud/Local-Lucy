# Local Lucy V11 Qualification — Runbook

## One-time setup

```bash
cd /home/mike/lucy-v11
python3 -m venv .venv  # only if not already present
source .venv/bin/activate
pip install -r requirements.txt  # if requirements change
```

## Reading order at session start

Always read these files in this order before doing any work:

```text
qualification/TEST_MASTER_PLAN.md
qualification/TEST_STATUS.json
qualification/TEST_TODO.md
qualification/SESSION_HANDOFF.md
qualification/DEFECT_REGISTER.md
qualification/DECISIONS.md
```

## Profiles

All commands assume the working directory is `/home/mike/lucy-v11`.

### `fast` — static and deterministic, no Ollama, no network

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_hmi_end_to_end.py -v
python3 -m pytest tools/router_py/tests -v -m "not model and not live_network and not voice"
```

Flags supported: `--resume`, `--from-test TEST_ID`, `--stage STAGE_ID`, `--stop-on-critical`, `--preserve-failed-fixtures`, `--diagnostic`, `--no-production-data`.

### `model-smoke` — sequential Gemma + Llama smoke, includes HMI surface

```bash
cd /home/mike/lucy-v11
python3 -m pytest qualification/ -v -m model_smoke --no-production-data
```

Runs:
- HMI surface injection-to-output (no models)
- Gemma smoke through HMI surface
- Release/unload Gemma
- Llama smoke through HMI surface
- Minimal model-switch checks

### `gemma-full`

```bash
cd /home/mike/lucy-v11
python3 -m pytest qualification/ -v -m gemma_full --no-production-data
```

### `llama-full`

```bash
cd /home/mike/lucy-v11
python3 -m pytest qualification/ -v -m llama_full --no-production-data
```

### `model-parity`

```bash
cd /home/mike/lucy-v11
python3 qualification/compare_model_results.py results/gemma_results.json results/llama_results.json
```

### `long-session`

```bash
cd /home/mike/lucy-v11
python3 -m pytest qualification/ -v -m long_session --no-production-data
```

### `faults`

```bash
cd /home/mike/lucy-v11
python3 -m pytest qualification/ -v -m fault_injection --no-production-data
```

### `performance`

```bash
cd /home/mike/lucy-v11
python3 -m pytest qualification/ -v -m performance --no-production-data
```

### `live-network`

Must be explicitly enabled.

```bash
cd /home/mike/lucy-v11
LUCY_QUAL_LIVE_NETWORK=1 python3 -m pytest qualification/ -v -m live_network --no-production-data
```

### `voice-smoke`

Only if voice is enabled and in scope.

```bash
cd /home/mike/lucy-v11
LUCY_QUAL_VOICE=1 python3 -m pytest qualification/ -v -m voice_smoke --no-production-data
```

### `full-qualification`

```bash
cd /home/mike/lucy-v11
python3 qualification/run_full_qualification.py --no-production-data
```

Runs all mandatory stages in dependency order and resumes from `TEST_STATUS.json` if interrupted.

## Environment safety

- Always set `--no-production-data` or `LUCY_RUNTIME_NAMESPACE_ROOT` to a disposable directory.
- Never set `LUCY_RUNTIME_STATE_FILE` to `/home/mike/lucy-v11/state/state/current_state.json` in tests.
- Model tests must run sequentially; never use `pytest-xdist` for model profiles.

## After running

1. Update `TEST_TODO.md` with task statuses and evidence references.
2. Update `TEST_STATUS.json` atomically.
3. Add any new defects to `DEFECT_REGISTER.md`.
4. Record decisions in `DECISIONS.md`.
5. Overwrite `SESSION_HANDOFF.md`.
6. Copy changed files to the Desktop:
   - `TEST_MASTER_PLAN.md` → `Local_Lucy_V11_TEST_MASTER_PLAN.md`
   - `TEST_CATALOGUE.md` → `Local_Lucy_V11_TEST_CATALOGUE.md`
   - `DECISIONS.md` → `Local_Lucy_V11_DECISIONS.md`
   - `SESSION_HANDOFF.md` → `Local_Lucy_V11_Session_Handoff_YYYY-MM-DD.md`
