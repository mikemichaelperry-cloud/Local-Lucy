#!/usr/bin/env python3
"""
Weather Provider - Fetches current weather from wttr.in (no API key required).

This module provides real-time weather data for queries like "what's the weather
in London?". It uses wttr.in which is free, reliable, and requires no API key.

v1 (2026-05-09):
- Async fetching via aiohttp
- JSON parsing for structured data
- Graceful fallback to error message on failure
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


def _extract_location(query: str) -> str | None:
    """Extract city/location from a weather query."""
    q = query.lower().strip()
    # Remove common prefixes
    patterns = [
        r"what'?s\s+the\s+weather\s+like\s+(in|at|for|near)\s+",
        r"what'?s\s+the\s+weather\s+(in|at|for|near)\s+",
        r"weather\s+like\s+(in|at|for|near)\s+",
        r"weather\s+(in|at|for|near)\s+",
        r"how'?s\s+the\s+weather\s+like\s+(in|at|for|near)\s+",
        r"how'?s\s+the\s+weather\s+(in|at|for|near)\s+",
        r"will\s+it\s+rain\s+(in|at|for|near)\s+",
        r"is\s+it\s+sunny\s+(in|at|for|near)\s+",
        r"temperature\s+(in|at|for|near)\s+",
        r"forecast\s+(for|in|at)\s+",
        r"do\s+i\s+need\s+(an?\s+)?(jacket|umbrella|coat|raincoat)\s+(in|at|for|near)?\s*",
        r"should\s+i\s+bring\s+(an?\s+)?(jacket|umbrella|coat|raincoat)\s+(in|at|for|near)?\s*",
    ]
    for pat in patterns:
        m = re.search(pat, q)
        if m:
            loc = q[m.end() :].strip()
            # Remove trailing punctuation
            loc = re.sub(r"[?.,!]+$", "", loc)
            # Strip trailing temporal/filler phrases that are not part of the location
            loc = re.sub(
                r"\s+(at the moment|right now|currently|as of now|for now|"
                r"today|tonight|tomorrow|this week|this weekend|"
                r"for today|for tonight|for tomorrow|for me|please)\s*$",
                "",
                loc,
            )
            loc = loc.strip()
            return loc if loc else None
    # Fallback: look for capitalized words or known cities
    return None


async def _fetch_wttr(location: str) -> dict[str, Any] | None:
    """Fetch weather from wttr.in for a location."""
    # wttr.in uses + for spaces, ~ for approximate
    safe_loc = location.replace(" ", "+")
    url = f"https://wttr.in/{safe_loc}?format=j1"
    headers = {"User-Agent": "curl/7.68.0"}  # wttr.in blocks some user agents
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"wttr.in returned {resp.status} for {location}")
                    return None
                text = await resp.text()
                return json.loads(text)
    except asyncio.TimeoutError:
        logger.warning(f"wttr.in timeout for {location}")
        return None
    except Exception as e:
        logger.warning(f"wttr.in error for {location}: {e}")
        return None


def _format_weather(data: dict[str, Any], requested_location: str) -> dict[str, Any]:
    """Format wttr.in JSON into a structured weather result."""
    try:
        current = data["current_condition"][0]
        area = data.get("nearest_area", [{}])[0]
        area_name = area.get("areaName", [{}])[0].get("value", requested_location)
        country = area.get("country", [{}])[0].get("value", "")
        region = area.get("region", [{}])[0].get("value", "")

        # Use the requested location in the header; note resolved area if it differs
        display_name = requested_location.title()
        resolved_name = f"{area_name}, {country}" if country else area_name
        loc_note = (
            f" (resolved to {resolved_name})"
            if resolved_name.lower() != requested_location.lower()
            else ""
        )

        temp_c = current.get("temp_C", "?")
        temp_f = current.get("temp_F", "?")
        feels_c = current.get("FeelsLikeC", "?")
        desc = current.get("weatherDesc", [{}])[0].get("value", "unknown")
        humidity = current.get("humidity", "?")
        wind = current.get("windspeedKmph", "?")
        wind_dir = current.get("winddir16Point", "")
        precip = current.get("precipMM", "0")
        visibility = current.get("visibility", "?")
        uv = current.get("uvIndex", "?")

        # Build text response
        lines = [
            f"Current weather in {display_name}:{loc_note}",
            f"  {desc}, {temp_c}°C ({temp_f}°F). Feels like {feels_c}°C.",
            f"  Humidity: {humidity}%, Wind: {wind} km/h {wind_dir}",
        ]
        if precip and float(precip) > 0:
            lines.append(f"  Precipitation: {precip}mm")
        if visibility and visibility != "?":
            lines.append(f"  Visibility: {visibility} km")
        if uv and uv != "?":
            lines.append(f"  UV Index: {uv}")

        # Hourly forecast (next 3 hours)
        today = data.get("weather", [{}])[0]
        hourly = today.get("hourly", [])[:3]
        if hourly:
            lines.append("  Next few hours:")
            for h in hourly:
                time_str = h.get("time", "?")
                # time is "0", "300", "600" etc — convert to HH:00
                if time_str.isdigit():
                    hour = int(time_str) // 100
                    time_str = f"{hour:02d}:00"
                h_temp = h.get("tempC", "?")
                h_desc = h.get("weatherDesc", [{}])[0].get("value", "")
                lines.append(f"    {time_str}: {h_desc}, {h_temp}°C")

        text = "\n".join(lines)

        return {
            "ok": True,
            "text": text,
            "formatted": text,
            "location": display_name,
            "resolved_location": resolved_name,
            "temp_c": temp_c,
            "temp_f": temp_f,
            "description": desc,
            "humidity": humidity,
            "wind_kmph": wind,
            "wind_dir": wind_dir,
            "precip_mm": precip,
            "uv_index": uv,
            "raw": data,
        }
    except (KeyError, IndexError, ValueError) as e:
        logger.warning(f"Failed to parse wttr.in response: {e}")
        return {
            "ok": False,
            "error": f"Could not parse weather data: {e}",
        }


async def fetch_weather(question: str) -> dict[str, Any]:
    """Fetch weather for a query string.

    Returns a dict with:
        ok: bool
        text: str (human-readable weather report)
        formatted: str (same as text)
        location: str (user's requested location)
        resolved_location: str (wttr.in resolved area)
        ... and various weather fields
    """
    location = _extract_location(question)
    if not location:
        # Try to guess from common patterns
        q = question.lower()
        # Simple fallback: look for "in X" or "for X" at end
        m = re.search(r"\b(in|at|for|near)\s+([a-z\s]+)$", q)
        if m:
            location = m.group(2).strip()
        else:
            # Default to a generic location or ask user
            return {
                "ok": False,
                "error": "Please specify a city or location for the weather forecast.",
            }

    data = await _fetch_wttr(location)
    if not data:
        return {
            "ok": False,
            "error": f"Could not fetch weather for '{location}'. Please try a major city name.",
        }

    return _format_weather(data, location)
