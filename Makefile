# Local Lucy v10 — Task Runner
# ============================================

.PHONY: help install test lint run clean check-env

PYTHON := ui-v10/.venv/bin/python3
PIP := ui-v10/.venv/bin/pip

help:
	@echo "Local Lucy v10 — Available targets:"
	@echo "  make install      Create venv and install dependencies"
	@echo "  make test         Run full pytest suite"
	@echo "  make lint         Run ruff (and mypy if installed)"
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
	QT_QPA_PLATFORM=offscreen $(PYTHON) -m pytest -q \
		--ignore=tools/router_py/test_synthetic_adversarial.py

lint:
	@echo "[lint] Running ruff..."
	ruff check tools/router_py/ models/router/ ui-v10/app/ web_adapter/
	@echo "[lint] Running mypy..."
	mypy tools/router_py/ --ignore-missing-imports

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
