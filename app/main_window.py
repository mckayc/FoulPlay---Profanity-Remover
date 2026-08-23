"""Main application window.

Milestone 1 scope: launch, show hardware detection results, and provide
access to Settings. The step wizard (Import -> Transcribe -> Review ->
Process -> Export) is filled in across later milestones as each pipeline
stage lands.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import media
from core.dependencies import missing_groups
from core.hardware import Accelerator, get_hardware_report
from core.logging_setup import get_log_file_path, read_recent_log_text
from core.profanity_matcher import find_matches
from core.transcript import Transcript
from projects.project_file import EditDecision, default_project_path, load_project, save_project
from settings.config import load_settings

from .dependency_dialog import DependencyInstallDialog
from .ffmpeg_install_dialog import FfmpegInstallDialog
from .process_dialog import ProcessProgressDialog
from .review_dialog import ReviewDialog
from .settings_dialog import SettingsDialog
from .transcribe_dialog import TranscribeProgressDialog

logger = logging.getLogger(__name__)

_ERROR_LOG_HINT = "\n\nIf this keeps happening, use the \"Copy Log\" button to grab diagnostic details."


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FoulPlay - Profanity Remover")
        self.resize(720, 480)

        self.settings = load_settings()

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        title = QLabel("<h2>FoulPlay</h2><p>Create a family-friendly audio &amp; subtitle track for your movies.</p>")
        title.setWordWrap(True)
        layout.addWidget(title)

        hardware_box = QGroupBox("Hardware")
        hardware_layout = QVBoxLayout(hardware_box)
        self.hardware_label = QLabel()
        self.hardware_label.setWordWrap(True)
        hardware_layout.addWidget(self.hardware_label)
        layout.addWidget(hardware_box)
        self._refresh_hardware_report()

        import_button = QPushButton("Import Video...")
        import_button.clicked.connect(self._import_video)
        layout.addWidget(import_button)

        open_project_button = QPushButton("Open Project...")
        open_project_button.setToolTip(
            "Resume a previously transcribed video (.fpproj) without re-transcribing it."
        )
        open_project_button.clicked.connect(self._open_project)
        layout.addWidget(open_project_button)

        settings_button = QPushButton("Settings...")
        settings_button.clicked.connect(self._open_settings)
        layout.addWidget(settings_button)

        layout.addStretch(1)

        log_row = QHBoxLayout()
        log_label = QLabel(f"Log file: {get_log_file_path()}")
        log_label.setWordWrap(True)
        log_row.addWidget(log_label, 1)
        copy_log_button = QPushButton("Copy Log")
        copy_log_button.setToolTip("Copy the diagnostic log to your clipboard to share when something goes wrong.")
        copy_log_button.clicked.connect(self._copy_log)
        log_row.addWidget(copy_log_button)
        layout.addLayout(log_row)

    def _refresh_hardware_report(self) -> None:
        report = get_hardware_report()
        gpu_names = ", ".join(g.name for g in report.gpus) if report.gpus else "None detected"
        accelerator_label = {
            Accelerator.CUDA: "NVIDIA CUDA",
            Accelerator.DIRECTML: "DirectML",
            Accelerator.CPU: "CPU only",
        }[report.recommended_accelerator]
        self.hardware_label.setText(
            f"<b>GPU(s):</b> {gpu_names}<br>"
            f"<b>Selected accelerator:</b> {accelerator_label}<br>"
            f"{report.expectation_message}"
        )

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            logger.info("Settings saved")
            QMessageBox.information(self, "Settings saved", "Your settings have been saved.")

    def _copy_log(self) -> None:
        text = read_recent_log_text()
        QGuiApplication.clipboard().setText(text)
        logger.info("Log copied to clipboard (%d chars)", len(text))
        QMessageBox.information(
            self,
            "Log copied",
            f"The log has been copied to your clipboard.\n\nFull log file:\n{get_log_file_path()}",
        )

    def _import_video(self) -> None:
        logger.info("Import Video clicked")
        if not media.is_ffmpeg_available():
            logger.warning("FFmpeg not available; offering to install")
            ffmpeg_dialog = FfmpegInstallDialog(self)
            ffmpeg_dialog.exec()
            if ffmpeg_dialog.succeeded:
                QMessageBox.information(
                    self, "Restart required", "Please restart FoulPlay, then try importing again."
                )
            return

        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Select a video file",
            "",
            "Video files (*.mkv *.mp4 *.mov *.avi *.m4v);;All files (*.*)",
        )
        if not path_str:
            logger.info("Import cancelled: no file selected")
            return
        video_path = Path(path_str)
        logger.info("Selected video: %s", video_path)

        needed = missing_groups(["asr"])
        if needed:
            logger.info("Missing dependency groups for transcription: %s", [g.key for g in needed])
            dep_dialog = DependencyInstallDialog(needed, self)
            if not dep_dialog.exec() or not dep_dialog.succeeded:
                logger.info("User declined/cancelled dependency install for transcription")
                return

        with tempfile.TemporaryDirectory(prefix="foulplay_") as tmp:
            workdir = Path(tmp)
            progress_dialog = TranscribeProgressDialog(
                video_path, self.settings.performance, workdir, self
            )
            progress_dialog.start()
            if progress_dialog.exec() != TranscribeProgressDialog.DialogCode.Accepted:
                if progress_dialog.error:
                    logger.error("Transcription failed: %s", progress_dialog.error)
                    QMessageBox.critical(self, "Transcription failed", progress_dialog.error + _ERROR_LOG_HINT)
                return

            transcript = progress_dialog.transcript
            assert transcript is not None

        self._review_and_process(video_path, transcript)

    def _open_project(self) -> None:
        logger.info("Open Project clicked")
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open a FoulPlay project", "", "FoulPlay projects (*.fpproj);;All files (*.*)"
        )
        if not path_str:
            logger.info("Open project cancelled: no file selected")
            return

        try:
            project = load_project(Path(path_str))
        except (OSError, ValueError) as exc:
            logger.error("Failed to load project: %s", exc)
            QMessageBox.critical(self, "Could not open project", str(exc) + _ERROR_LOG_HINT)
            return

        if not project.source_video.exists():
            QMessageBox.critical(
                self,
                "Video not found",
                f"The source video for this project could not be found:\n{project.source_video}",
            )
            return

        logger.info(
            "Loaded project: %s (%d sentences, %d words, %d prior edit decisions)",
            project.source_video,
            len(project.transcript.sentences),
            len(project.transcript.words),
            len(project.edits),
        )
        prior_by_index = {e.word_index: e for e in project.edits}
        self._review_and_process(project.source_video, project.transcript, prior_by_index)

    def _review_and_process(
        self,
        video_path: Path,
        transcript: Transcript,
        prior_decisions: dict[int, EditDecision] | None = None,
    ) -> None:
        matches = find_matches(transcript, self.settings.words)
        review_dialog = ReviewDialog(matches, prior_decisions, self)
        if review_dialog.exec() != ReviewDialog.DialogCode.Accepted:
            logger.info("Review cancelled")
            return

        decisions = review_dialog.collect_decisions()
        included_count = sum(1 for d in decisions if d.include)
        logger.info("Review confirmed: %d of %d flagged word(s) included", included_count, len(decisions))
        project_path = default_project_path(video_path)
        save_project(project_path, video_path, transcript, decisions)

        if not any(d.include for d in decisions):
            QMessageBox.information(self, "Nothing to process", "No edits were confirmed; nothing to process.")
            return

        needed = missing_groups(["separation"])
        if needed:
            logger.info("Missing dependency groups for processing: %s", [g.key for g in needed])
            dep_dialog = DependencyInstallDialog(needed, self)
            if not dep_dialog.exec() or not dep_dialog.succeeded:
                logger.info("User declined/cancelled dependency install for processing")
                return

        default_output = video_path.with_name(f"{video_path.stem} (Cleaned).mkv")
        output_str, _ = QFileDialog.getSaveFileName(
            self, "Save cleaned video as...", str(default_output), "Matroska video (*.mkv)"
        )
        if not output_str:
            logger.info("Processing cancelled: no output path chosen")
            return
        output_path = Path(output_str)
        logger.info("Output path: %s", output_path)

        with tempfile.TemporaryDirectory(prefix="foulplay_") as tmp:
            workdir = Path(tmp)
            process_dialog = ProcessProgressDialog(
                video_path, transcript, decisions, self.settings, workdir, output_path, self
            )
            process_dialog.start()
            if process_dialog.exec() != ProcessProgressDialog.DialogCode.Accepted:
                if process_dialog.error:
                    logger.error("Processing failed: %s", process_dialog.error)
                    QMessageBox.critical(self, "Processing failed", process_dialog.error + _ERROR_LOG_HINT)
                return

        report_path = output_path.with_name(f"{output_path.stem} - Changes.txt")
        logger.info("Processing complete: %s", output_path)
        QMessageBox.information(
            self,
            "Done",
            f"Cleaned video saved to:\n{output_path}\n\n"
            "It has a new 'English (Cleaned)' audio track and three subtitle tracks "
            "(unedited, substituted, and substitute-only) you can switch to in your player.\n\n"
            f"A change report was also saved to:\n{report_path}",
        )
