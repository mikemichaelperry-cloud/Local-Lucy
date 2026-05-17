#!/usr/bin/env python3
"""
VU Meter Widget for Local Lucy Voice Interface

A simple LED-style audio level meter with:
- 20 segments (10 green, 6 yellow, 4 red)
- Smooth decay animation
- Configurable orientation (horizontal/vertical)
- Input and output modes
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget


class VUMeter(QWidget):
    """
    LED-style VU meter widget.
    
    Displays audio levels as colored LED segments with smooth decay.
    
    Attributes:
        level_changed: Signal emitted when level changes (int 0-100)
    """
    
    level_changed = Signal(int)
    
    # Number of LED segments
    NUM_SEGMENTS = 20
    
    # Color zones (segment indices)
    GREEN_ZONE = range(0, 10)      # 0-9: Green
    YELLOW_ZONE = range(10, 16)    # 10-15: Yellow
    RED_ZONE = range(16, 20)       # 16-19: Red
    
    # Colors
    COLORS = {
        "green_on": QColor("#2ecc71"),
        "green_off": QColor("#1a5c3a"),
        "yellow_on": QColor("#f1c40f"),
        "yellow_off": QColor("#7d6a1a"),
        "red_on": QColor("#e74c3c"),
        "red_off": QColor("#7d2a22"),
        "background": QColor("#2d3436"),
    }
    
    def __init__(
        self,
        parent: QWidget | None = None,
        orientation: str = "horizontal",
        decay_ms: int = 50,
    ):
        """
        Initialize VU meter.
        
        Args:
            parent: Parent widget
            orientation: "horizontal" or "vertical"
            decay_ms: Decay animation interval in milliseconds
        """
        super().__init__(parent)
        
        self._orientation = orientation
        self._current_level = 0  # 0-100
        self._target_level = 0   # 0-100
        
        # Set minimum size
        if orientation == "horizontal":
            self.setMinimumSize(120, 24)
        else:
            self.setMinimumSize(24, 120)
        
        # Decay timer for smooth animation
        self._decay_timer = QTimer(self)
        self._decay_timer.timeout.connect(self._update_decay)
        self._decay_timer.start(decay_ms)
        
        self.setStyleSheet("background-color: transparent;")
    
    def set_level(self, level: int) -> None:
        """
        Set the current audio level.
        
        Args:
            level: Audio level 0-100
        """
        self._target_level = max(0, min(100, level))
        # Immediate update for rising levels, decay for falling
        if self._target_level > self._current_level:
            self._current_level = self._target_level
            self.update()
            self.level_changed.emit(self._current_level)
    
    def get_level(self) -> int:
        """Get current level (0-100)."""
        return self._current_level
    
    def _update_decay(self) -> None:
        """Smooth decay animation."""
        if self._current_level > self._target_level:
            # Decay by 10% of current level (minimum 2)
            decay = max(2, int(self._current_level * 0.1))
            self._current_level = max(self._target_level, self._current_level - decay)
            self.update()
            self.level_changed.emit(self._current_level)
    
    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the VU meter."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        
        # Calculate segment dimensions
        width = self.width()
        height = self.height()
        
        if self._orientation == "horizontal":
            segment_width = (width - (self.NUM_SEGMENTS + 1)) // self.NUM_SEGMENTS
            segment_height = height - 4
            spacing = 1
        else:
            segment_width = width - 4
            segment_height = (height - (self.NUM_SEGMENTS + 1)) // self.NUM_SEGMENTS
            spacing = 1
        
        # Draw background
        painter.fillRect(self.rect(), self.COLORS["background"])
        
        # Calculate how many segments to light
        segments_lit = int((self._current_level / 100.0) * self.NUM_SEGMENTS)
        
        # Draw segments
        for i in range(self.NUM_SEGMENTS):
            # Determine color
            if i in self.GREEN_ZONE:
                on_color = self.COLORS["green_on"]
                off_color = self.COLORS["green_off"]
            elif i in self.YELLOW_ZONE:
                on_color = self.COLORS["yellow_on"]
                off_color = self.COLORS["yellow_off"]
            else:  # RED_ZONE
                on_color = self.COLORS["red_on"]
                off_color = self.COLORS["red_off"]
            
            # Determine if this segment should be lit
            is_lit = i < segments_lit
            color = on_color if is_lit else off_color
            
            # Calculate position
            if self._orientation == "horizontal":
                x = 2 + i * (segment_width + spacing)
                y = 2
                rect_width = segment_width
                rect_height = segment_height
            else:
                # Vertical: bottom to top (0 at bottom)
                x = 2
                y = height - 2 - (i + 1) * (segment_height + spacing) + spacing
                rect_width = segment_width
                rect_height = segment_height
            
            # Draw segment
            painter.fillRect(x, y, rect_width, rect_height, color)
        
        painter.end()


class VoiceVUMeter(QWidget):
    """
    Combined input/output VU meter for voice interface.
    
    Shows separate meters for:
    - Input (microphone/recording)
    - Output (TTS playback)
    """
    
    def __init__(self, parent: QWidget | None = None):
        """Initialize voice VU meter widget."""
        super().__init__(parent)
        
        from PySide6.QtWidgets import QVBoxLayout, QLabel
        
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Input meter (recording)
        input_label = QLabel("🎤 Input")
        input_label.setStyleSheet("color: #94a5b1; font-size: 10px;")
        layout.addWidget(input_label)
        
        self.input_meter = VUMeter(self, orientation="horizontal")
        layout.addWidget(self.input_meter)
        
        # Output meter (playback)
        output_label = QLabel("🔊 Output")
        output_label.setStyleSheet("color: #94a5b1; font-size: 10px;")
        layout.addWidget(output_label)
        
        self.output_meter = VUMeter(self, orientation="horizontal")
        layout.addWidget(self.output_meter)
        
        self.setStyleSheet("background-color: #1e2529; border-radius: 4px;")
    
    def set_input_level(self, level: int) -> None:
        """Set input (recording) level 0-100."""
        self.input_meter.set_level(level)
    
    def set_output_level(self, level: int) -> None:
        """Set output (playback) level 0-100."""
        self.output_meter.set_level(level)
    
    def reset(self) -> None:
        """Reset both meters to zero."""
        self.input_meter.set_level(0)
        self.output_meter.set_level(0)
