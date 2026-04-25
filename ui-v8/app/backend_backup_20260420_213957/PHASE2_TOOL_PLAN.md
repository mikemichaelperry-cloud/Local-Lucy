# Phase 2 Tool Wrapper Migration Plan

**Date:** 2026-04-12  
**Status:** 📋 Planning Phase  
**Target Location:** `/home/mike/lucy-v8/snapshots/opt-experimental-v8-dev/tools/router_py/tools/`  

---

## Executive Summary

This plan defines the migration of core tool wrappers from shell scripts to Python implementations. The new Python tools will provide:
- **Better error handling** with structured exceptions
- **Type safety** through dataclasses and type hints
- **Testability** with clear interfaces and mockable components
- **Async/await support** for concurrent operations
- **Consistent retry logic** across all external calls

---

## Current State Analysis

### Existing Tool Architecture

| Component | Current Implementation | Purpose |
|-----------|------------------------|---------|
| `runtime_request.py` | Python ✅ | Main request endpoint (already migrated) |
| `runtime_voice.py` | Python ✅ | Voice PTT runtime (already migrated) |
| `local_answer.sh` | Shell | Local LLM (Ollama) wrapper |
| `local_runtime.sh` | Shell | Ollama API health checks |
| `fetch_evidence.sh` | Shell | Evidence fetch orchestrator |
| `tool_router.sh` | Shell | Internet tool dispatcher |
| `build_news_digest.sh` | Shell | RSS/news digest builder |
| `lucy_voice_ptt.sh` | Shell | Voice PTT wrapper |
| `search_web.py` | Python ✅ | Web search via SearXNG |
| `fetch_url.py` | Python ✅ | URL fetching with trust validation |

### Shell Tool Patterns Found

#### 1. Request Tool Pattern (local_answer.sh)
```bash
# External commands called:
- curl (Ollama API: POST /api/generate)
- python3 (JSON parsing)

# Environment variables:
LUCY_LOCAL_MODEL        # Model name (default: local-lucy)
LUCY_OLLAMA_API_URL     # API endpoint (default: http://127.0.0.1:11434/api/generate)
LUCY_LOCAL_TEMPERATURE  # Temperature (default: 0)
LUCY_LOCAL_TOP_P        # Top-p (default: 1)
LUCY_LOCAL_SEED         # Seed (default: 7)

# Input/Output:
Input: Query string via argv[1]
Output: Response text to stdout
Errors: Return code + stderr

# Error handling:
- Backend unavailable detection (connection refused, 127.0.0.1:11434)
- Timeout handling (120s max)
- Retry logic: None currently
```

#### 2. Voice Tool Pattern (lucy_voice_ptt.sh)
```bash
# External commands called:
- arecord/pw-record (audio capture)
- whisper/vosk (STT)
- tts_adapter.py (TTS)
- kokoro_session_worker.py (Kokoro TTS)
- play/mpv/paplay (audio playback)

# Environment variables:
LUCY_VOICE_MAX_SECONDS              # Recording limit (default: 8)
LUCY_VOICE_STT_ENGINE               # STT engine (auto/whisper/vosk)
LUCY_VOICE_TTS_ENGINE               # TTS engine (auto/kokoro/piper)
LUCY_VOICE_TTS_VOICE                # Voice ID (default: en_US)
LUCY_VOICE_ONESHOT                  # One-shot mode (0/1)
LUCY_VOICE_PTT_MODE                 # Mode (hold/toggle)

# Input/Output:
Input: Voice audio via stdin/keypress
Output: Audio playback, transcript to stdout
Errors: Exit codes (PTT_START_* / PTT_STOP_*)

# Error handling:
- Missing backend detection
- Recording timeout
- STT failure fallback
```

#### 3. News Tool Pattern (build_news_digest.sh)
```bash
# External commands called:
- awk (text processing)
- grep/sed/tr (text manipulation)
- date (timestamp generation)

# Environment variables:
None - pure data transformation

# Input/Output:
Input: Evidence pack file path
Output: Digest file with structured news data

# Error handling:
- Missing input file check
- AWK parsing errors (silent skip)
```

---

