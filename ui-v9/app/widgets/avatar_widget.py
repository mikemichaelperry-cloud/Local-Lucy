"""
Local Lucy Avatar Widget — minimal animated talking head.

Renders a simple face with lip-sync to TTS audio levels.
Uses only QPainter (no external images).  Updates at ~30 FPS with
negligible CPU cost.

Mouth shapes are selected from 5 visemes based on output audio level
(0–100) read from the voice audio levels JSON file.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget


# ---------------------------------------------------------------------------
#  Mouth viseme definitions (QPainterPath, normalised to 0..1 unit space)
# ---------------------------------------------------------------------------

class _Viseme:
    """Pre-built mouth shape as a QPainterPath."""

    def __init__(self, path: QPainterPath, jaw_dy: float = 0.0) -> None:
        self.path = path
        self.jaw_dy = jaw_dy  # vertical jaw offset (fraction of face radius)


def _build_visemes() -> list[_Viseme]:
    """Build 5 mouth shapes from closed to wide open."""
    visemes: list[_Viseme] = []

    # 0 — closed / rest (slight smile line)  [centered around x=0.5]
    p = QPainterPath()
    p.moveTo(0.20, 0.65)
    p.cubicTo(0.35, 0.62, 0.65, 0.62, 0.80, 0.65)
    p.cubicTo(0.65, 0.72, 0.35, 0.72, 0.20, 0.65)
    visemes.append(_Viseme(p, jaw_dy=0.0))

    # 1 — slightly open (M/B/P shape)
    p = QPainterPath()
    p.moveTo(0.20, 0.63)
    p.cubicTo(0.30, 0.58, 0.70, 0.58, 0.80, 0.63)
    p.lineTo(0.80, 0.70)
    p.cubicTo(0.70, 0.76, 0.30, 0.76, 0.20, 0.70)
    p.lineTo(0.20, 0.63)
    visemes.append(_Viseme(p, jaw_dy=0.02))

    # 2 — half open (EH/AH shape)
    p = QPainterPath()
    p.moveTo(0.18, 0.60)
    p.cubicTo(0.28, 0.54, 0.72, 0.54, 0.82, 0.60)
    p.lineTo(0.82, 0.74)
    p.cubicTo(0.72, 0.82, 0.28, 0.82, 0.18, 0.74)
    p.lineTo(0.18, 0.60)
    visemes.append(_Viseme(p, jaw_dy=0.03))

    # 3 — open (AA/AO shape)
    p = QPainterPath()
    p.moveTo(0.16, 0.58)
    p.cubicTo(0.24, 0.50, 0.76, 0.50, 0.84, 0.58)
    p.lineTo(0.84, 0.78)
    p.cubicTo(0.76, 0.88, 0.24, 0.88, 0.16, 0.78)
    p.lineTo(0.16, 0.58)
    visemes.append(_Viseme(p, jaw_dy=0.04))

    # 4 — wide open (AE/IY shape)
    p = QPainterPath()
    p.moveTo(0.14, 0.56)
    p.cubicTo(0.21, 0.46, 0.79, 0.46, 0.86, 0.56)
    p.lineTo(0.86, 0.82)
    p.cubicTo(0.79, 0.92, 0.21, 0.92, 0.14, 0.82)
    p.lineTo(0.14, 0.56)
    visemes.append(_Viseme(p, jaw_dy=0.05))

    return visemes


# ---------------------------------------------------------------------------
#  Avatar widget
# ---------------------------------------------------------------------------

class LucyAvatar(QWidget):
    """Minimal animated talking head for Local Lucy.

    Displays a circular face whose mouth lip-syncs to audio output levels.
    Eyes blink periodically.  Subtle head bob tied to audio energy.
    """

    UPDATE_INTERVAL_MS = 33  # ~30 FPS
    BLINK_INTERVAL_MIN_S = 3.0
    BLINK_INTERVAL_MAX_S = 7.0
    BLINK_DURATION_S = 0.15

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(180, 220)
        self.setMaximumSize(260, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._visemes = _build_visemes()
        self._audio_level = 0.0
        self._target_level = 0.0
        self._is_playing = False

        # Blink state
        self._blink_timer = 0.0
        self._next_blink = self._rand_blink_time()
        self._is_blinking = False

        # Animation timer
        self._timer = QTimer(self)
        self._timer.setInterval(self.UPDATE_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    def set_levels_file(self, path: Path | str | None) -> None:
        """Set the JSON levels file to monitor.  Pass None to disable."""
        self._levels_file = Path(path) if path else None

    # ------------------------------------------------------------------
    #  Animation loop
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        now = time.time()
        dt = self.UPDATE_INTERVAL_MS / 1000.0

        # 1. Read audio level
        self._read_audio_level()

        # 2. Smooth level (exponential decay)
        attack = 0.6  # fast attack
        decay = 0.85  # slower decay
        if self._target_level > self._audio_level:
            self._audio_level = self._audio_level * (1 - attack) + self._target_level * attack
        else:
            self._audio_level = self._audio_level * (1 - decay) + self._target_level * decay

        # 3. Blink logic
        self._blink_timer += dt
        if self._is_blinking:
            if self._blink_timer >= self.BLINK_DURATION_S:
                self._is_blinking = False
                self._blink_timer = 0.0
                self._next_blink = self._rand_blink_time()
        else:
            if self._blink_timer >= self._next_blink:
                self._is_blinking = True
                self._blink_timer = 0.0

        self.update()

    def _read_audio_level(self) -> None:
        path: Path | None = getattr(self, "_levels_file", None)
        if path is None or not path.exists():
            self._target_level = 0.0
            self._is_playing = False
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._target_level = float(data.get("output_level", 0))
            self._is_playing = bool(data.get("playing", False))
        except Exception:
            self._target_level = 0.0
            self._is_playing = False

    def _rand_blink_time(self) -> float:
        return random.uniform(self.BLINK_INTERVAL_MIN_S, self.BLINK_INTERVAL_MAX_S)

    # ------------------------------------------------------------------
    #  Painting
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        face_r = min(w, h) * 0.35

        # Subtle head bob tied to audio level (very slight)
        bob = self._audio_level * 0.003 * face_r
        cy += bob

        # ---- Face circle ----
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#4a90d9"))
        painter.drawEllipse(int(cx - face_r), int(cy - face_r), int(face_r * 2), int(face_r * 2))

        # ---- Eyes ----
        eye_rx = face_r * 0.22
        eye_ry = face_r * 0.28
        eye_y_offset = face_r * 0.15
        eye_sep = face_r * 0.32

        for dx in (-eye_sep, eye_sep):
            self._draw_eye(painter, cx + dx, cy - eye_y_offset, eye_rx, eye_ry)

        # ---- Nose (big prominent rounded triangle) ----
        nose_w = face_r * 0.30
        nose_h = face_r * 0.28
        nose_y = cy + face_r * 0.08
        nose_path = QPainterPath()
        nose_path.moveTo(cx, nose_y - nose_h * 0.4)
        # Left curve
        nose_path.quadTo(cx - nose_w * 0.8, nose_y + nose_h * 0.3, cx - nose_w, nose_y + nose_h)
        # Bottom across
        nose_path.lineTo(cx + nose_w, nose_y + nose_h)
        # Right curve
        nose_path.quadTo(cx + nose_w * 0.8, nose_y + nose_h * 0.3, cx, nose_y - nose_h * 0.4)
        nose_path.closeSubpath()
        # Lighter blue so it pops against face
        painter.setBrush(QColor("#87ceeb"))
        painter.setPen(Qt.NoPen)
        painter.drawPath(nose_path)

        # ---- Mouth (explicitly centered ellipses) ----
        level = min(self._audio_level, 100.0) / 100.0

        # Mouth center: explicitly at cx (no x-offset)
        mouth_cx = cx
        mouth_cy = cy + face_r * 0.56 + level * face_r * 0.06

        # Width: 55% of face diameter, grows slightly with level
        mouth_w = face_r * 1.10 + level * face_r * 0.10
        # Height: grows from 8% to 35% of face radius based on audio level
        mouth_h = face_r * 0.08 + level * face_r * 0.28

        # Dark interior
        painter.setBrush(QColor("#0a0a14"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(mouth_cx - mouth_w / 2), int(mouth_cy - mouth_h / 2), int(mouth_w), int(mouth_h))

        # Bright lip outline
        lip_pen = painter.pen()
        lip_pen.setColor(QColor("#ff6b8a"))
        lip_pen.setWidthF(2.5)
        painter.setPen(lip_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(int(mouth_cx - mouth_w / 2), int(mouth_cy - mouth_h / 2), int(mouth_w), int(mouth_h))

    def _draw_eye(self, painter: QPainter, cx: float, cy: float, rx: float, ry: float) -> None:
        """Draw one eye (white sclera + dark pupil), with blink."""
        painter.setPen(Qt.NoPen)

        if self._is_blinking:
            # Closed eye (thin line)
            painter.setBrush(QColor("#1a1a2e"))
            painter.drawEllipse(int(cx - rx), int(cy - ry * 0.15), int(rx * 2), int(ry * 0.3))
            return

        # Sclera
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(int(cx - rx), int(cy - ry), int(rx * 2), int(ry * 2))

        # Pupil (subtle look-toward-mouse or random drift could go here)
        pr = rx * 0.45
        painter.setBrush(QColor("#1a1a2e"))
        painter.drawEllipse(int(cx - pr), int(cy - pr * 1.1), int(pr * 2), int(pr * 2.2))
