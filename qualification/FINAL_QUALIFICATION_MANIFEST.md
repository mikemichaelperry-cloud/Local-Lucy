# Local Lucy V11 — Final Qualification Manifest

**Qualification decision:** `QUALIFIED`

**Date (UTC):** 2026-08-06T17:23:12Z

---

## Git state

| Property | Value |
|---|---|
| Repository | `/home/mike/lucy-v11` |
| Branch | `main` |
| Commit | `423e5dd70985ff654e46d6a693fa4d24e70404ff` |
| Working tree | **clean** |
| Rollback commit | `32490923dd607cd4c3da491ce5e4c8ebc0f29773` |
| V10 status | untouched |

---

## Environment

- **OS:** Ubuntu 22.04.5 LTS
- **Kernel:** Linux mike-System-Product-Name 6.8.0-136-generic #136~22.04.1-Ubuntu SMP PREEMPT_DYNAMIC Fri Jul  3 16:29:11 UTC  x86_64 x86_64 x86_64 GNU/Linux
- **Python:** 3.10.12
- **Dependency lock SHA-256:** `c28dda315c943c619768caf3183d1edb18c893cac714482abd6efe75c9a9c0cd`
- **Installed package freeze SHA-256:** `c5e1d0a501d1ed3fdd2d349a22787fcabdd05b07e8244dbe58526d964b860353`

---

## Models

| Model | Ollama tag | Ollama ID | Blob digest |
|---|---|---|---|
| Gemma | `local-lucy-gemma4:latest` | `97b4a7a8de9a` | `sha256-faff1a63667fac17ac5e777f47114688fcefea96e220e211aaa8d62c2c4561f1` |
| Llama | `local-lucy-llama31:latest` | `4282cbd85b15` | `sha256-667b0c1932bc6ffc593ed1d03f895bf2dc8dc6df21db3042284a6f4416b06a29` |

Gemma also uses adapter `sha256-e70b0e5cd80323d5d588b4ed06780356b7b1ba03995a4b8164c6ae9db0ff5989`.

---

## Router assets

| File | SHA-256 |
|---|---|
| `models/router/comprehensive_examples.json` | `b278514c064eac55b0a40f57659901a74b42597cca6c4487121d29431952708f` |
| `models/router/comprehensive_embeddings.npy` | `6166e28af993b0a1638e784bfbbe6da26d6a0493dec36c5995f37c8935a52d56` |
| `models/router/classifier_head.pt` | `12e2c1691459dde696f808122bfd19ba618b97c2ca308b13e8c84d6d353d406d` |
| `models/router/classifier_head_config.json` | `250aea0d02ffa4697c7520ffc0d6776a68bb6bd1a9e0902779a562990316fc18` |

---

## Configuration

- `LUCY_EVIDENCE_ENABLED=1`
- `LUCY_ENABLE_INTERNET=1`
- `LUCY_AUGMENTATION_POLICY=fallback_only`
- `LUCY_SESSION_MEMORY=0`

### Memory defaults

- `recent_turn_limit`: 12
- `semantic_older_turns`: 8
- `execution_engine_max_chars`: 2400
- `config_default_max_chars`: 2000

The execution-engine helper passes `max_chars=2400`; the config default remains `2000`. This override is tested in `tools/router_py/test_execution_engine_memory.py`.

---

## Test results

### Full deterministic regression

```bash
python3 -m pytest tools/router_py -v --tb=short
```

**Result:** `1233 passed, 7 skipped, 274 deselected, 188 subtests passed` (2026-08-06T16:39Z)

### Memory requalification

```bash
python3 -m pytest tools/tests/test_memory_requalification.py \
  tools/router_py/test_execution_engine_memory.py \
  tools/router_py/test_memory_gate.py \
  tools/router_py/test_location_memory.py -v --tb=short
```

**Result:** `156 passed, 46 subtests passed`

### Privacy and fault verification