## Proposed Python Architecture

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Architecture** | Class-based with dataclasses | Consistent with router_py pattern |
| **Async/Await** | Yes, for I/O operations | Allows concurrent API calls, timeouts |
| **HTTP Client** | `aiohttp` with timeouts | Async-friendly, better than urllib |
| **Retry Logic** | `tenacity` library | Industry standard, configurable |
| **Error Handling** | Custom exception hierarchy | Structured error propagation |
| **Configuration** | Pydantic Settings | Type-safe env var handling |

### Base Tool Wrapper Class

```python
# router_py/tools/base_tool.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

T = TypeVar('T')

class ToolError(Exception):
    """Base exception for tool errors."""
    def __init__(self, message: str, code: str = "unknown", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

class ToolTimeoutError(ToolError):
    """Tool operation timed out."""
    pass

class ToolBackendError(ToolError):
    """Backend service unavailable."""
    pass

@dataclass(frozen=True)
class ToolResult:
    """Standardized tool execution result."""
    success: bool
    data: Any
    error_code: str = ""
    error_message: str = ""
    execution_time_ms: int = 0
    metadata: dict = field(default_factory=dict)

class BaseToolWrapper(ABC, Generic[T]):
    """Abstract base for all tool wrappers."""
    
    def __init__(self, config: T, logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._setup_retry_policy()
    
    def _setup_retry_policy(self):
        """Configure retry policy - can be overridden."""
        self._retry_decorator = retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=self._should_retry,
            before_sleep=self._on_retry,
        )
    
    @abstractmethod
    def _should_retry(self, exception: Exception) -> bool:
        """Determine if exception should trigger retry."""
        pass
    
    def _on_retry(self, retry_state):
        """Log retry attempts."""
        self.logger.warning(
            f"Retry {retry_state.attempt_number}/3 after error: {retry_state.outcome.exception()}"
        )
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool operation."""
        pass
```

---

## Tool Migration Specifications

### 1. Request Tool (request_tool.py)

**Purpose:** Handle API requests to local LLM (Ollama) with retry and error handling.

**Consolidation:** Absorbs functionality from:
- `local_answer.sh` (Ollama API calls)
- `local_runtime.sh` (health checks)

```python
# router_py/tools/request_tool.py
from dataclasses import dataclass
from typing import AsyncIterator
import aiohttp
from tenacity import retry_if_exception_type

@dataclass(frozen=True)
class RequestToolConfig:
    ollama_url: str = "http://127.0.0.1:11434/api/generate"
    model: str = "local-lucy"
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int = 7
    timeout_seconds: float = 120.0
    max_retries: int = 3
    retry_backoff_base: float = 1.0

@dataclass(frozen=True)
class LLMResponse:
    text: str
    tokens_generated: int
    total_duration_ms: int
    load_duration_ms: int

class RequestTool(BaseToolWrapper[RequestToolConfig]):
    """
    Async-capable LLM request tool with retry logic.
    
    Features:
    - Streaming response support
    - Connection pooling via aiohttp
    - Automatic retry on transient errors
    - Backend health checking
    """
    
    async def execute(self, prompt: str, stream: bool = False) -> ToolResult:
        """Execute LLM request with retries."""
        pass
    
    async def health_check(self) -> bool:
        """Check if Ollama backend is available."""
        pass
    
    async def stream_response(self, prompt: str) -> AsyncIterator[str]:
        """Stream response chunks for real-time display."""
        pass
    
    def _should_retry(self, exception: Exception) -> bool:
        """Retry on connection errors, timeouts, 5xx responses."""
        if isinstance(exception, (aiohttp.ClientConnectionError, asyncio.TimeoutError)):
            return True
        if isinstance(exception, aiohttp.ClientResponseError) and exception.status >= 500:
            return True
        return False
```

**External Commands Replaced:**
| Shell Command | Python Equivalent |
|---------------|-------------------|
| `curl -fsS --max-time 120` | `aiohttp.ClientSession.post()` with timeout |
| `python3 -c "json..."` | `json.loads()` native |

**Environment Variables Used:**
```python
LUCY_LOCAL_MODEL          # -> config.model
LUCY_OLLAMA_API_URL       # -> config.ollama_url
LUCY_LOCAL_TEMPERATURE    # -> config.temperature
LUCY_LOCAL_TOP_P          # -> config.top_p
LUCY_LOCAL_SEED           # -> config.seed
```

**Error Handling:**
- `ToolTimeoutError`: Request exceeded timeout
- `ToolBackendError`: Ollama not running (connection refused)
- `ToolError`: Invalid response, model not found

