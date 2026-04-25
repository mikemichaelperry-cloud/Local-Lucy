"""ROLE: PRIMARY AUTHORITATIVE ENTRYPOINT.
HMI operator console for Local Lucy.
Preferred HMI start surface for new workflows.
"""

import argparse
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.main_window import OperatorConsoleWindow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Lucy authoritative operator console.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Launch the window and auto-exit shortly after showing it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.smoke_test and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    app = QApplication(sys.argv)
    window = OperatorConsoleWindow()
    window.show()

    if args.smoke_test:
        print("LOCAL_LUCY_UI_WINDOW_SHOWN", flush=True)
        QTimer.singleShot(900, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