```bash
python3 -m pytest tools/router_py/test_stage_06_planner_security.py \
  tools/router_py/test_stage_06_untrusted_web.py \
  tools/router_py/test_stage_14_fault_injection.py \
  tools/router_py/test_stage_15_privacy_audit.py \
  tools/router_py/test_execution_engine_state.py::TestPIIRedaction \
  tools/tests/test_memory_privacy_canary.py -v --tb=short
```

**Result:** `30 passed` (2026-08-06T16:59Z)

### Model verification

| Stage | Result |
|---|---|
| `stage_08_gemma_smoke.py` | 3/3 passed |
| `stage_09_gemma_scenario_suite.py` | 12/12 passed |
| `stage_10_llama_smoke.py` | 3/3 passed |
| `stage_11_llama_scenario_suite.py` | 12/12 passed, 12/12 route parity, 12/12 outcome parity |
| `stage_13_model_switch.py` | 3/3 passed |

No dual-model residency observed at any checkpoint.

### Soak and final clean run

```bash
python3 tools/router_py/stage_19_clean_run.py
```

**Result:** `7/7 stages passed` (2026-08-06T17:21Z)

---

## Routing metrics

- **Validation:** 21/21 = 1.000
- **Holdout:** 13/15 = 0.867
- **Combined:** 34/36 = 0.944

---

## Known limitations

1. **HMI-ANAPH-001:** `Use DuckDuckGo search` holdout expectation assumes `main.py` anaphora context that `compute_baseline_metrics.py` excludes; classified as `TEST_EXPECTATION_ERROR`.
2. Persistent-fact correction authority is not enforced automatically; newer contradictory facts are stored and retrieved but not preferred over older facts without explicit user management.
3. Generic low-confidence → AUGMENTED fallback is not implemented and is not being added during stabilisation.
4. Voice text-display issue reported but unreproduced in static/HMI tests; documented as `UNREPRODUCED` in `qualification/VOICE_TEXT_DISPLAY_INVESTIGATION.md`.

## Active defects

None.

---

## Result artefact checksums

| File | SHA-256 |
|---|---|
| `qualification/results/baseline_metrics.json` | `4066aced5ab5d073ff0f04bb517474fba72a997ce0d154bba1b86abdb2df2ee6` |
| `qualification/results/stage_08_gemma_smoke.json` | `b7a3e5d4f067815ab2cc840ba4d98e110b6e03b8b736c8f8067575f0a8ff9bca` |
| `qualification/results/stage_09_gemma_scenarios.json` | `57988bfee48bb08ac1188541520ce3497509bde6a9b752b1f88ac30059d3e980` |
| `qualification/results/stage_10_llama_smoke.json` | `110e54c3fd61d223657896c0e58eae8b585e501881d0bd684b0b128803f5c85e` |
| `qualification/results/stage_11_llama_scenarios.json` | `34b310b9666b2d33036d3e37e8acb07918342188bdb1be14290cf63f650c8fc0` |
| `qualification/results/stage_13_model_switch.json` | `2abffed0fe5c1ec7db263a5fbb79048181860992c9276809ccf7e966bec9b999` |
| `qualification/results/stage_16_hmi_soak.json` | `e1be4a89f33e337b6b79bd6231e3dd3a32ce6dc026d91b04f77907359987340d` |
| `qualification/results/stage_16_hmi_weather_boundary.json` | `d565e0da6c5d8b841fef62ab069e53c09fcbde011e5199ecbfe76aaa9ff7e47c` |
| `qualification/results/stage_19_clean_run.json` | `b4a8dde240aa648f4ff64e55346ac445c511313eff7227fdb1f66b6a1e888185` |

---

## Skipped / deselected tests

- **Skipped:** 7 live API tests (OpenAI/Kimi) that require external credentials.
- **Deselected:** 274 tests excluded by default pytest markers (`slow`, `live`, etc.).
