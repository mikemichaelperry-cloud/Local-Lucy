"""AioHTTP web adapter for Local Lucy v10.

This is a thin input/output surface over ``tools/router_py.main.execute_plan_python``.
It does not implement routing, search, memory, model execution, or response
formatting. Those all remain in the existing Local Lucy pipeline.

Run as a module from the repository root::

    source ui-v10/.venv/bin/activate
    LUCY_WEB_ENABLED=1 python -m web_adapter

Environment variables::

    LUCY_WEB_ENABLED      set to "1"/"true"/"yes" to start the server
    LUCY_WEB_HOST         bind address (default: 127.0.0.1)
    LUCY_WEB_PORT         bind port (default: 8765)
    LUCY_WEB_AUTH_TOKEN   secret token/password (required for non-localhost binds)
    LUCY_WEB_MAX_QUESTION max question length (default: 4000)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

# Ensure ``tools`` is on sys.path. The existing router code imports itself as
# the top-level ``router_py`` package (``tools/router_py``), so we must
# preserve that layout when importing the pipeline.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "tools"))

from router_py.main import execute_plan_python  # noqa: E402

from web_adapter.static import INDEX_HTML  # noqa: E402

logger = logging.getLogger("local_lucy.web_adapter")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_MAX_QUESTION = 4000
SUPPORTED_MODELS = frozenset(
    {
        "local-lucy-llama31",
        "gemma4:12b-it-qat",
    }
)


class WebConfig:
    """Runtime configuration for the web adapter."""

    def __init__(self) -> None:
        self.host = os.environ.get("LUCY_WEB_HOST", DEFAULT_HOST).strip()
        self.port = int(os.environ.get("LUCY_WEB_PORT", str(DEFAULT_PORT)))
        self.auth_token = os.environ.get("LUCY_WEB_AUTH_TOKEN", "").strip()
        self.max_question = int(os.environ.get("LUCY_WEB_MAX_QUESTION", str(DEFAULT_MAX_QUESTION)))

    def is_local_bind(self) -> bool:
        """Return True when the configured bind address is loopback-only."""
        return self.host in ("127.0.0.1", "localhost", "::1")


# Typed application config key (avoids aiohttp AppKey warnings).
CONFIG_KEY = web.AppKey("config", WebConfig)


# ---------------------------------------------------------------------------
# Model / runtime state helpers
# ---------------------------------------------------------------------------


def _active_model_from_state() -> str | None:
    """Read the active model from the runtime state file, if available."""
    try:
        import runtime_control  # noqa: E402

        state_file = Path(
            os.environ.get("LUCY_RUNTIME_STATE_FILE", runtime_control.DEFAULT_STATE_FILE)
        )
        state = runtime_control.load_or_create_state(state_file, refresh_timestamp=False)
        return state.get("model") or state.get("active_model")
    except Exception as exc:
        logger.debug(f"Could not read active model from state: {exc}")
        return os.environ.get("LUCY_LOCAL_MODEL")


def _default_model() -> str:
    """Return a sensible default model name for display and validation."""
    return _active_model_from_state() or "local-lucy-llama31"


def _validate_model(model: str | None) -> str | None:
    """Return a normalized model name if it is a supported configured model."""
    if not model:
        return None
    normalized = model.strip()
    if normalized in SUPPORTED_MODELS:
        return normalized
    return None


def _lucy_available() -> bool:
    """Best-effort check that the Ollama backend is reachable."""
    url = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434/api/tags")
    try:
        import urllib.request

        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception as exc:
        logger.debug(f"Ollama availability check failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def _check_auth_token(request: web.Request, token: str) -> bool:
    """Validate the Authorization header against the configured token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        return False

    # Bearer token
    if auth_header.lower().startswith("bearer "):
        return secrets.compare_digest(auth_header[7:].strip(), token)

    # Basic auth (username ignored, password must match token)
    if auth_header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            _, _, password = decoded.partition(":")
            return secrets.compare_digest(password, token)
        except Exception:
            return False

    return False


