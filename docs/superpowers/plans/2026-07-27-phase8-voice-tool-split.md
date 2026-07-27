# Phase 8c — Split `tools/router_py/voice_tool.py`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `tools/router_py/voice_tool.py` into a focused `tools/router_py/voice/` package and migrate callers, preserving behavior.

**Architecture:** Move exception classes to `voice/exceptions.py`, data classes to `voice/models.py`, utility helpers to `voice/utils.py`, and the main `VoicePipeline` class plus `quick_voice_interaction` to `voice/pipeline.py`. Expose the public API through `voice/__init__.py`. Migrate direct callers to import from `router_py.voice`. Delete the old monolithic module after callers are migrated.

**Tech Stack:** Python 3, pytest, ruff, git

## Global Constraints

- Preserve all existing behavior; no functional changes.
- Remove `tools/router_py/voice_tool.py` only after callers are migrated.
- Run `./scripts/run-fast-tests.sh` (the fast default suite) after each task; no regressions allowed.
- Run `ruff check tools/router_py/voice/` after code changes.
- Commit after each task.
- Do not touch modules outside `voice_tool.py` and its direct callers.
- Keep the optional-import behavior: `router_py.voice` must import cleanly even when heavy voice dependencies are missing.

---

### Task 1: Add characterization tests for `voice_tool`

**Files:**
- Create: `tools/router_py/test_voice_tool_characterization.py`

**Interfaces:**
- Consumes: existing public symbols from `router_py.voice_tool` that are always available: `clean_text`, `iso_now`, exception classes, `AudioBuffer`, `VoiceResult`, `VADConfig`, `VoiceMetrics`, `TranscriptionResult`.
- Produces: passing tests that exercise the public API and must continue to pass after the split.

- [ ] **Step 1: Write the characterization test file**

Create `tools/router_py/test_voice_tool_characterization.py`:

```python
#!/usr/bin/env python3
"""Characterization tests for the voice_tool public API.

These tests exercise symbols that are always available (no heavy voice deps).
They must pass before and after the voice_tool.py split.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from router_py.voice_tool import (
    AudioBuffer,
    PlaybackError,
    RecordingError,
    SynthesisError,
    TranscriptionError,
    TranscriptionResult,
    VADConfig,
    VoiceMetrics,
    VoicePipelineError,
    VoiceResult,
    clean_text,
    iso_now,
)


def test_clean_text():
    assert clean_text("  hello  ") == "hello"
    assert clean_text(None) == ""
    assert clean_text(123) == "123"


def test_iso_now():
    ts = iso_now()
    assert "T" in ts
    assert ts.endswith("Z")


def test_audio_buffer_duration():
    # 1 second of 16-bit mono 16000 Hz silence
    data = b"\x00" * (16000 * 1 * 2)
    buf = AudioBuffer(data=data, sample_rate=16000, channels=1, sample_width=2)
    assert buf.duration_ms == 1000
    assert buf.frame_count == 16000


def test_transcription_result():
    result = TranscriptionResult(text="hello", backend="whisper")
    assert result.text == "hello"
    assert result.backend == "whisper"


def test_voice_result_defaults():
    result = VoiceResult(
        input_text="hello",
        response_text="hi there",
        output_audio=b"",
    )
    assert result.input_text == "hello"
    assert result.response_text == "hi there"
    assert result.success is True


def test_vad_config_defaults():
    cfg = VADConfig()
    assert cfg.sample_rate == 16000


def test_voice_metrics_defaults():
    metrics = VoiceMetrics()
    assert metrics.total_duration_ms == 0


def test_exception_hierarchy():
    assert issubclass(RecordingError, VoicePipelineError)
    assert issubclass(TranscriptionError, VoicePipelineError)
    assert issubclass(SynthesisError, VoicePipelineError)
    assert issubclass(PlaybackError, VoicePipelineError)
```

- [ ] **Step 2: Run the characterization tests**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_voice_tool_characterization.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/test_voice_tool_characterization.py
git commit -m "test(voice): add voice_tool characterization tests before split"
```

---

### Task 2: Create the `tools/router_py/voice/` package

**Files:**
- Create: `tools/router_py/voice/__init__.py`
- Create: `tools/router_py/voice/exceptions.py`
- Create: `tools/router_py/voice/models.py`
- Create: `tools/router_py/voice/utils.py`
- Create: `tools/router_py/voice/pipeline.py`

**Interfaces:**
- Consumes: existing code in `tools/router_py/voice_tool.py`.
- Produces: a package with the same public symbols as the old module.

- [ ] **Step 1: Create `tools/router_py/voice/__init__.py`**

```python
#!/usr/bin/env python3
"""Local Lucy voice processing package."""

