"""Local model caller."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _render_chat_fast_from_raw(raw_text: str) -> str:
    """Render chat-fast formatted response from raw model output."""
    # Strip validated markers
    text = raw_text.replace("BEGIN_VALIDATED", "").replace("END_VALIDATED", "").strip()
    return text


async def call_local_model_async(
    prompt: str,
    context: dict[str, Any],
    session_memory: str = "",
    route_mode: str = "LOCAL",
    model: str | None = None,
) -> str:
    """Call local model asynchronously using Python-native path."""
    logger.debug(f"Calling local model async with prompt: {prompt[:50]}...")

    try:
        from router_py.local_answer import LocalAnswer, LocalAnswerConfig
    except ImportError:
        return "Error: LocalAnswer module not available"

    config = LocalAnswerConfig.from_env()
    if model:
        config.model = str(model)
        logger.info(f"[MODEL] Async local model set to: {model}")

    answer = LocalAnswer(config)

    if session_memory:
        logger.debug(f"Using provided session memory ({len(session_memory)} chars)")

    try:
        result = await answer.generate_answer(
            query=prompt,
            session_memory=session_memory,
            route_mode=route_mode,
        )
        return result.text
    except Exception as e:
        logger.warning(f"Local model failed: {e}")
        return f"Error: Local model failed to generate response. {e}"
