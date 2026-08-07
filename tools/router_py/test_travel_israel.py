#!/usr/bin/env python3
"""Tests for Israel-specific travel destination extraction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unverified_context_trusted import _extract_travel_destination


def test_israel_destination_extraction():
    assert _extract_travel_destination("recommend places to visit in Israel") == "Israel"
    assert _extract_travel_destination("what should I see in Jerusalem?") == "Jerusalem"


def test_things_to_do_in_tel_aviv():
    assert _extract_travel_destination("things to do in Tel Aviv") == "Tel Aviv"


def test_eretz_variant_maps_to_israel():
    assert _extract_travel_destination("visit Eretz Israel") == "Israel"


def test_known_israel_destinations():
    assert _extract_travel_destination("guide to Haifa") == "Haifa"
    assert _extract_travel_destination("what to see in Eilat") == "Eilat"
    assert _extract_travel_destination("places to visit in Galilee") == "Galilee"
    assert _extract_travel_destination("things to do in the Dead Sea") == "Dead Sea"
    assert _extract_travel_destination("travel to the Negev") == "Negev"


def test_non_travel_israel_query_returns_none():
    assert _extract_travel_destination("News from Israel") is None


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
