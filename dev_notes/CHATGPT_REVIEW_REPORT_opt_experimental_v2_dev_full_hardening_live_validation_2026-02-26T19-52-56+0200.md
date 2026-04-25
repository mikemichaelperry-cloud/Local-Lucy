# ChatGPT Review Report: Opt Experimental v2 Dev (Full Hardening + Live Validation + False-Positive Fix)
Date: February 26, 2026
Time: 19:52:56 +0200

## 1. Purpose
Comprehensive review package for ChatGPT covering:
- latest session lineage / handoff context
- full local + live internet validation battery
- strict host enforcement hardening (`www.`/case/trailing-dot normalization without alias sprawl)
- new alias-behavior regression coverage
- trust probe harness fixes and improved diagnostics
- root-cause + patch for `url_safety.py` DNS-failure false positives
- final post-fix status (including official trust probe)

## 2. Snapshot / Scope
- Active snapshot:
  - `/home/mike/lucy/snapshots/opt-experimental-v2-dev`
- Frozen baseline (unchanged):
  - `/home/mike/lucy/snapshots/FROZEN/opt-experimental-v1-FROZEN-20260224`

Primary handoffs in this sequence:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T18-28-44+0200.md`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T18-33-50+0200.md`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T19-19-56+0200.md`

## 3. Executive Summary (Final Status)
Current system status is strong.

Final validated outcomes:
- Full regression suite: PASS
- Live internet E2E acceptance: PASS
- Internet/evidence systems regression: PASS
- Targeted guardrail regressions: PASS
- Manual hostile/borderline URL probes: PASS
- New alias-behavior regression: PASS
- `SHA256SUMS` manifest: refreshed and verified
- Official trust probe (`probe_trust_sites.py`): PASS with `GATE_FAIL=0` after final URL-safety false-positive fix

What changed during this work:
1. Strict host enforcement semantics tightened and clarified (without broadening trust)
2. Trust allowlists now include deterministic `www.` variants
3. Trust probe harness fixed (policy parser + `LUCY_ROOT` support + clearer gate failure classification)
4. `url_safety.py` false positives fixed for public domains on transient DNS resolution failures

Remaining non-system failures in trust probe are external/upstream:
- `aljazeera.com` TLS hostname mismatch (probe expectation failure)
- `presstv.ir` timeout (probe expectation failure)

## 4. What Was Requested / Validation Goals
The goal was to verify no regressions/breakage after recent router/trust/fetch hardening by running:
- full regression
- live internet tests with full permissions and internet access
- borderline / break-through probes
- broad allowed-site coverage

Then to:
- implement ChatGPT-recommended strict host semantics (`www.` normalization + explicit alias policy)
- retest with same permissions/internet access
- investigate and fix remaining false positives

## 5. Full Validation Battery Executed
### Core + Live Suites
Executed in `/home/mike/lucy/snapshots/opt-experimental-v2-dev`:
- `./tools/internet/searxng_ensure_up.sh`
- `./tools/full_regression_v2.sh`
- `./tools/internet/internet_e2e_accept.sh`
- `./tools/internet/all_systems_regression.sh`

Results:
- PASS before alias-policy hardening
- PASS again after alias-policy hardening and retest

Verification sweep log (post-hardening rerun):
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/logs/verify_all_dev_evidence_tools_v1.2026-02-26T19_34_01+02_00.log`

Internet E2E log:
- `/tmp/internet-e2e/log.txt`

### Targeted Guardrail Regressions (PASS)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_fetch_gate_url_safety_unified.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_router_allowlist_filter_enforcement.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_router_vs_fallback_mode_drift_monitor.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_query_policy_shared_heuristics.sh`

### Manual Hostile / Borderline Probes (PASS)
Live probes against:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/internet/run_fetch_with_gate.sh`

Confirmed blocked:
- `localhost`, `127.0.0.1`, `127.1`
- IPv4 dword (`2130706433`)
- hex IP (`0x7f000001`)
- octal-ish IP (`0177.0.0.1`)
- userinfo trick (`user@127.0.0.1`)
- IPv6 loopback (`[::1]`)
- `0.0.0.0`
- metadata IP (`169.254.169.254`)
- suffix trick (`wikipedia.org.evil.com`)

Confirmed allowed:
- `https://en.wikipedia.org/wiki/Test`
- after normalization patch:
  - `https://WWW.WIKIPEDIA.ORG/wiki/Test`
  - `https://www.wikipedia.org./wiki/Test`

## 6. Policy Semantics Hardening Implemented (ChatGPT-aligned)
### Agreed policy model
Implemented the recommended strict approach:
- normalize syntax variants only (`www.`, case, trailing dot)
- keep explicit allowlisting semantics
- do **not** implicitly trust brand aliases (e.g. `ti.com` remains separate from `texasinstruments.com`)

### Code changes
Files changed:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/net/bin/allow_check.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/net/bin/url_domain.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/internet/run_fetch_with_gate.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/trust/generate_trust_lists.py`

Behavior changes:
- host comparisons are case-insensitive
- leading `www.` normalized for matching
- trailing root dot normalized (`example.com.` -> `example.com`)
- generated trust allowlists now include base + `www.` variants for each listed domain
- no automatic alias expansion beyond `www.`

### New regression added (PASS)
File:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_fetch_gate_alias_behavior.sh`

Covers:
- `www.` variant allowed when base domain is allowlisted
- case-insensitive host match
- trailing-dot normalization
- suffix attack blocked
- `ti.com` blocked unless explicitly allowlisted (no implicit alias trust)

