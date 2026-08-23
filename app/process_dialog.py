"""Progress dialog for the processing stage: dialogue isolation, per-word
audio edits, remix, subtitle generation, and final MKV mux.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from core import media, mux, subtitle_gen
from core.audio_edit import edit_vocals, remix
from core.audio_isolate import separate_dialogue
from core.transcript import Transcript
from projects.project_file import EditDecision
from settings.config import AppSettings


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
            self.progress.emit(15)
            separated_dir = self._workdir / "separated"
            vocals, accompaniment = separate_dialogue(
                audio_path, separated_dir, prefer_gpu=self._settings.performance.prefer_gpu, on_output=None
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
            clean_srt_path = None
            forced_srt_path = None
            if self._settings.subtitles.generate_clean_track:
                clean_subs = subtitle_gen.build_clean_subtitles(self._transcript, self._edits)
                clean_srt_path = self._workdir / "clean.srt"
                clean_subs.save(str(clean_srt_path))
            if self._settings.subtitles.generate_forced_track:
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
                clean_subtitles_srt=clean_srt_path,
                forced_subtitles_srt=forced_srt_path,
            )

            self.progress.emit(100)
            self.finished_ok.emit(self._output_path)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class ProcessProgressDialog(QDialog):
    def __init__(
        self,
        video_path: Path,
        transcript: Transcript,
        edits: list[EditDecision],
        settings: AppSettings,
        workdir: Path,
        output_path: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Processing")
        self.resize(460, 140)
        self.setModal(True)

        self.output_path: Path | None = None
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

        self._worker = _ProcessWorker(video_path, transcript, edits, settings, workdir, output_path)
        self._worker.status.connect(self.status_label.setText)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)

    def start(self) -> None:
        self._worker.start()

    def _on_success(self, output_path: Path) -> None:
        self.output_path = output_path
        self.accept()

    def _on_failure(self, message: str) -> None:
        self.error = message
        self.reject()
