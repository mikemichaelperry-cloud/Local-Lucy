"""
Provider modules for ExecutionEngine.

Each module handles one external source (Wikipedia, OpenAI, Kimi, weather, time, news).
This keeps the ExecutionEngine focused on dispatch logic only.
"""

from router_py.providers.evidence import (
    fetch_wikipedia_evidence,
    fetch_api_evidence,
    fetch_time_evidence,
    fetch_weather_evidence,
    fetch_news_evidence,
    fetch_trusted_evidence,
    format_time_response,
)
from router_py.providers.wikipedia import format_wikipedia_response
from router_py.providers.openai import call_openai_for_response, call_openai_subprocess
from router_py.providers.kimi import call_kimi_for_response, call_kimi_subprocess
from router_py.providers.local import call_local_model_async

__all__ = [
    "fetch_wikipedia_evidence",
    "fetch_api_evidence",
    "fetch_time_evidence",
    "fetch_weather_evidence",
    "fetch_news_evidence",
    "fetch_trusted_evidence",
    "format_time_response",
    "format_wikipedia_response",
    "call_openai_for_response",
    "call_openai_subprocess",
    "call_kimi_for_response",
    "call_kimi_subprocess",
    "call_local_model_async",
]