**Estimated Effort:** 2-3 days
- Core implementation: 1 day
- Retry logic & error handling: 0.5 day
- Streaming support: 0.5 day
- Tests: 1 day

---

### 2. Voice Tool (voice_tool.py)

**Purpose:** Unified voice processing (record, transcribe, synthesize) with async pipeline.

**Replaces:** `lucy_voice_ptt.sh` voice processing logic

```python
# router_py/tools/voice_tool.py
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
import asyncio

class VoiceEngine(Enum):
    WHISPER = auto()
    VOSK = auto()

class TTSEngine(Enum):
    KOKORO = auto()
    PIPER = auto()
    NONE = auto()

@dataclass(frozen=True)
class VoiceToolConfig:
    # Recording
    max_recording_seconds: int = 8
    recorder: str = "auto"  # auto/arecord/pw-record
    
    # STT
    stt_engine: VoiceEngine | str = "auto"
    whisper_bin: Path | None = None
    vosk_bin: Path | None = None
    
    # TTS
    tts_engine: TTSEngine | str = "auto"
    tts_voice: str = "en_US"
    tts_max_chars: int = 1000
    kokoro_socket: Path = Path("/tmp/kokoro.sock")
    
    # Audio
    audio_player: str = "auto"  # auto/play/mpv/paplay

@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    engine: VoiceEngine
    confidence: float  # if available
    audio_duration_ms: int

@dataclass(frozen=True)
class SynthesisResult:
    audio_path: Path
    engine: TTSEngine
    duration_ms: int
    sample_rate: int

class VoiceTool(BaseToolWrapper[VoiceToolConfig]):
    """
    Async voice processing pipeline.
    
    Pipeline stages (can run concurrently where safe):
    1. Record audio -> WAV file
    2. Transcribe -> text
    3. (Optional) Synthesize response -> WAV file
    4. Play audio
    """
    
    async def record(self, max_seconds: int | None = None) -> Path:
        """Record audio to temporary WAV file."""
        pass
    
    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        """Transcribe audio to text."""
        pass
    
    async def synthesize(self, text: str) -> SynthesisResult:
        """Synthesize text to speech."""
        pass
    
    async def play(self, audio_path: Path) -> None:
        """Play audio file."""
        pass
    
    async def execute_pipeline(
        self, 
        record_first: bool = True,
        on_transcript: Callable[[str], Awaitable[str]] | None = None,
    ) -> ToolResult:
        """
        Execute full voice pipeline.
        
        If on_transcript is provided, synthesizes and plays the response.
        """
        pass
    
    def _should_retry(self, exception: Exception) -> bool:
        """Retry on recorder/transcriber transient failures."""
        pass
```

**External Commands Replaced:**
| Shell Command | Python Equivalent |
|---------------|-------------------|
| `arecord/pw-record` | `asyncio.create_subprocess_exec()` |
| `whisper/vosk` | subprocess with async streaming |
| `tts_adapter.py` | Direct Python import/call |
| `play/mpv/paplay` | `asyncio.create_subprocess_exec()` |

**Environment Variables Used:**
```python
LUCY_VOICE_MAX_SECONDS           # -> config.max_recording_seconds
LUCY_VOICE_STT_ENGINE            # -> config.stt_engine
LUCY_VOICE_TTS_ENGINE            # -> config.tts_engine
LUCY_VOICE_TTS_VOICE             # -> config.tts_voice
LUCY_VOICE_TTS_MAX_CHARS         # -> config.tts_max_chars
LUCY_VOICE_WHISPER_BIN           # -> config.whisper_bin
LUCY_VOICE_VOSK_BIN              # -> config.vosk_bin
```

**Error Handling:**
- `VoiceRecordingError`: Recorder not available, permission denied
- `VoiceTranscriptionError`: STT failed, no speech detected
- `VoiceSynthesisError`: TTS engine unavailable
- `VoicePlaybackError`: Audio player not found

**Async Benefits:**
- Concurrent: Record next utterance while playing previous response
- Non-blocking: UI can show "listening..." indicators
- Timeout handling: Recording timeouts without blocking

**Estimated Effort:** 4-5 days
- Core pipeline: 2 days
- Engine detection (whisper/vosk/kokoro/piper): 1 day
- Streaming audio I/O: 1 day
- Tests: 1-2 days

---

