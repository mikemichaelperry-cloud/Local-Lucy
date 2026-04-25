# Baseline (Before Changes)
Date: February 21, 2026

Commands run:
- python3 tools/trust/generate_trust_lists.py
- tools/trust/verify_trust_lists.sh
- tools/full_regression_v2.sh

Observed state:
- generate_trust_lists.py: PASS
- verify_trust_lists.sh: PASS
- full_regression_v2.sh: FAIL
  - failure point: "fetch boi.org.il did not look like HTML"
