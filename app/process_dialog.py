"""Processing page: dialogue isolation, per-word audio edits, remix,
subtitle generation, and final MKV mux, with progress shown inline instead
of in a separate window.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from core import media, mux, subtitle_gen
from core.audio_edit import edit_vocals, remix
from core.audio_isolate import separate_dialogue
from core.report_gen import save_change_report
from core.transcript import Transcript
from projects.project_file import EditDecision
from settings.config import AppSettings

logger = logging.getLogger(__name__)

_ISOLATION_RANGE = (15, 55)  # progress band mapped from Demucs's own 0-100%


class _ProcessWorker(QThread):
    status = Signal(str)
    progress = Signal(int)
    finished_ok = Signal(object)  # output Path
    failed = Signal(str)

    def __init__(
        self,
        video_path: Path,
        transcript: Transcript,
        edits: list[EditDecision],
        settings: AppSettings,
        workdir: Path,
        output_path: Path,
    ) -> None:
        super().__init__()
        self._video_path = video_path
        self._transcript = transcript
        self._edits = edits
        self._settings = settings
        self._workdir = workdir
        self._output_path = output_path

    def run(self) -> None:
        try:
            self.status.emit("Extracting audio...")
            self.progress.emit(5)
            audio_path = self._workdir / "source_audio.wav"
            media.extract_audio(self._video_path, audio_path)

            self.status.emit("Isolating dialogue from music/effects (this can take a while)...")
            self.progress.emit(_ISOLATION_RANGE[0])
            separated_dir = self._workdir / "separated"

            def on_isolation_progress(percent: int) -> None:
                low, high = _ISOLATION_RANGE
                self.progress.emit(low + int((high - low) * percent / 100))

            vocals, accompaniment = separate_dialogue(
                audio_path,
                separated_dir,
                prefer_gpu=self._settings.performance.prefer_gpu,
                on_output=None,
                on_progress=on_isolation_progress,
            )

            self.status.emit("Editing flagged words...")
            self.progress.emit(60)
            edited_vocals_path = self._workdir / "edited_vocals.wav"
            edit_vocals(
                vocals, self._transcript, self._edits, self._settings.audio_edit, edited_vocals_path
            )

            self.status.emit("Remixing dialogue with music/effects...")
            self.progress.emit(75)
            cleaned_audio_path = self._workdir / "cleaned_audio.wav"
            remix(edited_vocals_path, accompaniment, cleaned_audio_path)

            self.status.emit("Generating subtitles...")
            self.progress.emit(85)
            unedited_subs = subtitle_gen.build_unedited_subtitles(self._transcript)
            unedited_srt_path = self._workdir / "unedited.srt"
            unedited_subs.save(str(unedited_srt_path))

            clean_subs = subtitle_gen.build_clean_subtitles(self._transcript, self._edits)
            clean_srt_path = self._workdir / "clean.srt"
            clean_subs.save(str(clean_srt_path))

            forced_subs = subtitle_gen.build_forced_subtitles(
                self._transcript, self._edits, self._settings.subtitles.forced_text_mode
            )
            forced_srt_path = self._workdir / "forced.srt"
            forced_subs.save(str(forced_srt_path))

            self.status.emit("Muxing final file...")
            self.progress.emit(95)
            probe = media.probe(self._video_path)
            mux.mux_final(
                source_video=self._video_path,
                cleaned_audio_wav=cleaned_audio_path,
                output_path=self._output_path,
                original_audio_count=len(probe.audio_streams),
                original_subtitle_count=len(probe.subtitle_streams),
                unedited_subtitles_srt=unedited_srt_path,
                clean_subtitles_srt=clean_srt_path,
                forced_subtitles_srt=forced_srt_path,
            )

            self.status.emit("Writing change report...")
            self.progress.emit(98)
            report_path = self._output_path.with_name(f"{self._output_path.stem} - Changes.txt")
            save_change_report(self._video_path, self._transcript, self._edits, report_path)

            self.progress.emit(100)
            self.finished_ok.emit(self._output_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Processing worker failed")
            self.failed.emit(str(exc))


class ProcessPage(QWidget):
    finished_ok = Signal(object)  # output Path
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.output_path: Path | None = None
        self.error: str | None = None
        self._worker: _ProcessWorker | None = None

        layout = QVBoxLayout(self)
        layout.addStretch(1)

        title = QLabel("<h2>Processing</h2>")
        layout.addWidget(title)

        self.status_label = QLabel("Starting...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        layout.addWidget(self.cancel_button)

        layout.addStretch(2)

    def start(
        self,
        video_path: Path,
        transcript: Transcript,
        edits: list[EditDecision],
        settings: AppSettings,
        workdir: Path,
        output_path: Path,
    ) -> None:
        self.output_path = None
        self.error = None
        self.status_label.setText("Starting...")
        self.progress_bar.setValue(0)

        self._worker = _ProcessWorker(video_path, transcript, edits, settings, workdir, output_path)
        self._worker.status.connect(self.status_label.setText)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, output_path: Path) -> None:
        self.output_path = output_path
        self.finished_ok.emit(output_path)

    def _on_failure(self, message: str) -> None:
        self.error = message
        self.failed.emit(message)