### 3. News Tool (news_tool.py)

**Purpose:** RSS/news aggregation with async fetching and caching.

**Consolidation:** Merges into `request_tool.py` as it's primarily URL fetching + parsing.

```python
# router_py/tools/news_tool.py (or part of request_tool.py)
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator
import feedparser  # or custom RSS parser

@dataclass(frozen=True)
class NewsArticle:
    title: str
    source_domain: str
    published_at: datetime | None
    summary: str
    url: str
    trust_tier: int  # 1=high, 2=medium, 3=low

@dataclass(frozen=True)
class NewsDigest:
    articles: list[NewsArticle]
    digest_built_at: datetime
    sources: set[str]
    
    def to_markdown(self) -> str:
        """Format as markdown for LLM consumption."""
        pass

class NewsTool(BaseToolWrapper):
    """
    News aggregation tool with parallel fetching.
    
    Consolidated into request_tool.py - uses same HTTP client.
    Features:
    - Parallel RSS feed fetching
    - Content deduplication
    - Trust tier filtering
    - LRU caching
    """
    
    async def fetch_feed(self, feed_url: str) -> list[NewsArticle]:
        """Fetch and parse single RSS feed."""
        pass
    
    async def build_digest(
        self, 
        domains: list[str],
        max_articles_per_source: int = 6,
        max_total_articles: int = 20,
    ) -> NewsDigest:
        """Build digest from multiple sources in parallel."""
        pass
    
    def _should_retry(self, exception: Exception) -> bool:
        """Retry on network errors."""
        pass
```

**External Commands Replaced:**
| Shell Command | Python Equivalent |
|---------------|-------------------|
| `curl` (RSS fetching) | `aiohttp` via request_tool |
| `awk` (text extraction) | Python string parsing |
| `date` | `datetime.datetime.now()` |

**Consolidation Benefits:**
- Shared HTTP connection pool with request_tool
- Same retry logic, timeout handling
- Unified caching layer
- Simpler configuration

**Estimated Effort:** 2 days (as part of request_tool)
- RSS parsing: 0.5 day
- Parallel fetching: 0.5 day
- Digest formatting: 0.5 day
- Tests: 0.5 day

---

## Migration Priority Order

| Priority | Tool | Effort | Risk | Reasoning |
|----------|------|--------|------|-----------|
| 1 | **request_tool.py** | Medium | Low | Core infrastructure, clear API contract |
| 2 | **news_tool.py** | Low | Low | Builds on request_tool, simple parsing |
| 3 | **voice_tool.py** | High | Medium | Complex async I/O, multiple backends |

---

## Common Patterns & Shared Components

### 1. HTTP Client Pool

```python
# router_py/tools/http_client.py
import aiohttp
from contextlib import asynccontextmanager

class HTTPClientPool:
    """Shared async HTTP client with connection pooling."""
    
    _session: aiohttp.ClientSession | None = None
    
    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=10, limit_per_host=5),
                timeout=aiohttp.ClientTimeout(total=120),
            )
        return cls._session
    
    @classmethod
    async def close(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()
```

### 2. Retry Policy Configuration

```python
# router_py/tools/retry_config.py
from tenacity import RetryConfig

DEFAULT_RETRY_CONFIG = RetryConfig(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((
        aiohttp.ClientConnectionError,
        asyncio.TimeoutError,
    )),
    reraise=True,
)

STRICT_RETRY_CONFIG = RetryConfig(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    # More aggressive for critical paths
)
```

### 3. Backend Health Monitoring

```python
# router_py/tools/health_monitor.py
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class BackendHealth:
    name: str
    available: bool
    last_checked: datetime
    latency_ms: int
    error_count: int

class HealthMonitor:
    """Track backend health to fail fast on repeated failures."""
    
    def __init__(self, failure_threshold: int = 3, recovery_timeout_seconds: int = 60):
        self._states: dict[str, BackendHealth] = {}
        self._failure_threshold = failure_threshold
        self._recovery_timeout = timedelta(seconds=recovery_timeout_seconds)
    
    def record_check(self, name: str, available: bool, latency_ms: int = 0):
        """Record a health check result."""
        pass
    
    def is_healthy(self, name: str) -> bool:
        """Check if backend should be considered available."""
        pass
```

---

## Testing Strategy

### Unit Tests

