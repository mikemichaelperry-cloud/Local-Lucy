# Local Lucy UI Post-Install Verification Report
Timestamp: 2026-03-20T18:39:49+0200

## Scope
- UI venv root: `/home/mike/lucy/ui/.venv`
- App root: `/home/mike/lucy/ui/app`
- Local Lucy runtime code: untouched
- Launcher / governor / routing integration: not added

## Verification Results
- `python -c "import PySide6; print(PySide6.__version__)"`: PASS (`6.10.2`)
- `which pyside6-designer`: PASS (`/home/mike/lucy/ui/.venv/bin/pyside6-designer`)
- `which pyside6-uic`: PASS (`/home/mike/lucy/ui/.venv/bin/pyside6-uic`)
- `which pyside6-rcc`: PASS (`/home/mike/lucy/ui/.venv/bin/pyside6-rcc`)
- `which pyside6-project`: PASS (`/home/mike/lucy/ui/.venv/bin/pyside6-project`)
- `pyinstaller --version || true`: PASS (`6.19.0`)
- `python -m py_compile /home/mike/lucy/ui/app/main.py`: PASS

## Smoke Test Result
- Deterministic launch command used for verification:
  - `cd /home/mike/lucy/ui`
  - `source .venv/bin/activate`
  - `PYTHONPATH=. python app/main.py --smoke-test`
- Result: PASS
- Evidence:
  - process exit code `0`
  - startup marker printed: `SMOKE_TEST_WINDOW_SHOWN`

## Desktop Display Launch Result
- Host fix applied:
  - `sudo apt-get install -y libxcb-cursor0`
- Real display launch verification:
  - `cd /home/mike/lucy/ui`
  - `source .venv/bin/activate`
  - `PYTHONPATH=. python -c "from PySide6.QtCore import QTimer; from PySide6.QtWidgets import QApplication; from app.main import OperatorConsoleWindow; import sys; app = QApplication(sys.argv); window = OperatorConsoleWindow(); window.show(); print('VISIBLE_WINDOW_SHOWN', flush=True); QTimer.singleShot(800, app.quit); raise SystemExit(app.exec())"`
- Result: PASS
- Evidence:
  - process exit code `0`
  - startup marker printed: `VISIBLE_WINDOW_SHOWN`

## Manual Run Command Example
- `cd /home/mike/lucy/ui`
- `source .venv/bin/activate`
- `PYTHONPATH=. python app/main.py`

## Notes
- The smoke-test path uses Qt's offscreen platform automatically so the verification stays deterministic and self-terminating.
- The earlier desktop-display blocker was a host Qt/X11 dependency issue, not an application bug. Installing `libxcb-cursor0` resolved it.
