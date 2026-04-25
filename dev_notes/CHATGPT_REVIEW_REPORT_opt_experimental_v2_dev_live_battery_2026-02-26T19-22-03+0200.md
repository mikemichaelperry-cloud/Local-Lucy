# ChatGPT Review Report: Opt Experimental v2 Dev Live Battery
Date: February 26, 2026
Time: 19:22:03 +0200

## 1. Purpose
Prepare a full review package for ChatGPT covering:
- latest session context (`dev_note`) usage
- full local + live internet regression battery
- borderline / break-through probes
- trust probe compatibility fix and rerun results
- residual issues requiring review or patching

## 2. Snapshot / Scope
- Active snapshot under test:
  - `/home/mike/lucy/snapshots/opt-experimental-v2-dev`
- Latest handoff used:
  - `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T19-19-56+0200.md`
- Frozen baseline (unchanged):
  - `/home/mike/lucy/snapshots/FROZEN/opt-experimental-v1-FROZEN-20260224`

## 3. Executive Summary
- The full regression suite passes in the active `opt-experimental-v2-dev` snapshot.
- Live internet E2E and internet/evidence systems regression both pass.
- Manual hostile/borderline URL probes (SSRF + parsing/allowlist bypass tricks) were blocked as expected.
- A compatibility issue in `tools/trust/probe_trust_sites.py` was fixed (policy parser + `LUCY_ROOT` support).
- After fixing the probe harness, the official trust probe runs but reports 2 gate expectation failures:
  - `idf.il` (probe host `www.idf.il`)
  - `texasinstruments.com` (probe host `ti.com`)
- These 2 failures appear to be alias/canonicalization mismatch issues between trust-catalog probe expectations and runtime gate allowlist matching, not broad regression of live internet behavior.

## 4. What Was Run (Live + Local)
### Core battery
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/internet/searxng_ensure_up.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/full_regression_v2.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/internet/internet_e2e_accept.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/internet/all_systems_regression.sh`

### Targeted guardrails
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_fetch_gate_url_safety_unified.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_router_allowlist_filter_enforcement.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_router_vs_fallback_mode_drift_monitor.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_query_policy_shared_heuristics.sh`

### Manual borderline / break-through probes (`run_fetch_with_gate.sh`)
Allowed (expected):
- `https://en.wikipedia.org/wiki/Test`

Blocked (expected):
- `https://example.com/` (not allowlisted)
- `http://localhost:8080/`
- `http://127.0.0.1:8080/`
- `http://127.1/`
- `http://2130706433/` (IPv4 dword)
- `http://0x7f000001/` (hex IP)
- `http://0177.0.0.1/` (octal-ish form)
- `http://user@127.0.0.1/` (userinfo trick)
- `http://[::1]/`
- `http://0.0.0.0/`
- `http://169.254.169.254/latest/meta-data/`
- `https://wikipedia.org.evil.com/` (suffix trick)

## 5. Results (Pass / Fail)
### PASS
- `tools/full_regression_v2.sh`
- `tools/internet/internet_e2e_accept.sh`
- `tools/internet/all_systems_regression.sh`
- `tools/tests/test_fetch_gate_url_safety_unified.sh`
- `tools/tests/test_router_allowlist_filter_enforcement.sh`
- `tools/tests/test_router_vs_fallback_mode_drift_monitor.sh`
- `tools/tests/test_query_policy_shared_heuristics.sh`
- Manual SSRF/hostname parsing/allowlist bypass probe set

### FAIL / Needs Review
Official trust probe (`tools/trust/probe_trust_sites.py`) after compatibility patch:
- Script execution: works
- Final status: exits with `GATE_FAIL=2`

Gate expectation failures:
1. `idf.il`
- catalog domain: `idf.il`
- probe host: `www.idf.il`
- probe HTTP result: reachable (`200`)
- gate result: `other_error` / `FAIL_POLICY`

2. `texasinstruments.com`
- catalog domain: `texasinstruments.com`
- probe host: `ti.com`
- probe HTTP result: reachable (`200`)
- gate result: `other_error` / `FAIL_POLICY`

Interpretation:
- The probe can reach these sites, but gate validation fails on host/domain canonicalization (alias mismatch).
- Candidate fix area is trust probe expectation logic or gate alias handling, depending intended policy semantics.

