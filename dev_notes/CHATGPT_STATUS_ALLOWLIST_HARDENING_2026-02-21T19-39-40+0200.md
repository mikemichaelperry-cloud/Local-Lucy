# ChatGPT Status Report: Allowlist Stabilization and Fetch Hardening
Date: February 21, 2026

## Current Status
- Allowlist source of truth is now YAML-only:
  - `/home/mike/lucy/snapshots/opt-experimental-v1/config/trust/trust_catalog.yaml`
  - `/home/mike/lucy/snapshots/opt-experimental-v1/config/trust/policy.yaml`
- Runtime allowlist is generated from YAML:
  - `/home/mike/lucy/snapshots/opt-experimental-v1/config/trust/generated/allowlist_fetch.txt`
- Legacy allowlist file removed:
  - `/home/mike/lucy/snapshots/opt-experimental-v1/config/fetch_domains_allowlist.txt`
- Regression and health status are currently green after changes.

## What Was Changed
1. Removed legacy allowlist dependency from runtime
- Updated code to stop using/falling back to `config/fetch_domains_allowlist.txt`.
- Enforced generated trust allowlist as required input.

Files changed:
- `/home/mike/lucy/snapshots/opt-experimental-v1/lucy_chat.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v1/tools/fetch_url_allowlisted.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v1/tools/internet/run_fetch_with_gate.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v1/tools/internet/run_fetch_with_gate_v1.sh`

2. Fixed allowlist drift bug in chat pre-check path
- `lucy_chat.sh` previously checked the legacy list while fetch path checked generated trust list.
- Now both paths consistently resolve to generated fetch allowlist.

3. Hardened live fetch behavior to reduce false fetch failures
- Added browser-like headers, longer timeouts, retry, and HTTP/1.1 fallback.
- Relaxed strict `curl -f` behavior where it was causing unnecessary failures.
- Kept policy enforcement intact (allowlist + redirect final-domain gate).

Files changed:
- `/home/mike/lucy/snapshots/opt-experimental-v1/tools/internet/run_fetch_with_gate.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v1/tools/fetch_url_allowlisted.sh`

4. Updated trust probe classification
- HTTP error responses (401/403/412/418, etc.) are now treated as network-reachable outcomes, not DNS/network failures.
- Gate expectation checking remains strict.

File changed:
- `/home/mike/lucy/snapshots/opt-experimental-v1/tools/trust/probe_trust_sites.py`

## Why These Changes Were Made
- Root cause was policy/source drift: different code paths used different allowlists.
- This caused inconsistent behavior (`blocked_domain` in one path while another path allowed/fetched).
- Additional real-world instability came from strict fetch assumptions (status-code and protocol sensitivity).
- Hardening was added to improve reliability without loosening security policy.

## Verification Results
1. Core verification and regression
- `tools/trust/verify_trust_lists.sh`: PASS
- `tools/sha_manifest.sh regen`: PASS
- `tools/full_regression_v2.sh`: PASS

2. Full health battery
- `tools/health_battery.sh --keep-going`: PASS
- Summary:
  - `/home/mike/lucy/snapshots/opt-experimental-v1/tmp/test_reports/health_battery/20260221T193640+0200/summary.txt`

3. Trust probe (post-hardening)
- `tools/trust/probe_trust_sites.py`
- Result:
  - `TOTAL=60`
  - `GATE_FAIL=0`
  - `DNS failures=1`
  - `HTTPS request failures=7`
- Report:
  - `/home/mike/lucy/snapshots/opt-experimental-v1/tmp/test_reports/trust_probe/20260221T193709+0200/report.md`

4. Full allowlist sweep improvement (live)
- Pre-hardening sweep:
  - `pass=33/57`, `fetch_fail=22`, `timeout=2`
- Post-hardening sweep:
  - `pass=53/57`, `fetch_fail=2`, `timeout=2`
- Post-hardening report:
  - `/home/mike/lucy/snapshots/opt-experimental-v1/tmp/test_reports/allowlist_sweep_fast/20260221T193551+0200/results.tsv`

## Remaining External Failures
The remaining non-pass domains appear environmental/upstream rather than allowlist policy errors:
- `gov.il` (connection refused)
- `idf.il` (DNS no address)
- `eia.gov` (timeout)
- `feeds.washingtonpost.com` (timeout)

## End-to-End Behavioral Check
- Allowlisted URL fetch works in NL chat (example: `https://reuters.com`).
- Non-allowlisted URL remains correctly blocked (example: `https://example.com`).

## Recommended Operational Rule
- Continue editing only:
  - `/home/mike/lucy/snapshots/opt-experimental-v1/config/trust/trust_catalog.yaml`
  - `/home/mike/lucy/snapshots/opt-experimental-v1/config/trust/policy.yaml`
- Regenerate + verify after trust changes:
  1. `/home/mike/lucy/snapshots/opt-experimental-v1/tools/trust/generate_trust_lists.py`
  2. `/home/mike/lucy/snapshots/opt-experimental-v1/tools/trust/verify_trust_lists.sh`
  3. `/home/mike/lucy/snapshots/opt-experimental-v1/tools/sha_manifest.sh regen`
  4. `/home/mike/lucy/snapshots/opt-experimental-v1/tools/full_regression_v2.sh`
