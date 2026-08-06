import os
import urllib.request

import pytest

OLLAMA_URL = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate")


@pytest.fixture(autouse=True)
def _disable_persistent_model_warmup_for_fast_tests(request):
    """Set LUCY_LOCAL_KEEP_ALIVE=0 for fast tests so they do not keep models warm.

    Slow/live tests that exercise warmup/heartbeat behavior are left untouched.
    """
    markers = {m.name for m in request.node.iter_markers()}
    if markers & {"slow", "live"}:
        yield
        return

    old_keep_alive = os.environ.get("LUCY_LOCAL_KEEP_ALIVE")
    os.environ["LUCY_LOCAL_KEEP_ALIVE"] = "0"
    try:
        yield
    finally:
        if old_keep_alive is None:
            os.environ.pop("LUCY_LOCAL_KEEP_ALIVE", None)
        else:
            os.environ["LUCY_LOCAL_KEEP_ALIVE"] = old_keep_alive


def _ollama_is_reachable() -> bool:
    """Return True if the Ollama daemon is listening at the configured URL.

    Uses the lightweight /api/tags endpoint so we do not force a model load
    during the reachability probe.
    """
    try:
        tags_url = OLLAMA_URL.rsplit("/", 1)[0] + "/tags"
        req = urllib.request.Request(tags_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def ollama_available() -> bool:
    """Shared helper; tests can skip if Ollama is not reachable."""
    return _ollama_is_reachable()


@pytest.fixture(scope="session", autouse=False)
def skip_without_ollama() -> None:
    """Skip the requesting test if Ollama is not reachable."""
    if not _ollama_is_reachable():
        pytest.skip(f"Ollama not reachable at {OLLAMA_URL}")
