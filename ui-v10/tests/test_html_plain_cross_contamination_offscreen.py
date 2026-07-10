#!/usr/bin/env python3
"""Regression test: HTML → plain-text transition must clear the document.

After a NEWS response containing URLs sets HTML in the QTextBrowser, a
subsequent LOCAL response that calls setPlainText must first call clear()
on the widget.  QTextBrowser reuses the same QTextDocument across
setHtml/setPlainText calls, so document-level state (styles, resource cache,
link colouring) can leak without an explicit clear().

This test verifies the `widget.clear()` guard in `_set_plain_text`.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="html_xcontam_") as tmp_dir:
        home = Path(tmp_dir) / "home"
        home.mkdir(parents=True)
        os.environ["HOME"] = str(home)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["LUCY_UI_ROOT"] = str(REPO_UI_ROOT)
        sys.path.insert(0, str(REPO_UI_ROOT))

        from app.panels.conversation_panel import ConversationPanel
        from PySide6.QtWidgets import QApplication

        app = QApplication([])
        panel = ConversationPanel()
        history = panel._history

        # Phase 1 — set HTML with URLs (NEWS path)
        news_text = "Sources:\n" "- https://nytimes.com/article-1\n" "- https://bbc.co.uk/article-2"
        panel._set_plain_text(history, news_text, reset_scroll=False)
        app.processEvents()
        assert "<a" in history.toHtml(), "NEWS text should render as HTML with <a> tags"

        # Phase 2 — spy on clear() during the plain-text switch
        original_clear = history.clear
        call_log: list[bool] = []

        def spied_clear() -> None:
            call_log.append(True)
            original_clear()

        history.clear = spied_clear  # type: ignore[method-assign]
        try:
            local_text = "Latest Request\n" "What is 2+2?\n\n" "Latest Answer\n" "The sum is 4."
            panel._set_plain_text(history, local_text, reset_scroll=False)
            app.processEvents()
        finally:
            history.clear = original_clear  # type: ignore[method-assign]

        assert call_log, (
            "_set_plain_text must call widget.clear() before switching from HTML "
            "to plain text to prevent document-level state leakage."
        )

        # Phase 3 — sanity-check the final content
        plain = history.toPlainText()
        assert "Latest Request" in plain, f"'Latest Request' missing: {plain!r}"
        assert "Latest Answer" in plain, f"'Latest Answer' missing: {plain!r}"
        assert "<a" not in history.toHtml(), "Plain text must not contain <a> tags"

        panel.deleteLater()
        app.processEvents()
        print("HTML_PLAIN_CROSS_CONTAMINATION_OFFSCREEN_OK")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
