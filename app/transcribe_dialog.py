"""Transcription page: extracts audio and runs transcription in the
background, showing progress and a curated activity log inline instead of
in a separate window. When a subtitle was supplied, transcription runs via
the subtitle-assisted hybrid pipeline instead of a single Whisper pass.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from core import media
from core.hybrid_transcribe import HybridStats, hybrid_transcribe
from core.profanity_matcher import find_matches
from core.transcribe import transcribe_audio
from core.transcript import Transcript
from settings.config import PerformanceSettings, WordEntry

from .activity_log import ActivityLog

logger = logging.getLogger(__name__)


def _format_position(seconds: float) -> str:
    minutes, secs = divmod(max(seconds, 0), 60)
    return f"{int(minutes)}:{int(secs):02d}"


def _format_ts(seconds: float) -> str:
    minutes, secs = divmod(max(seconds, 0), 60)
    return f"{int(minutes)}:{int(secs):02d}"


class _TranscribeWorker(QThread):
    status = Signal(str)
    progress = Signal(int)  # 0-100
    position = Signal(float, float)  # (seconds_transcribed, total_seconds)
    log_event = Signal(str)
    finished_ok = Signal(object, object)  # (Transcript, HybridStats)
    failed = Signal(str)

    def __init__(
        self,
        video_path: Path,
        subtitle_path: Path | None,
        performance: PerformanceSettings,
        word_entries: list[WordEntry],
        workdir: Path,
    ) -> None:
        super().__init__()
        self._video_path = video_path
        self._subtitle_path = subtitle_path
        self._performance = performance
        self._word_entries = word_entries
        self._workdir = workdir

    def run(self) -> None:
        try:
            def on_progress(seconds_done: float, total_seconds: float) -> None:
                if total_seconds > 0:
                    pct = 10 + int(85 * min(seconds_done / total_seconds, 1.0))
                    self.progress.emit(pct)
                self.position.emit(seconds_done, total_seconds)

            if self._subtitle_path is not None:
                self.status.emit("Transcribing with subtitle safety net...")
                self.progress.emit(5)
                transcript, stats = hybrid_transcribe(
                    self._video_path,
                    self._subtitle_path,
                    self._performance,
                    self._word_entries,
                    self._workdir,
                    on_event=self.log_event.emit,
                    on_progress=on_progress,
                )
            else:
                self.status.emit("Extracting audio...")
                self.progress.emit(5)
                audio_path = self._workdir / "extracted_audio.wav"
                media.extract_audio(self._video_path, audio_path)

                self.status.emit("Transcribing (this can take a while for a full movie)...")
                transcript = transcribe_audio(
                    audio_path,
                    model_size=self._performance.whisper_model_size,
                    language=self._performance.whisper_language,
                    vad_filter=self._performance.whisper_vad_filter,
                    beam_size=self._performance.whisper_beam_size,
                    prefer_gpu=self._performance.prefer_gpu,
                    on_progress=on_progress,
                )
                stats = HybridStats()
                for m in find_matches(transcript, self._word_entries):
                    self.log_event.emit(f"Found flagged word '{m.matched_term}' at {_format_ts(m.word.start)}")

            self.progress.emit(100)
            self.finished_ok.emit(transcript, stats)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Transcription worker failed")
            self.failed.emit(str(exc))


class TranscribePage(QWidget):
    finished_ok = Signal(object, object)  # (Transcript, HybridStats)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.transcript: Transcript | None = None
        self.stats: HybridStats = HybridStats()
        self.error: str | None = None
        self._worker: _TranscribeWorker | None = None

        layout = QVBoxLayout(self)
        layout.addStretch(1)

        title = QLabel("<h2>Transcribing</h2>")
        layout.addWidget(title)

        self.status_label = QLabel("Starting...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.position_label = QLabel("")
        self.position_label.setProperty("muted", True)
        layout.addWidget(self.position_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.activity_log = ActivityLog()
        layout.addWidget(self.activity_log)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        layout.addWidget(self.cancel_button)

        layout.addStretch(2)

    def start(
        self,
        video_path: Path,
        subtitle_path: Path | None,
        performance: PerformanceSettings,
        word_entries: list[WordEntry],
        workdir: Path,
    ) -> None:
        self.transcript = None
        self.stats = HybridStats()
        self.error = None
        self.status_label.setText("Starting...")
        self.position_label.setText("")
        self.progress_bar.setValue(0)
        self.activity_log.reset()

        self._worker = _TranscribeWorker(video_path, subtitle_path, performance, word_entries, workdir)
        self._worker.status.connect(self.status_label.setText)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.position.connect(self._on_position)
        self._worker.log_event.connect(self.activity_log.append_event)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_position(self, seconds_done: float, total_seconds: float) -> None:
        if total_seconds > 0:
            self.position_label.setText(
                f"Transcribed {_format_position(seconds_done)} of ~{_format_position(total_seconds)}"
            )

    def _on_success(self, transcript: Transcript, stats: HybridStats) -> None:
        self.transcript = transcript
        self.stats = stats
        self.finished_ok.emit(transcript, stats)

    def _on_failure(self, message: str) -> None:
        self.error = message
        self.failed.emit(message)