```python
# router_py/tools/test_request_tool.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_request_tool_success():
    config = RequestToolConfig(ollama_url="http://test")
    tool = RequestTool(config)
    
    with patch('aiohttp.ClientSession.post') as mock_post:
        mock_post.return_value.__aenter__.return_value.json = AsyncMock(
            return_value={"response": "Hello"}
        )
        result = await tool.execute("Hi")
    
    assert result.success
    assert result.data.text == "Hello"

@pytest.mark.asyncio
async def test_request_tool_retry_on_connection_error():
    """Verify retry on transient connection errors."""
    pass

@pytest.mark.asyncio
async def test_request_tool_backend_unavailable():
    """Verify proper error when Ollama not running."""
    pass
```

### Integration Tests

```python
# router_py/tools/test_voice_integration.py
@pytest.mark.slow
@pytest.mark.asyncio
async def test_voice_pipeline_end_to_end():
    """Full pipeline: record -> transcribe -> synthesize -> play."""
    pass
```

---

## Rollout Plan

### Phase 2A: Request Tool (Week 1)

```bash
# Development
tools/router_py/tools/request_tool.py         # Core implementation
tools/router_py/tools/test_request_tool.py    # Unit tests
tools/router_py/tools/http_client.py          # Shared HTTP pool

# Validation
pytest tools/router_py/tools/test_request_tool.py -v

# Shadow Mode (optional)
LUCY_REQUEST_TOOL_PY=1 ./lucy_chat.sh "test"  # Use Python version
LUCY_REQUEST_TOOL_PY=0 ./lucy_chat.sh "test"  # Use shell version (default)
```

### Phase 2B: News Tool (Week 1-2)

```bash
# Development (consolidated into request_tool)
tools/router_py/tools/request_tool.py         # Add RSS methods

# Validation
pytest tools/router_py/tools/test_news.py -v
```

### Phase 2C: Voice Tool (Week 2-3)

```bash
# Development
tools/router_py/tools/voice_tool.py           # Core implementation
tools/router_py/tools/test_voice_tool.py      # Unit tests

# Validation
pytest tools/router_py/tools/test_voice_tool.py -v
./tools/router_py/tools/voice_tool_cli.py --test-record --test-transcribe
```

### Phase 2D: Full Integration (Week 3-4)

```bash
# Update existing tools to use new wrappers
runtime_request.py    # Use request_tool for Ollama calls
runtime_voice.py      # Use voice_tool for voice operations

# Regression testing
bash tools/tests/run_router_regression_gate_fast.sh
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Async/await complexity | Medium | Medium | Extensive testing, fallback to sync |
| HTTP client stability | Low | High | Use well-tested aiohttp, connection pooling |
| Voice backend compatibility | Medium | Medium | Keep shell fallback, feature flags |
| Performance regression | Low | Medium | Benchmarks, keep connection pool warm |

---

## Success Criteria

1. **Functional Parity**: All existing shell tool functionality works in Python
2. **Error Handling**: Better error messages and structured exceptions
3. **Performance**: No regression in latency (target: <10% increase)
4. **Reliability**: Fewer failures due to better retry logic
5. **Test Coverage**: >80% unit test coverage for new tools

---

## Appendix: File Structure

```
tools/router_py/
├── tools/                          # NEW: Tool wrappers
│   ├── __init__.py
│   ├── base_tool.py               # BaseToolWrapper abstract class
│   ├── http_client.py             # Shared aiohttp client pool
│   ├── retry_config.py            # Retry policy configurations
│   ├── health_monitor.py          # Backend health tracking
│   ├── request_tool.py            # LLM API requests + news
│   ├── voice_tool.py              # Voice pipeline
│   ├── test_request_tool.py       # Unit tests
│   ├── test_voice_tool.py         # Unit tests
│   └── test_integration.py        # Integration tests
├── main.py                         # Existing router orchestrator
├── execution_engine.py             # Existing execution engine
├── classify.py                     # Existing classifier
├── policy.py                       # Existing policy
└── MIGRATION_STATUS.md             # This doc
```

---

**Next Steps:**
1. ✅ Create this plan document
2. 🔄 Implement `base_tool.py` with retry logic
3. 🔄 Implement `request_tool.py` with tests
4. ⏳ Consolidate `news_tool.py` into `request_tool.py`
5. ⏳ Implement `voice_tool.py` with tests
6. ⏳ Integration and regression testing
