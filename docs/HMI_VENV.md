# HMI Virtual Environment (`ui-v8/.venv`)

Local Lucy v8 uses a single Python virtual environment located at **`ui-v8/.venv`**. This document explains why it lives inside `ui-v8/`, what it contains, and how to verify it.

---

## Why `ui-v8/.venv`?

The venv is nested under `ui-v8/` for historical reasons:

1. **Origin:** The venv was originally created for the PySide6 desktop HMI (Human-Machine Interface) in `ui-v8/app/`. It contains `PySide6` and the Qt stack required to run the GUI.
2. **Evolution:** Over time it also became the project's heavy-ML dependency home — `torch`, `transformers`, `kokoro`, and `sentence-transformers` are installed there because the HMI needs voice (TTS) and the router needs embeddings.
3. **Current reality:** Many backend tools, test suites, and voice pipelines now source this venv even though they have nothing to do with the GUI. It is the *de facto* project-wide ML environment.

> **We do not plan to move or rename it.** Dozens of launchers, test headers, and CI references hard-code `ui-v8/.venv`. The cost of migration exceeds the benefit.

---

## What It Contains

Key packages installed in `ui-v8/.venv`:

| Package | Purpose |
|---------|---------|
| `PySide6` | Desktop GUI (HMI) |
| `torch` | PyTorch — used by Kokoro TTS and ModernBERT embeddings |
| `transformers` | HuggingFace transformers — ModernBERT tokenizer/model |
| `sentence-transformers` | Embedding model comparison / future candidate |
| `kokoro` | TTS engine (Kokoro) |
| `soundfile` | Audio I/O for Kokoro |
| `numpy`, `scikit-learn` | Math / similarity for router |
| `pytest`, `pytest-asyncio` | Test runner |

Full list: see `ui-v8/requirements.txt`.

---

## Verification

### 1. Check that the venv exists

```bash
ls ui-v8/.venv/bin/python3
# Expected: ui-v8/.venv/bin/python3
```

### 2. Show the active Python path

```bash
# From project root
ui-v8/.venv/bin/python3 -c "import sys; print(sys.executable)"
# Expected: /home/mike/lucy-v8/ui-v8/.venv/bin/python3
```

### 3. Verify key imports

```bash
ui-v8/.venv/bin/python3 -c "import torch; import transformers; import kokoro; print('OK')"
```

### 4. Run the test suite

```bash
cd ~/lucy-v8
source ui-v8/.venv/bin/activate
python -m pytest tools/router_py/ --ignore=tools/router_py/test_resource_leaks.py -q
```

---

## Files That Reference `ui-v8/.venv`

The following launchers and scripts expect the venv at exactly this path:

| File | Reference |
|------|-----------|
| `START_LUCY.sh` | `V8_PYTHON="${SCRIPT_DIR}/ui-v8/.venv/bin/python3"` |
| `README.md` | Setup instructions create venv at `ui-v8/.venv` |
| `CONTRIBUTING.md` | Dev setup uses `ui-v8/.venv` |
| `tools/lucy_voice_ptt.sh` | Falls back to `ui-v8/.venv/bin/python3` |
| `tools/diagnostics/check_gpu_allocation.sh` | `VENV_PYTHON=".../ui-v8/.venv/bin/python"` |
| Multiple test files in `tools/tests/` and `tools/router_py/` | Docstring headers reference `source ui-v8/.venv/bin/activate` |

---

## Notes for Contributors

- **Do not create a second venv at the project root.** Use `ui-v8/.venv` for all Python work.
- **Do not rename or move `ui-v8/.venv`.** If you need a different Python version, create a new venv inside `ui-v8/` with a different name (e.g., `ui-v8/.venv-3.11`) and update `START_LUCY.sh` locally — but do not commit the rename.
- The venv is **not tracked by Git**. It is rebuilt from `ui-v8/requirements.txt` after clone.
