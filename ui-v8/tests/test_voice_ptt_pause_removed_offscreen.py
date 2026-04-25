#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        print(f"ASSERTION FAILED: {message}", file=sys.stderr)
        raise SystemExit(1)


REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Set required runtime namespace root
    home = Path.home()
    os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(home / "lucy" / "runtime")
    # Set required authority contract variables
    os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(home / "lucy" / "snapshots" / "opt-experimental-v7-dev")
    os.environ["LUCY_UI_ROOT"] = str(REPO_UI_ROOT)
    os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
    sys.path.insert(0, str(REPO_UI_ROOT))

    from PySide6.QtWidgets import QApplication
    from app.main_window import OperatorConsoleWindow

    app = QApplication([])
    window = OperatorConsoleWindow()
    window.show()
    app.processEvents()

    control = window.control_panel
    assert_ok(not hasattr(control, "_voice_tts_pause_selector"), "voice ptt pause selector should be absent")
    assert_ok(control._voice_ptt_group is not None, "voice ptt group should initialize")
    assert_ok(control._voice_ptt_button is not None, "voice ptt button should initialize")

    window.close()
    app.processEvents()
    print("VOICE_PTT_PAUSE_REMOVED_OFFSCREEN_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
