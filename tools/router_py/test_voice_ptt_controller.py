#!/usr/bin/env python3
"""Tests for voice_runtime PTTController."""

import asyncio
from pathlib import Path

import pytest

try:
    from .voice_runtime import PTTController
except ImportError:
    from voice_runtime import PTTController


class TestPTTControllerHold:
    """Hold-mode PTT: press starts, release stops."""

    @pytest.fixture
    def ptt(self):
        return PTTController(mode="hold", max_seconds=2.0)

    @pytest.mark.asyncio
    async def test_press_starts_recording(self, ptt):
        assert not ptt.is_recording()
        started = await ptt.press()
        assert started is True
        assert ptt.is_recording()

    @pytest.mark.asyncio
    async def test_release_stops_recording(self, ptt):
        await ptt.press()
        stopped = await ptt.release()
        assert stopped is True
        assert not ptt.is_recording()

    @pytest.mark.asyncio
    async def test_release_when_not_recording_is_noop(self, ptt):
        stopped = await ptt.release()
        assert stopped is False
        assert not ptt.is_recording()

    @pytest.mark.asyncio
    async def test_double_press_ignored(self, ptt):
        await ptt.press()
        started_again = await ptt.press()
        assert started_again is False
        assert ptt.is_recording()

    @pytest.mark.asyncio
    async def test_wait_for_stop_returns_true_on_release(self, ptt):
        await ptt.press()
        # Simulate release after short delay
        asyncio.get_event_loop().call_later(0.1, lambda: asyncio.create_task(ptt.release()))
        stopped = await ptt.wait_for_stop(timeout=1.0)
        assert stopped is True

    @pytest.mark.asyncio
    async def test_wait_for_stop_returns_false_on_timeout(self, ptt):
        await ptt.press()
        stopped = await ptt.wait_for_stop(timeout=0.1)
        assert stopped is False

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, ptt):
        await ptt.press()
        assert ptt.is_recording()
        ptt.reset()
        assert not ptt.is_recording()


class TestPTTControllerTap:
    """Tap-mode PTT: first tap starts, second tap stops."""

    @pytest.fixture
    def ptt(self):
        return PTTController(mode="tap", max_seconds=2.0)

    @pytest.mark.asyncio
    async def test_first_tap_starts(self, ptt):
        started = await ptt.press()
        assert started is True
        assert ptt.is_recording()

    @pytest.mark.asyncio
    async def test_second_tap_stops(self, ptt):
        await ptt.press()
        started = await ptt.press()  # second tap
        assert started is False
        assert not ptt.is_recording()

    @pytest.mark.asyncio
    async def test_release_in_tap_mode_is_noop(self, ptt):
        await ptt.press()
        stopped = await ptt.release()
        assert stopped is False
        assert ptt.is_recording()

    @pytest.mark.asyncio
    async def test_wait_for_stop_returns_true_on_second_tap(self, ptt):
        await ptt.press()
        asyncio.get_event_loop().call_later(0.1, lambda: asyncio.create_task(ptt.press()))
        stopped = await ptt.wait_for_stop(timeout=1.0)
        assert stopped is True

    @pytest.mark.asyncio
    async def test_wait_for_stop_returns_false_on_timeout(self, ptt):
        await ptt.press()
        stopped = await ptt.wait_for_stop(timeout=0.1)
        assert stopped is False


class TestPTTControllerTimeout:
    """Timeout guards regardless of mode."""

    @pytest.mark.asyncio
    async def test_hold_mode_timeout(self):
        ptt = PTTController(mode="hold", max_seconds=0.2)
        await ptt.press()
        stopped = await ptt.wait_for_stop(timeout=0.2)
        assert stopped is False  # timeout, not signal

    @pytest.mark.asyncio
    async def test_tap_mode_timeout(self):
        ptt = PTTController(mode="tap", max_seconds=0.2)
        await ptt.press()
        stopped = await ptt.wait_for_stop(timeout=0.2)
        assert stopped is False  # timeout, not signal

    @pytest.mark.asyncio
    async def test_custom_timeout_override(self):
        ptt = PTTController(mode="hold", max_seconds=10.0)
        await ptt.press()
        stopped = await ptt.wait_for_stop(timeout=0.1)
        assert stopped is False
