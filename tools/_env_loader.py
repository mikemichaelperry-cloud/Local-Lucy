"""Small helper to load the project .env file for standalone tools."""

from __future__ import annotations

import os
from pathlib import Path


def load_project_dotenv() -> None:
    """Load lucy-v10/.env into environment variables if python-dotenv is available.

    Existing environment variables are never overwritten, so values set by
    START_LUCY.sh or a user's shell take precedence over the file.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - graceful degradation
        return

    for root in (
        os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT"),
        os.environ.get("LUCY_ROOT"),
        str(Path(__file__).resolve().parent.parent),
    ):
        if not root:
            continue
        env_path = Path(root).expanduser().resolve() / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
            break
