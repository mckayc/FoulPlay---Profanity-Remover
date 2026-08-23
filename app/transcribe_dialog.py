"""Progress dialog that extracts audio and runs transcription in the
background, then reports the resulting Transcript back to the caller.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from core import media
from core.transcribe import transcribe_audio
from core.transcript import Transcript
from settings.config import PerformanceSettings


class _TranscribeWorker(QThread):
    status = Signal(str)
    progress = Signal(int)  # 0-100
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
            self.failed.emit(str(exc))


class TranscribeProgressDialog(QDialog):
    def __init__(self, video_path: Path, performance: PerformanceSettings, workdir: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Transcribing")
        self.resize(420, 140)
        self.setModal(True)

        self.transcript: Transcript | None = None
        self.error: str | None = None

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Starting...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)

        self._worker = _TranscribeWorker(video_path, performance, workdir)
        self._worker.status.connect(self.status_label.setText)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)

    def start(self) -> None:
        self._worker.start()

    def _on_success(self, transcript: Transcript) -> None:
        self.transcript = transcript
        self.accept()

    def _on_failure(self, message: str) -> None:
        self.error = message
        self.reject()
