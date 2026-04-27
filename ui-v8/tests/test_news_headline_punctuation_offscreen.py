#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


REPO_UI_ROOT = Path(__file__).resolve().parents[1]
REPO_TOOLS_ROOT = Path("/home/mike/lucy-v8/tools")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="news_punct_ui_") as tmp_dir:
        sandbox = Sandbox(Path(tmp_dir))
        sandbox.prepare_import_environment()
        sandbox.install_runtime_control_tool()
        sandbox.write_current_state()
        sandbox.write_runtime_lifecycle()
        sandbox.write_request_result()

        from PySide6.QtWidgets import QApplication
        from app.main_window import OperatorConsoleWindow

        app = QApplication([])
        window = OperatorConsoleWindow()
        window.resize(960, 720)
        window.show()
        app.processEvents()
        window.refresh_runtime_state()
        app.processEvents()

        answer_text = window.conversation_panel._history.toPlainText()
        assert_ok(
            "After Iran Downs Jet." in answer_text,
            f"latest answer should punctuate rendered news headline bullets, got={answer_text!r}",
        )
        assert_ok(
            "pace challenge of Easter." in answer_text,
            f"latest answer should punctuate second rendered news headline bullet, got={answer_text!r}",
        )
        assert_ok(
            "- nytimes.com." not in answer_text and "- bbc.co.uk." not in answer_text,
            f"source-domain bullets should stay unpunctuated, got={answer_text!r}",
        )

        window.close()
        window.deleteLater()
        app.processEvents()
        print("NEWS_HEADLINE_PUNCTUATION_OFFSCREEN_OK")
        return 0


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.tools_dir = self.home / ".codex-api-home" / "lucy" / "snapshots" / "lucy-v8" / "tools"
        self.state_dir = self.home / ".codex-api-home" / "lucy" / "runtime-v8" / "state"
        self.current_state_path = self.state_dir / "current_state.json"
        self.runtime_lifecycle_path = self.state_dir / "runtime_lifecycle.json"
        self.last_request_result_path = self.state_dir / "last_request_result.json"
        self.request_history_path = self.state_dir / "request_history.jsonl"
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def prepare_import_environment(self) -> None:
        os.environ["HOME"] = str(self.home)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        # Set required runtime namespace root (parent of state_dir)
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(self.state_dir.parent)
        # Set required authority contract variables
        os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(self.home / "lucy" / "snapshots" / "lucy-v8")
        os.environ["LUCY_UI_ROOT"] = str(REPO_UI_ROOT)
        os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
        sys.path.insert(0, str(REPO_UI_ROOT))

    def install_runtime_control_tool(self) -> None:
        shutil.copy2(REPO_TOOLS_ROOT / "runtime_control.py", self.tools_dir / "runtime_control.py")

    def write_current_state(self) -> None:
        write_json(
            self.current_state_path,
            {
                "schema_version": 1,
                "profile": "lucy-v8",
                "mode": "auto",
                "memory": "on",
                "evidence": "on",
                "voice": "on",
                "augmentation_policy": "direct_allowed",
                "augmented_provider": "openai",
                "model": "local-lucy",
                "updated_at": "2026-04-04T08:18:35Z",
            },
        )

    def write_runtime_lifecycle(self) -> None:
        write_json(
            self.runtime_lifecycle_path,
            {
                "schema_version": 1,
                "status": "running",
                "started_at": "2026-04-04T08:10:00Z",
                "updated_at": "2026-04-04T08:18:35Z",
                "last_error": "",
            },
        )

    def write_request_result(self) -> None:
        payload = {
            "accepted": True,
            "completed_at": "2026-04-04T08:18:35Z",
            "control_state": {
                "mode": "auto",
                "memory": "on",
                "evidence": "on",
                "voice": "on",
                "augmentation_policy": "direct_allowed",
                "augmented_provider": "openai",
                "model": "local-lucy",
                "profile": "lucy-v8",
            },
            "error": "",
            "outcome": {
                "requested_mode": "NEWS",
                "final_mode": "NEWS",
                "evidence_mode": "validated",
                "trust_class": "evidence_backed",
                "outcome_code": "answered",
                "action_hint": "",
                "answer_class": "evidence_backed_answer",
                "provider_authorization": "not_applicable",
                "operator_trust_label": "evidence-backed",
                "operator_answer_path": "Evidence-backed answer",
                "operator_note": "Latest items extracted from allowlisted sources.",
                "fallback_used": "false",
                "fallback_reason": "none",
                "augmented_provider": "none",
                "augmented_direct_request": "0",
                "evidence_created": "true",
            },
            "request_id": "req-news-punctuation",
            "request_text": "What about the latest world news?",
            "response_text": (
                "From current sources:\n"
                "Latest items extracted from allowlisted sources as of 2026-04-04T08:18:34Z.\n"
                "Key items:\n"
                "- [nytimes.com] (Sat, 04 Apr 2026 07:54:02 +0000): Iran War Live Updates: U.S. Forces Search for Missing Airman After Iran Downs Jet\n"
                "- [bbc.co.uk] (Sat, 04 Apr 2026 06:42:48 GMT): Artemis II crew now halfway to Moon as they face pace challenge of Easter\n"
                "Sources:\n"
                "- nytimes.com\n"
                "- bbc.co.uk\n"
            ),
            "route": {
                "selected_route": "NEWS",
                "mode": "NEWS",
                "intent_class": "news",
                "reason": "offscreen news punctuation test",
                "query": "What about the latest world news?",
                "utc": "2026-04-04T08:18:35Z",
            },
            "status": "completed",
        }
        self.last_request_result_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        self.request_history_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
