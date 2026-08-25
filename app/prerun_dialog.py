"""Pre-run confirmation screen: shown after Import (and subtitle
selection) but before transcription actually starts, so the user can see
what they're committing to -- an estimated time based on the chosen
Whisper model and video length, plus (if a subtitle was supplied) a quick
text-only sample of what it suggests will be flagged -- and back out if
something looks off. Shown whether or not a subtitle was supplied.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core import media
from core.estimate import estimate_transcription_minutes, format_minutes_range
from core.hybrid_transcribe import baseline_model_size, load_subtitle_events, pseudo_transcript_from_events
from core.profanity_matcher import find_matches
from core.transcribe import pick_device_and_compute_type
from settings.config import AppSettings

logger = logging.getLogger(__name__)


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {secs}s"


class PreRunPage(QWidget):
    continued = Signal()
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch(1)

        title = QLabel("<h2>Ready to transcribe</h2>")
        layout.addWidget(title)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.subtitle_box = QGroupBox("Subtitle preview")
        subtitle_layout = QVBoxLayout(self.subtitle_box)
        self.subtitle_label = QLabel("")
        self.subtitle_label.setWordWrap(True)
        subtitle_layout.addWidget(self.subtitle_label)
        layout.addWidget(self.subtitle_box)
        self.subtitle_box.setVisible(False)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.cancelled.emit)
        row.addWidget(cancel_button)
        continue_button = QPushButton("Continue")
        continue_button.setProperty("accent", True)
        continue_button.clicked.connect(self.continued.emit)
        row.addWidget(continue_button)
        layout.addLayout(row)

        layout.addStretch(2)

    def set_up(self, video_path: Path, subtitle_path: Path | None, settings: AppSettings) -> None:
        probe = media.probe(video_path)
        duration = probe.duration_seconds
        size_str = _format_size(video_path.stat().st_size)

        model = baseline_model_size(settings.performance)
        device, _compute = pick_device_and_compute_type(settings.performance.prefer_gpu)
        use_gpu = device == "cuda"
        low, high = estimate_transcription_minutes(duration, model, use_gpu)
        estimate_str = format_minutes_range(low, high)

        self.summary_label.setText(
            f"<b>Video:</b> {_format_duration(duration)} ({size_str})<br>"
            f"<b>Whisper model:</b> {model} ({'GPU' if use_gpu else 'CPU'})<br><br>"
            f"Based on this, transcription will likely take approximately <b>{estimate_str}</b> to complete. "
            "Processing (dialogue isolation, muting, muxing) after you review the results will take additional "
            "time on top of that."
        )

        self._set_up_subtitle_preview(subtitle_path, settings)

    def _set_up_subtitle_preview(self, subtitle_path: Path | None, settings: AppSettings) -> None:
        if subtitle_path is None:
            self.subtitle_box.setVisible(False)
            return

        try:
            events = load_subtitle_events(subtitle_path)
            pseudo = pseudo_transcript_from_events(events)
            matches = find_matches(pseudo, settings.words)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not preview subtitle %s: %s", subtitle_path, exc)
            self.subtitle_box.setVisible(False)
            return

        if not matches:
            self.subtitle_label.setText("No flagged words found in the subtitle text.")
            self.subtitle_box.setVisible(True)
            return

        counts = Counter(m.matched_term for m in matches)
        sample = ", ".join(f"{term} ({n})" if n > 1 else term for term, n in counts.most_common(8))
        more = "" if len(counts) <= 8 else f", and {len(counts) - 8} more"
        self.subtitle_label.setText(
            f"Based on a quick text scan of the subtitle, found {len(matches)} instance(s) of "
            f"{len(counts)} flagged word/phrase(s): {sample}{more}.<br><br>"
            "<i>This is only a text scan of the subtitle, not a confirmed transcription -- the actual review "
            "after transcription may find more, fewer, or different results.</i>"
        )
        self.subtitle_box.setVisible(True)