@web.middleware
async def auth_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Require authentication when a token is configured."""
    config: WebConfig = request.app[CONFIG_KEY]
    if config.auth_token and not _check_auth_token(request, config.auth_token):
        return web.Response(
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="Local Lucy"'},
            text="Authentication required",
        )
    return await handler(request)


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------


async def _run_lucy_query(
    question: str,
    model: str | None,
) -> dict[str, Any]:
    """Call the Local Lucy pipeline off the event loop thread."""
    start = time.monotonic()
    loop = asyncio.get_running_loop()

    def _sync_execute() -> Any:
        kwargs: dict[str, Any] = {
            "question": question,
            "policy": "fallback_only",
            "timeout": 130,
            "surface": "api",
        }
        if model:
            kwargs["model"] = model
        # Stateless by default: do not carry a session_id so web requests do not
        # share or recall conversation context through the session-memory system.
        kwargs["context"] = {}
        return execute_plan_python(**kwargs)

    outcome = await loop.run_in_executor(None, _sync_execute)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    return {
        "ok": outcome.outcome_code == "answered",
        "answer": outcome.response_text or "",
        "route": outcome.route,
        "provider": outcome.provider,
        "model": model or _default_model(),
        "elapsed_ms": elapsed_ms,
    }


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------


async def index_handler(request: web.Request) -> web.Response:
    """Serve the single-page web interface."""
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def status_handler(request: web.Request) -> web.Response:
    """Return Lucy availability and the active default model."""
    active_model = _default_model()
    return web.json_response(
        {
            "ok": True,
            "available": _lucy_available(),
            "active_model": active_model,
            "default_model": active_model,
            "memory_enabled": os.environ.get("LUCY_SESSION_MEMORY", "0").lower()
            in ("1", "true", "yes", "on"),
        }
    )


async def models_handler(request: web.Request) -> web.Response:
    """Return supported configured models and the active default."""
    return web.json_response(
        {
            "ok": True,
            "models": sorted(SUPPORTED_MODELS),
            "active_model": _default_model(),
        }
    )


async def ask_handler(request: web.Request) -> web.Response:
    """Submit a question to Local Lucy and return the final answer."""
    config: WebConfig = request.app[CONFIG_KEY]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

    question = str(body.get("question", "")).strip()
    if not question:
        return web.json_response({"ok": False, "error": "Question is required"}, status=400)
    if len(question) > config.max_question:
        return web.json_response(
            {"ok": False, "error": f"Question exceeds {config.max_question} characters"},
            status=400,
        )

    requested_model = _validate_model(body.get("model"))
    if body.get("model") and requested_model is None:
        return web.json_response(
            {"ok": False, "error": "Unsupported model requested"},
            status=400,
        )

    try:
        result = await _run_lucy_query(question, requested_model)
        if not result["ok"]:
            return web.json_response(
                {"ok": False, "error": "Lucy could not answer"},
                status=502,
            )
        return web.json_response(result)
    except Exception:
        logger.exception("Unhandled error during /api/ask")
        return web.json_response(
            {"ok": False, "error": "Internal error while processing the request"},
            status=500,
        )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(overrides: dict[str, Any] | None = None) -> web.Application:
    """Create and configure the aiohttp application."""
    config = WebConfig()
    if overrides:
        for key, value in overrides.items():
            setattr(config, key, value)

    app = web.Application(middlewares=[auth_middleware])
    app[CONFIG_KEY] = config
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/status", status_handler)
    app.router.add_get("/api/models", models_handler)
    app.router.add_post("/api/ask", ask_handler)
    return app


def main() -> int:
    """Entry point for ``python -m web_adapter``."""
    enabled = os.environ.get("LUCY_WEB_ENABLED", "").lower() in ("1", "true", "yes", "on")
    if not enabled:
        print(
            "Local Lucy web adapter is disabled. Set LUCY_WEB_ENABLED=1 to start it.",
            file=sys.stderr,
        )
        return 1

    config = WebConfig()
    if not config.is_local_bind() and not config.auth_token:
        print(
            "LUCY_WEB_AUTH_TOKEN is required when binding to a non-loopback address.",
            file=sys.stderr,
        )
        return 1

    # Web requests are stateless by default: do not read or write conversation
    # memory through the shared session-memory system. This avoids conflating
    # web turns with HMI memory without redesigning the memory subsystem.
    os.environ["LUCY_SESSION_MEMORY"] = "0"

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    app = create_app()
    print(f"Local Lucy web adapter starting on http://{config.host}:{config.port}")
    if config.is_local_bind():
        print(
            "Listening on loopback only. Set LUCY_WEB_HOST to a LAN/Tailscale IP for remote access."
        )
    else:
        print(f"Listening on {config.host}. Authentication is required.")

    web.run_app(app, host=config.host, port=config.port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