# Core symbols that are always available (no heavy voice dependencies)
from router_py.voice.exceptions import (
    PlaybackError,
    RecordingError,
    SynthesisError,
    TranscriptionError,
    VoicePipelineError,
)
from router_py.voice.models import (
    AudioBuffer,
    TranscriptionResult,
    VADConfig,
    VoiceMetrics,
    VoiceResult,
)
from router_py.voice.utils import clean_text, iso_now

# Heavy voice pipeline is optional; gracefully degrade if deps are missing.
try:
    from router_py.voice.pipeline import VoicePipeline, quick_voice_interaction

    _voice_available = True
except ImportError:
    _voice_available = False

    class VoicePipeline:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("Voice pipeline dependencies are not available")

    def quick_voice_interaction(*args, **kwargs):  # type: ignore
        raise ImportError("Voice pipeline dependencies are not available")

__all__ = [
    "AudioBuffer",
    "TranscriptionResult",
    "VADConfig",
    "VoiceMetrics",
    "VoiceResult",
    "VoicePipeline",
    "quick_voice_interaction",
    "clean_text",
    "iso_now",
    "VoicePipelineError",
    "RecordingError",
    "TranscriptionError",
    "SynthesisError",
    "PlaybackError",
]
```

- [ ] **Step 2: Create `tools/router_py/voice/exceptions.py`**

Create the file with this header, then copy the exception class hierarchy verbatim from `tools/router_py/voice_tool.py` lines 99-131:

```python
#!/usr/bin/env python3
"""Voice pipeline exceptions."""


class VoicePipelineError(RuntimeError):
    """Base exception for voice pipeline errors."""

    pass


class RecordingError(VoicePipelineError):
    # ... copy verbatim


class TranscriptionError(VoicePipelineError):
    # ... copy verbatim


class SynthesisError(VoicePipelineError):
    # ... copy verbatim


class PlaybackError(VoicePipelineError):
    # ... copy verbatim
```

- [ ] **Step 3: Create `tools/router_py/voice/models.py`**

Create the file with this header, then copy the dataclasses verbatim from `tools/router_py/voice_tool.py` lines 134-299:

```python
#!/usr/bin/env python3
"""Voice pipeline data models."""

from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class TranscriptionResult:
    # ... copy verbatim lines 143-148


@dataclass
class AudioBuffer:
    # ... copy verbatim lines 151-218 (include methods)


@dataclass
class VoiceMetrics:
    # ... copy verbatim lines 219-239


@dataclass
class VoiceResult:
    # ... copy verbatim lines 241-274


@dataclass
class VADConfig:
    # ... copy verbatim lines 276-297
```

- [ ] **Step 4: Create `tools/router_py/voice/utils.py`**

Create the file with this header, then copy the utility functions and logger classes verbatim from `tools/router_py/voice_tool.py` lines 60-97 and 1828-1865:

```python
#!/usr/bin/env python3
"""Voice utility helpers."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def iso_now() -> str:
    """Return current UTC time as ISO-8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_text(value: Any) -> str:
    """Clean and normalize text input."""
    if value is None:
        return ""
    return str(value).strip()


def log_voice_pipeline_start():
    # ... copy verbatim from voice_tool.py line 1830


class VoiceUsageLogger:
    # ... copy verbatim from voice_tool.py lines 1838-1865
```

- [ ] **Step 5: Create `tools/router_py/voice/pipeline.py`**

Create the file with this header, then copy the `VoicePipeline` class and `quick_voice_interaction` function verbatim from `tools/router_py/voice_tool.py` lines 299-1827 and 1580-1620. Keep the module-level sys.path/imports for `tts_adapter`, `playback`, and `base_tool_wrapper` exactly as in the original:

```python
#!/usr/bin/env python3
"""Main voice pipeline implementation."""

from __future__ import annotations

import asyncio
import audioop
import io
import json
import logging
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# Import base wrapper
try:
    from .base_tool_wrapper import BaseToolWrapper, ToolConfig, ToolResult
except ImportError:
    from base_tool_wrapper import BaseToolWrapper, ToolConfig, ToolResult

# Import TTS adapter / playback
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_runtime_namespace_root

VOICE_DIR = Path(__file__).resolve().parents[1] / "voice"
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

