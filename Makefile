# Local Lucy v10 — Task Runner
# ============================================

.PHONY: help install test lint run clean check-env sha

PYTHON := ui-v10/.venv/bin/python3
PIP := ui-v10/.venv/bin/pip

help:
	@echo "Local Lucy v10 — Available targets:"
	@echo "  make install      Create venv and install dependencies"
	@echo "  make test         Run full pytest suite"
	@echo "  make lint         Run ruff check and format validation"
	@echo "  make sha          Regenerate and verify SHA256SUMS manifests"
	@echo "  make run          Launch desktop app"
	@echo "  make clean        Remove generated artifacts"
	@echo "  make check-env    Validate environment (Ollama, models, CUDA)"

install:
	@echo "[install] Creating virtual environment..."
	python3 -m venv ui-v10/.venv
	$(PIP) install --upgrade pip
	$(PIP) install -r ui-v10/requirements.txt
	$(PIP) install -r models/router/requirements.txt
	$(PIP) install -e .
	@echo "[install] Done. Run 'make check-env' to verify."

test:
	@echo "[test] Running pytest suite..."
	OLLAMA_KEEP_ALIVE=0 QT_QPA_PLATFORM=offscreen $(PYTHON) -m pytest \
		-q \
		--ignore=tools/router_py/test_synthetic_adversarial.py \
		--ignore=tools/router_py/test_real_router_burn_in.py \
		--ignore=tools/tests/test_end_to_end_comprehensive.py \
		--deselect web_adapter/test_web_adapter.py::test_ask_integration_local \
		-W error::pytest.PytestReturnNotNoneWarning

lint:
	@echo "[lint] Running ruff..."
	ruff check .
	ruff format --check .

sha:
	@echo "[sha] Regenerating SHA256SUMS manifests..."
	bash tools/sha_manifest.sh regen
	cd ui-v10 && bash tools/sha_manifest.sh regen
	bash tools/tests/test_sha_manifest_discipline.sh
	bash ui-v10/tests/test_sha_manifest_discipline.sh

check-env:
	@echo "[check-env] Validating Local Lucy environment..."
	$(PYTHON) scripts/check_environment.py

run:
	@echo "[run] Launching Local Lucy..."
	bash START_LUCY.sh

clean:
	@echo "[clean] Removing generated artifacts..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete
	rm -rf tmp/
	rm -rf runtime/state/
	@echo "[clean] Done."