## 6. Trust Probe Harness Fix (Applied This Session)
File patched:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/trust/probe_trust_sites.py`

Changes:
- `detect_root()` now respects `LUCY_ROOT`
- `load_policy()` now parses top-level multiline YAML lists in `config/trust/policy.yaml`

Why needed:
- Existing parser expected only single-line `key: value` YAML and failed on current policy entries like:
  - `primary_doc_prefer_domains:`
  - `  - "ti.com"`

Validation:
- `python3 -m py_compile /home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/trust/probe_trust_sites.py` (PASS)

## 7. Allowed-Site Coverage (Custom Live Sweep)
A custom live probe covered all domains in:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/config/trust/generated/allowlist_fetch.txt`

Summary:
- Total domains: `62`
- DNS OK: `60`
- TCP:443 OK: `59`
- HTTPS reachable (`HEAD` success or HTTP status response): `54`
- 2xx/3xx: `36`
- 4xx/5xx but reachable: `18`

Artifact:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/live_allowlist_probe/allowlist_fetch_probe_latest.json`

Observed non-pass domains in that run (volatile/upstream conditions):
- `analog.com`
- `eia.gov`
- `feeds.washingtonpost.com`
- `gov.il`
- `idf.il`
- `st.com`
- `texasinstruments.com`
- `washingtonpost.com`

Note:
- The later official trust probe showed HTTP reachability for several of these, confirming environment/upstream variability across runs.

## 8. Key Logs and Artifacts for ChatGPT Review
### Handoffs / session context
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T18-33-50+0200.md`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T19-19-56+0200.md`

### Full regression / verification
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/logs/verify_all_dev_evidence_tools_v1.2026-02-26T19_14_52+02_00.log`

### Internet E2E
- `/tmp/internet-e2e/log.txt`

### Official trust probe (post-fix)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/trust_probe/20260226T191938+0200/report.md`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/trust_probe/20260226T191938+0200/results.json`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/trust_probe/20260226T191938+0200/results.csv`

### Custom allowlist live probe
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/live_allowlist_probe/allowlist_fetch_probe_latest.json`

## 9. Suggested Review Focus for ChatGPT
Please review and prioritize:
1. Trust/gate alias canonicalization semantics
- Should `idf.il` implicitly allow `www.idf.il`?
- Should `texasinstruments.com` probe/gate pass when `probe_host=ti.com`?
- If yes, where is the correct fix: trust catalog entries, generated allowlists, gate matcher, or probe expectations?

2. Trust probe expectations vs runtime policy
- Are `probe_host` values intended to be independently allowlisted, or just probe-only transport aliases?
- Should `probe_trust_sites.py` gate-check the catalog domain instead of `probe_host` for certain alias mappings?

3. Regression coverage gaps
- Is there a missing targeted regression specifically for alias/canonicalization gate behavior in trust probes?

4. Safety review of borderlines
- Confirm no missed URL parser variants in `url_safety.py` / `run_fetch_with_gate.sh` beyond those tested.

## 10. Commands Used (Selected)
```bash
cd /home/mike/lucy/snapshots/opt-experimental-v2-dev
./tools/internet/searxng_ensure_up.sh
./tools/full_regression_v2.sh
./tools/internet/internet_e2e_accept.sh
./tools/internet/all_systems_regression.sh
```

```bash
cd /home/mike/lucy/snapshots/opt-experimental-v2-dev
./tools/tests/test_fetch_gate_url_safety_unified.sh
./tools/tests/test_router_allowlist_filter_enforcement.sh
./tools/tests/test_router_vs_fallback_mode_drift_monitor.sh
./tools/tests/test_query_policy_shared_heuristics.sh
```

```bash
cd /home/mike/lucy/snapshots/opt-experimental-v2-dev
LUCY_ROOT=/home/mike/lucy/snapshots/opt-experimental-v2-dev python3 tools/trust/probe_trust_sites.py
```

## 11. Current Files Changed in This Session (Relevant)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/trust/probe_trust_sites.py` (compatibility fix)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T19-19-56+0200.md` (handoff)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/CHATGPT_REVIEW_REPORT_opt_experimental_v2_dev_live_battery_2026-02-26T19-22-03+0200.md` (this report)
