## Fast-test workflow (added after Phase 8 review)

To avoid waiting for the slow/live-LLM tests during routine development:

```bash
cd /home/mike/lucy-v11
./scripts/run-fast-tests.sh
```

This runs the default `tools/router_py/` suite with `@pytest.mark.slow` and `@pytest.mark.live` tests excluded.

To run the full suite, including slow/live tests:

```bash
python3 -m pytest tools/router_py/ -m "" -q --tb=line
```