_playback_with_levels_import_error = None

try:
    import tts_adapter
    from playback import play_wav_file, PlaybackError, detect_audio_player

    try:
        from playback_with_levels import play_wav_file_with_levels
    except ImportError as e:
        _playback_with_levels_import_error = str(e)
        play_wav_file_with_levels = None
except ImportError as e:
    tts_adapter = None
    play_wav_file = None
    play_wav_file_with_levels = None
    PlaybackError = RuntimeError
    detect_audio_player = lambda: ""

from router_py.voice.exceptions import (
    PlaybackError,
    RecordingError,
    SynthesisError,
    TranscriptionError,
    VoicePipelineError,
)
from router_py.voice.models import (
    AudioBuffer,
    TranscriptionResult,
    VADConfig,
    VoiceMetrics,
    VoiceResult,
)
from router_py.voice.utils import clean_text, iso_now

logger = logging.getLogger(__name__)


class VoicePipeline(BaseToolWrapper):
    # ... copy verbatim from voice_tool.py lines 299-1827


async def quick_voice_interaction(
    # ... copy signature and body verbatim from voice_tool.py lines 1580-1620
):
    # ... copy verbatim
```

- [ ] **Step 6: Verify package imports cleanly**

```bash
cd /home/mike/lucy-v11/tools
python3 -c "from router_py.voice import clean_text, iso_now; print('ok')"
python3 -c "from router_py.voice.exceptions import VoicePipelineError; print('ok')"
python3 -c "from router_py.voice.models import AudioBuffer, VoiceResult; print('ok')"
```

Expected: all three print `ok`.

- [ ] **Step 7: Commit**

```bash
git add tools/router_py/voice/
git commit -m "refactor(voice): split voice_tool.py into focused package"
```

---

### Task 3: Migrate callers

**Files:**
- Modify: `tools/router_py/__init__.py:85-99`
- Modify: `tools/router_py/streaming_voice.py:294,311,531`
- Modify: `tools/router_py/voice_runtime.py:26-27,142`
- Modify: `tools/router_py/test_voice_tool.py:22-30`
- Modify: `tools/router_py/test_voice_tool_characterization.py:12`

**Interfaces:**
- No interface change; only import paths change from `router_py.voice_tool` / `voice_tool` to `router_py.voice`.

- [ ] **Step 1: Update `tools/router_py/__init__.py`**

Replace the voice import block (lines 85-99):

```python
# Voice Pipeline (Phase 5) - optional import for graceful fallback
try:
    from .voice_tool import (
        VoicePipeline,
        AudioBuffer,
        VoiceResult,
        VoiceMetrics,
        VADConfig,
        quick_voice_interaction,
        VoicePipelineError,
        RecordingError,
        TranscriptionError,
        SynthesisError,
        PlaybackError,
    )

    _voice_available = True
except ImportError as _voice_import_err:
    _voice_available = False

    # Define placeholder classes for type hints when voice deps are missing
    class VoicePipeline:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(f"Voice pipeline not available: {_voice_import_err}")
```

with:

```python
# Voice Pipeline (Phase 5) - optional import for graceful fallback
try:
    from .voice import (
        AudioBuffer,
        PlaybackError,
        RecordingError,
        SynthesisError,
        TranscriptionError,
        VADConfig,
        VoiceMetrics,
        VoicePipeline,
        VoicePipelineError,
        VoiceResult,
        quick_voice_interaction,
    )

    _voice_available = True
except ImportError as _voice_import_err:
    _voice_available = False

    # Define placeholder classes for type hints when voice deps are missing
    class VoicePipeline:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(f"Voice pipeline not available: {_voice_import_err}")
