"""Transcription page: extracts audio and runs transcription in the
background, showing progress inline instead of in a separate window.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from core import media
from core.transcribe import transcribe_audio
from core.transcript import Transcript
from settings.config import PerformanceSettings

logger = logging.getLogger(__name__)


def _format_position(seconds: float) -> str:
    minutes, secs = divmod(max(seconds, 0), 60)
    return f"{int(minutes)}:{int(secs):02d}"


class _TranscribeWorker(QThread):
    status = Signal(str)
    progress = Signal(int)  # 0-100
    position = Signal(float, float)  # (seconds_transcribed, total_seconds)
    finished_ok = Signal(object)  # Transcript
    failed = Signal(str)

    def __init__(self, video_path: Path, performance: PerformanceSettings, workdir: Path) -> None:
        super().__init__()
        self._video_path = video_path
        self._performance = performance
        self._workdir = workdir

    def run(self) -> None:
        try:
            self.status.emit("Extracting audio...")
            self.progress.emit(5)
            audio_path = self._workdir / "extracted_audio.wav"
            media.extract_audio(self._video_path, audio_path)

            self.status.emit("Transcribing (this can take a while for a full movie)...")

            def on_progress(seconds_done: float, total_seconds: float) -> None:
                if total_seconds > 0:
                    pct = 10 + int(85 * min(seconds_done / total_seconds, 1.0))
                    self.progress.emit(pct)
                self.position.emit(seconds_done, total_seconds)

            transcript = transcribe_audio(
                audio_path,
                model_size=self._performance.whisper_model_size,
                language=self._performance.whisper_language,
                vad_filter=self._performance.whisper_vad_filter,
                beam_size=self._performance.whisper_beam_size,
                prefer_gpu=self._performance.prefer_gpu,
                on_progress=on_progress,
            )
            self.progress.emit(100)
            self.finished_ok.emit(transcript)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Transcription worker failed")
            self.failed.emit(str(exc))


class TranscribePage(QWidget):
    finished_ok = Signal(object)  # Transcript
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.transcript: Transcript | None = None
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

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        layout.addWidget(self.cancel_button)

        layout.addStretch(2)

    def start(self, video_path: Path, performance: PerformanceSettings, workdir: Path) -> None:
        self.transcript = None
        self.error = None
        self.status_label.setText("Starting...")
        self.position_label.setText("")
        self.progress_bar.setValue(0)

        self._worker = _TranscribeWorker(video_path, performance, workdir)
        self._worker.status.connect(self.status_label.setText)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.position.connect(self._on_position)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_position(self, seconds_done: float, total_seconds: float) -> None:
        if total_seconds > 0:
            self.position_label.setText(
                f"Transcribed {_format_position(seconds_done)} of ~{_format_position(total_seconds)}"
            )

    def _on_success(self, transcript: Transcript) -> None:
        self.transcript = transcript
        self.finished_ok.emit(transcript)

    def _on_failure(self, message: str) -> None:
        self.error = message
        self.failed.emit(message)