## 7. Trust Probe Harness: Fixes and Diagnostics Improvements
### Initial harness issues fixed
File:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/trust/probe_trust_sites.py`

Fixes:
- `detect_root()` now honors `LUCY_ROOT`
- `load_policy()` supports top-level multiline YAML list values in current `config/trust/policy.yaml`
- canonical mapping for generated `www.` allowlist variants back to catalog domains (avoids catalog lookup mismatch)

### Diagnostic improvement added
`probe_trust_sites.py` now classifies gate failures with `gate_failure_class`, including:
- `URL_SAFETY_POLICY_BLOCK`
- `ALLOWLIST_MISMATCH`
- `POLICY_BLOCK_OTHER`
- `GATE_OTHER_ERROR`

This avoids conflating policy blocks with allowlist alias mismatches.

## 8. URL Safety False-Positive Root Cause + Fix
### Observed problem
Official trust probe initially showed 2 gate failures:
- `idf.il`
- `texasinstruments.com`

Direct gate output showed:
- `blocked: local/meta/ssrf target`
- `reason=FAIL_POLICY`

Root cause in `url_safety.py`:
- DNS resolution failure (`dns resolution failed`) was treated as a policy violation
- That caused false positives for public domains during local DNS flakiness

### Fix implemented
File:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/internet/url_safety.py`

Change:
- DNS failures / no resolved addresses are no longer treated as policy violations
- URL safety still blocks:
  - localhost names
  - metadata IP
  - IP literals
  - hostnames resolving to forbidden/private/link-local/loopback/etc.

Rationale:
- DNS transport failure is not evidence of SSRF/local routing
- Fetch layer should classify transport/network failure, not policy layer

### New regression added (PASS)
File:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_url_safety_dns_failure_not_policy_block.sh`

Deterministic coverage:
- simulates DNS failure for a public hostname (`example.com`) and asserts no policy block
- verifies localhost / IP literal targets remain blocked

## 9. Official Trust Probe Results (Before/After)
### Before URL safety false-positive fix
Runs produced `GATE_FAIL=2`
- Failures were reclassified (correctly) as `URL_SAFETY_POLICY_BLOCK`
- Domains:
  - `idf.il`
  - `texasinstruments.com`

Artifacts (diagnostic-classification version):
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/trust_probe/20260226T193805+0200/report.md`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/trust_probe/20260226T193805+0200/results.json`

### After URL safety false-positive fix (current)
Command:
```bash
LUCY_ROOT=/home/mike/lucy/snapshots/opt-experimental-v2-dev python3 tools/trust/probe_trust_sites.py
```

Result:
- `GATE_FAIL=0` (resolved)
- Probe expectation failures remain `2` (external/upstream)

Current artifacts:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/trust_probe/20260226T195158+0200/report.md`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/trust_probe/20260226T195158+0200/results.json`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/trust_probe/20260226T195158+0200/results.csv`

Key report lines (current):
- Gate expectation failures: `0`
- Probe expectation failures: `2`
- Gate failures section: `None`

## 10. Allowed-Site Coverage (Custom Live Sweep)
Custom live sweep was used earlier to probe all domains in:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/config/trust/generated/allowlist_fetch.txt`

Post-`www.` expansion, total entries increased (base + `www.` variants).
Example rerun summary (expanded allowlist):
- `total=124`
- `dns_ok=117`
- `tcp_ok=116`
- `http_ok=104`

Artifact:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/test_reports/live_allowlist_probe/allowlist_fetch_probe_latest.json`

Interpretation:
- This sweep is useful for broad reachability smoke coverage, but official trust probe output is the stronger policy/gate signal.
- Expected external volatility remains (timeouts/TLS/site-specific behavior).

## 11. Files Changed in This Review Cycle (Key)
### Gate / matching / normalization
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/net/bin/allow_check.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/net/bin/url_domain.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/internet/run_fetch_with_gate.sh`

### URL safety
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/internet/url_safety.py`

### Trust generation / probing
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/trust/generate_trust_lists.py`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/trust/probe_trust_sites.py`

### Tests (new/updated)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_fetch_gate_alias_behavior.sh` (new)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_url_safety_dns_failure_not_policy_block.sh` (new)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_router_allowlist_filter_enforcement.sh` (updated to avoid live-DNS flakiness in unit-style assertions)

### Manifest / notes
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/SHA256SUMS` (regenerated + verified)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T19-19-56+0200.md`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/CHATGPT_REVIEW_REPORT_opt_experimental_v2_dev_live_battery_2026-02-26T19-22-03+0200.md`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/CHATGPT_REVIEW_REPORT_opt_experimental_v2_dev_full_hardening_live_validation_2026-02-26T19-52-56+0200.md` (this file)

## 12. What ChatGPT Should Review (Priority)
1. Policy semantics sanity (implemented path)
- Confirm `www.` / case / trailing-dot normalization is the right strict compromise
- Confirm explicit alias-only trust policy remains intact (`ti.com` not implied by `texasinstruments.com`)

2. URL safety false-positive fix correctness
- Confirm allowing DNS failures to fall through to fetch-layer classification does not weaken SSRF guarantees
- Validate that resolved-forbidden-network checks still fail closed

3. Trust probe diagnostics quality
- Confirm `gate_failure_class` taxonomy is useful and sufficient
- Suggest any additional distinctions (e.g., TLS policy vs URL policy vs allowlist)

4. Regression completeness
- Evaluate whether additional URL parsing edge regressions should be added (IDN punycode, trailing dot on more hosts, mixed-case + userinfo combos, newline/encoding oddities)

## 13. Bottom Line
System status is now materially stronger and cleaner than at the start of this sequence:
- Security enforcement remains strict
- Host matching semantics are clarified and deterministic
- No implicit trust broadening was introduced
- Live validation remains green
- Official trust probe gate failures are resolved (`GATE_FAIL=0`)

The remaining trust probe failures are external site behavior (TLS mismatch / timeout), not local gate/policy regressions.
