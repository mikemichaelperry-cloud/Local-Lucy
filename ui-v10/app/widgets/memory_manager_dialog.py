"""Memory Manager Dialog — Qt UI for persistent_facts CRUD."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

# Import memory_service from the tools tree
TOOLS_ROOT = Path(__file__).resolve().parents[3] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from memory.memory_service import (
    delete_persistent_fact,
    get_persistent_facts,
    store_persistent_fact,
)


class MemoryManagerDialog(QDialog):
    """Modal dialog for viewing and editing Lucy's persistent facts."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Memory Facts")
        self.setMinimumSize(480, 360)
        self._apply_stylesheet()
        self._build_ui()
        self._refresh_list()

    def _apply_stylesheet(self) -> None:
        """Apply dark theme matching the operator console."""
        self.setStyleSheet("""
            QDialog {
                background: #1a2229;
            }
            QLabel {
                color: #d8e0e6;
                font-size: 13px;
            }
            QListWidget {
                background: #12191f;
                color: #d8e0e6;
                border: 1px solid #33424d;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 4px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background: #2b3b46;
                color: #ecf2f6;
            }
            QLineEdit {
                background: #12191f;
                border: 1px solid #33424d;
                border-radius: 6px;
                color: #d8e0e6;
                padding: 6px;
                font-size: 13px;
            }
            QPushButton {
                background: #2b3b46;
                border: 1px solid #445764;
                border-radius: 6px;
                color: #ecf2f6;
                min-height: 34px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #334753;
            }
            QPushButton:disabled {
                background: #212b33;
                color: #7f8d97;
                border-color: #37434c;
            }
        """)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header = QLabel(
            "These facts are injected into every LOCAL prompt.\n"
            "Lucy uses them to answer questions about you and your family."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.itemSelectionChanged.connect(self._update_delete_button_state)
        layout.addWidget(self._list)

        # Add fact row
        add_layout = QHBoxLayout()
        self._new_fact_input = QLineEdit()
        self._new_fact_input.setPlaceholderText("Enter a new fact (e.g. 'Mike likes jazz')...")
        add_layout.addWidget(self._new_fact_input)

        self._add_button = QPushButton("Add Fact")
        self._add_button.clicked.connect(self._on_add)
        add_layout.addWidget(self._add_button)
        layout.addLayout(add_layout)

        # Action buttons
        btn_layout = QHBoxLayout()
        self._delete_button = QPushButton("Delete Selected")
        self._delete_button.clicked.connect(self._on_delete)
        self._delete_button.setEnabled(False)
        btn_layout.addWidget(self._delete_button)

        btn_layout.addStretch(1)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        btn_layout.addWidget(close_button)
        layout.addLayout(btn_layout)

    def _refresh_list(self) -> None:
        self._list.clear()
        try:
            facts = get_persistent_facts()
            for i, text in enumerate(facts, 1):
                item = QListWidgetItem(f"{i}. {text}")
                item.setData(Qt.UserRole, i)  # store 1-based index
                self._list.addItem(item)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load facts: {e}")
        self._update_delete_button_state()

    def _update_delete_button_state(self) -> None:
        self._delete_button.setEnabled(self._list.currentItem() is not None)

    def _on_add(self) -> None:
        text = self._new_fact_input.text().strip()
        if not text:
            return
        try:
            store_persistent_fact(text)
            self._new_fact_input.clear()
            self._refresh_list()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add fact: {e}")

    def _on_delete(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        row = self._list.row(item)
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete this fact?\n\n{item.text()}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            # We need the actual DB id, not the row index.
            # get_persistent_facts returns ordered by id, so row maps to the list index.
            facts = get_persistent_facts()
            if 0 <= row < len(facts):
                # Find the id by querying all facts with ids
                import sqlite3
                from memory.memory_service import _get_connection

                conn = _get_connection()
                cur = conn.execute("SELECT id FROM persistent_facts ORDER BY id")
                ids = [r[0] for r in cur.fetchall()]
                if 0 <= row < len(ids):
                    delete_persistent_fact(ids[row])
                    self._refresh_list()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete fact: {e}")
