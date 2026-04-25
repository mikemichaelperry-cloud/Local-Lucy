#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path


BRIDGE_PATH = Path("/home/mike/lucy/ui-v7/app/services/runtime_bridge.py")


def install_qt_stubs() -> None:
    qtcore = types.ModuleType("PySide6.QtCore")

    class QObject:
        pass

    class QRunnable:
        pass

    def Signal(*_args, **_kwargs):
        return object()

    def Slot(*_args, **_kwargs):
        def decorator(func):
            return func

        return decorator

    qtcore.QObject = QObject
    qtcore.QRunnable = QRunnable
    qtcore.Signal = Signal
    qtcore.Slot = Slot

    pyside6 = types.ModuleType("PySide6")
    pyside6.QtCore = qtcore
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore


def load_bridge_module():
    spec = importlib.util.spec_from_file_location("runtime_bridge_test_module", BRIDGE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {BRIDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# stub\n", encoding="utf-8")


def main() -> int:
    if not BRIDGE_PATH.exists():
        raise SystemExit(f"missing bridge file: {BRIDGE_PATH}")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "snapshot"
        touch(root / "tools" / "runtime_control.py")
        touch(root / "tools" / "runtime_profile.py")
        touch(root / "tools" / "runtime_lifecycle.py")
        touch(root / "tools" / "runtime_request.py")

        install_qt_stubs()
        os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(root)
        module = load_bridge_module()
        bridge = module.RuntimeBridge()

        assert bridge.snapshot_root == root.resolve()
        assert bridge.control_tool_path == root / "tools" / "runtime_control.py"
        assert bridge.profile_tool_path == root / "tools" / "runtime_profile.py"
        assert bridge.lifecycle_tool_path == root / "tools" / "runtime_lifecycle.py"
        assert bridge.request_tool_path == root / "tools" / "runtime_request.py"
        assert bridge.voice_tool_path == root / "tools" / "runtime_voice.py"
        assert bridge.request_capability.available is True
        assert bridge.voice_capability.available is False

    print("PASS: test_runtime_bridge_authority_root_override")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
