#!/usr/bin/env python3
"""Offscreen visual and functional verification of MemoryManagerDialog."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault(
        "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
    )
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_UI_ROOT.parent))
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")
    sys.path.insert(0, str(REPO_UI_ROOT))
    # tools.memory.memory_service lives under REPO_UI_ROOT.parent / "tools"
    sys.path.insert(0, str(REPO_UI_ROOT.parent / "tools"))

    # Use a temp DB so we don't pollute real persistent_facts
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    os.environ["LUCY_MEMORY_DB_PATH"] = db_path

    # Ensure memory_service reloads its connection cache for this temp DB
    import memory.memory_service as memory_service

    memory_service._close_connection()
    memory_service._CONN_CACHE = None

    from app.widgets.memory_manager_dialog import MemoryManagerDialog
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget, QMessageBox, QPushButton

    app = QApplication.instance() or QApplication([])

    # --- Phase 1: Empty-state dialog ---
    dialog = MemoryManagerDialog()
    dialog.show()
    app.processEvents()

    assert_ok(dialog.windowTitle() == "Manage Memory Facts", f"title={dialog.windowTitle()!r}")
    assert_ok(dialog.width() >= 480, f"width={dialog.width()} < 480")
    assert_ok(dialog.height() >= 360, f"height={dialog.height()} < 360")

    list_widget = dialog._list
    assert_ok(isinstance(list_widget, QListWidget), "_list should be QListWidget")
    assert_ok(list_widget.count() == 0, f"list should start empty, got {list_widget.count()} items")

    input_field = dialog._new_fact_input
    assert_ok(isinstance(input_field, QLineEdit), "_new_fact_input should be QLineEdit")
    assert_ok(input_field.placeholderText() != "", "placeholder text should be set")

    add_btn = dialog._add_button
    assert_ok(isinstance(add_btn, QPushButton), "_add_button should be QPushButton")
    delete_btn = dialog._delete_button
    assert_ok(isinstance(delete_btn, QPushButton), "_delete_button should be QPushButton")

    # --- Phase 2: Add facts ---
    input_field.setText("Mike likes jazz")
    app.processEvents()
    add_btn.click()
    app.processEvents()

    assert_ok(list_widget.count() == 1, f"after add, count={list_widget.count()}")
    item_text = list_widget.item(0).text()
    assert_ok("Mike likes jazz" in item_text, f"item text={item_text!r}")
    assert_ok(input_field.text() == "", "input should clear after add")

    input_field.setText("Sarah is allergic to peanuts")
    add_btn.click()
    app.processEvents()

    assert_ok(list_widget.count() == 2, f"after second add, count={list_widget.count()}")
    item_text2 = list_widget.item(1).text()
    assert_ok("Sarah is allergic to peanuts" in item_text2, f"second item text={item_text2!r}")

    # --- Phase 3: Delete a fact ---
    list_widget.setCurrentRow(0)
    app.processEvents()

    # Monkey-patch QMessageBox.question to auto-confirm (avoid modal blocking in offscreen)
    original_question = QMessageBox.question
    QMessageBox.question = lambda *args, **kwargs: QMessageBox.Yes
    try:
        delete_btn.click()
        app.processEvents()
    finally:
        QMessageBox.question = original_question

    assert_ok(list_widget.count() == 1, f"after delete, count={list_widget.count()}")
    remaining_text = list_widget.item(0).text()
    assert_ok(
        "Sarah is allergic to peanuts" in remaining_text, f"remaining item={remaining_text!r}"
    )

    # --- Phase 4: Reject empty add ---
    input_field.setText("   ")
    add_btn.click()
    app.processEvents()
    assert_ok(list_widget.count() == 1, "empty add should be a no-op")

    # --- Phase 5: Visual capture ---
    # Force a reasonable size and re-layout
    dialog.resize(600, 450)
    dialog.show()
    app.processEvents()

    pixmap = QPixmap(dialog.size())
    dialog.render(pixmap)
    screenshot_path = REPO_UI_ROOT / "tests" / "memory_manager_dialog_offscreen.png"
    ok = pixmap.save(str(screenshot_path))
    assert_ok(ok, f"failed to save screenshot to {screenshot_path}")
    assert_ok(pixmap.width() == 600, f"screenshot width={pixmap.width()}")
    assert_ok(pixmap.height() == 450, f"screenshot height={pixmap.height()}")

    # Verify non-empty pixmap (not just black/transparent)
    image = pixmap.toImage()
    # Sample a few pixels; if they're all identical, something is wrong
    samples = [
        image.pixelColor(10, 10).rgba(),
        image.pixelColor(100, 100).rgba(),
        image.pixelColor(300, 200).rgba(),
        image.pixelColor(590, 440).rgba(),
    ]
    assert_ok(len(set(samples)) > 1, f"screenshot looks blank/uniform: {samples}")

    dialog.close()
    dialog.deleteLater()
    app.processEvents()

    # Cleanup temp DB
    Path(db_path).unlink(missing_ok=True)

    print("MEMORY_MANAGER_DIALOG_OFFSCREEN_OK")
    print(f"  Screenshot: {screenshot_path}")
    return 0


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