```

- [ ] **Step 2: Update `tools/router_py/streaming_voice.py`**

Replace:
```python
from voice_tool import AudioBuffer
```
with:
```python
from router_py.voice import AudioBuffer
```

Replace:
```python
from voice_tool import VoicePipeline
```
with:
```python
from router_py.voice import VoicePipeline
```

(There are two occurrences; update both.)

- [ ] **Step 3: Update `tools/router_py/voice_runtime.py`**

Replace:
```python
from voice_tool import VoicePipeline, AudioBuffer
```
with:
```python
from router_py.voice import AudioBuffer, VoicePipeline
```

Replace the second occurrence:
```python
from voice_tool import VoicePipeline
```
with:
```python
from router_py.voice import VoicePipeline
```

- [ ] **Step 4: Update test imports**

In `tools/router_py/test_voice_tool.py`, replace:
```python
from router_py.voice_tool import clean_text, iso_now
```
with:
```python
from router_py.voice import clean_text, iso_now
```

And replace:
```python
from router_py.voice_tool import (
    VoicePipeline,
    VADConfig,
    VoiceResult,
)
```
with:
```python
from router_py.voice import (
    VoicePipeline,
    VADConfig,
    VoiceResult,
)
```

In `tools/router_py/test_voice_tool_characterization.py`, replace the `from router_py.voice_tool import (...)` block with `from router_py.voice import (...)` using the same symbols.

- [ ] **Step 5: Verify caller imports**

```bash
cd /home/mike/lucy-v11/tools
python3 -c "import router_py"
python3 -c "import router_py.test_voice_tool"
python3 -c "import router_py.test_voice_tool_characterization"
python3 -c "import streaming_voice" 2>/dev/null || true
python3 -c "import voice_runtime" 2>/dev/null || true
```

Expected: imports succeed where dependencies are available; optional modules may fail only due to missing voice backends, not import-path errors.

- [ ] **Step 6: Commit**

```bash
git add tools/router_py/__init__.py \
        tools/router_py/streaming_voice.py \
        tools/router_py/voice_runtime.py \
        tools/router_py/test_voice_tool.py \
        tools/router_py/test_voice_tool_characterization.py
git commit -m "refactor(voice): migrate callers from voice_tool to voice package"
```

---

### Task 4: Delete the old `voice_tool.py`

**Files:**
- Delete: `tools/router_py/voice_tool.py`

**Interfaces:**
- Removes the old monolithic module; all callers now use `router_py.voice`.

- [ ] **Step 1: Delete the file**

```bash
cd /home/mike/lucy-v11
rm tools/router_py/voice_tool.py
```

- [ ] **Step 2: Confirm no remaining references in source**

```bash
cd /home/mike/lucy-v11
grep -R "from router_py\.voice_tool\|import router_py\.voice_tool\|from voice_tool import\|import voice_tool" --include="*.py" tools/ ui-v10/ || true
```

Expected: no matches (except possibly comments/docstrings that do not import the module).

- [ ] **Step 3: Commit**

```bash
git rm tools/router_py/voice_tool.py
git commit -m "refactor(voice): remove monolithic voice_tool.py"
```

---

### Task 5: Run tests and lint

**Files:**
- None (verification only).

**Interfaces:**
- Confirm no regressions.

- [ ] **Step 1: Run ruff**

```bash
cd /home/mike/lucy-v11
python3 -m ruff check tools/router_py/voice/
```

Expected: `All checks passed!`

- [ ] **Step 2: Run characterization tests**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_voice_tool_characterization.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Run the fast router suite**

```bash
cd /home/mike/lucy-v11
./scripts/run-fast-tests.sh
```

Expected: the suite passes with the same baseline counts as before (693 passed, 7 skipped, 261 deselected, 169 subtests).

- [ ] **Step 4: Commit verification results (optional)**

No code changes; record the final counts in the report.

---

### Task 6: Write the voice-tool split report

**Files:**
- Create: `lucy-v11-prep/reports/phase8_voice_tool_split_2026-07-27.md`

**Interfaces:**
- No code interface; report documents the change.

- [ ] **Step 1: Write the report**

The report should include:

- Date, branch, V10 preservation statement.
- Objective: split `voice_tool.py`.
- New files: `tools/router_py/voice/__init__.py`, `exceptions.py`, `models.py`, `utils.py`, `pipeline.py`.
- Deleted file: `tools/router_py/voice_tool.py`.
- Callers migrated: `router_py/__init__.py`, `streaming_voice.py`, `voice_runtime.py`, `test_voice_tool.py`, plus the characterization tests.
- Verification: grep results, ruff result, pytest summary.
- Gate assessment table.
- Next steps: continue with `policy.py` or `policy_router.py`.

- [ ] **Step 2: Commit the report**

```bash
git add lucy-v11-prep/reports/phase8_voice_tool_split_2026-07-27.md
git commit -m "docs: Phase 8c report for voice_tool.py split"
```

---

## Self-review checklist

- [ ] Spec coverage: package creation, caller migration, deletion, characterization tests, fast suite, lint, report.
- [ ] Placeholder scan: no TBD/TODO/"fill in details".
- [ ] Type consistency: public symbols unchanged; optional import behavior preserved.
- [ ] Scope: only `voice_tool.py` and callers touched.
