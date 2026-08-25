"""Reusable curated activity-log panel.

Deliberately shows discrete, nameable pipeline events (a flagged word
found, a subtitle/fast-pass mismatch, a re-check with a better model) --
not a verbatim word-for-word transcript -- per explicit user preference.
"""

from __future__ import annotations

import time

from PySide6.QtWidgets import QPlainTextEdit


class ActivityLog(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.setFixedHeight(140)
        self._start_time: float | None = None

    def reset(self) -> None:
        self.clear()
        self._start_time = time.monotonic()

    def append_event(self, message: str) -> None:
        if self._start_time is None:
            self._start_time = time.monotonic()
        elapsed = time.monotonic() - self._start_time
        minutes, secs = divmod(int(elapsed), 60)
        self.appendPlainText(f"[{minutes}:{secs:02d}] {message}")
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
