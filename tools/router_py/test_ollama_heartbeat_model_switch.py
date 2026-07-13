#!/usr/bin/env python3
"""Regression tests for Ollama heartbeat model-switch behaviour."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import router_py.local_answer as local_answer
from router_py.local_answer import (
    LocalAnswer,
    _OllamaWarmupThread,
    start_ollama_heartbeat,
    stop_ollama_heartbeat,
)


def test_heartbeat_stops_pinging_old_model_after_switch():
    """When the model changes, the previous heartbeat thread must not reload it."""
    stop_ollama_heartbeat()
    if local_answer._heartbeat_thread is not None:
        local_answer._heartbeat_thread.join(timeout=1.0)
    local_answer._heartbeat_thread = None
    local_answer._heartbeat_model = None
    local_answer._heartbeat_stop.clear()

    pings: list[tuple[str, float]] = []
    original_ping = local_answer._ollama_heartbeat_ping

    def fake_ping(model: str) -> None:
        pings.append((model, time.monotonic()))
        # Simulate the time a real Ollama ping takes to load a model.
        time.sleep(0.05)

    local_answer._ollama_heartbeat_ping = fake_ping
    try:
        # Start a fast heartbeat for the old model.
        local_answer._heartbeat_model = "old-model"
        local_answer._heartbeat_stop.clear()
        old_thread = threading.Thread(
            target=local_answer._heartbeat_loop,
            args=("old-model", 0.02),
            daemon=True,
        )
        old_thread.start()
        time.sleep(0.06)  # let it ping at least once

        switch_time = time.monotonic()
        # Simulate the HMI switching to a new model.
        start_ollama_heartbeat("new-model")
        time.sleep(0.1)  # give the old thread time to finish any in-flight ping

        old_pings_after_switch = [m for m, t in pings if m == "old-model" and t >= switch_time]
        assert not old_pings_after_switch, f"Old heartbeat reloaded old-model after switch: {pings}"
    finally:
        local_answer._ollama_heartbeat_ping = original_ping
        stop_ollama_heartbeat()
        if local_answer._heartbeat_thread is not None:
            local_answer._heartbeat_thread.join(timeout=1.0)


def test_recurring_warmup_replaces_thread_on_model_change():
    """When the model changes, the previous recurring warmup thread is stopped."""
    if LocalAnswer._warmup_thread is not None:
        LocalAnswer._warmup_thread.stop()
        LocalAnswer._warmup_thread.join(timeout=1.0)
    LocalAnswer._warmup_thread = None
    LocalAnswer._warmup_done = False

    pings: list[str] = []
    original_ping = _OllamaWarmupThread._ping

    def fake_ping(self: _OllamaWarmupThread) -> None:
        # Do not ping if a newer thread has already replaced this one.
        if LocalAnswer._warmup_thread is not None and LocalAnswer._warmup_thread is not self:
            return
        pings.append(self.model)

    _OllamaWarmupThread._ping = fake_ping
    try:
        old_thread = _OllamaWarmupThread(
            interval_s=300,
            model="old-model",
            api_url="http://127.0.0.1:11434/api/generate",
            keep_alive="5m",
        )
        LocalAnswer._warmup_thread = old_thread
        old_thread.start()

        # Simulate switching to a new model.
        new_thread = _OllamaWarmupThread(
            interval_s=300,
            model="new-model",
            api_url="http://127.0.0.1:11434/api/generate",
            keep_alive="5m",
        )
        old_thread.stop()
        old_thread.join(timeout=1.0)
        LocalAnswer._warmup_thread = new_thread
        new_thread.start()
        time.sleep(0.05)

        assert not old_thread.is_alive(), "Old warmup thread should have stopped"
        assert LocalAnswer._warmup_thread is new_thread
        assert "old-model" not in pings, f"Old model should not be pinged after switch: {pings}"
    finally:
        _OllamaWarmupThread._ping = original_ping
        if LocalAnswer._warmup_thread is not None:
            LocalAnswer._warmup_thread.stop()
            LocalAnswer._warmup_thread.join(timeout=1.0)
        LocalAnswer._warmup_thread = None
