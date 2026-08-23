"""Main application window.

Milestone 1 scope: launch, show hardware detection results, and provide
access to Settings. The step wizard (Import -> Transcribe -> Review ->
Process -> Export) is filled in across later milestones as each pipeline
stage lands.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
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
from core.profanity_matcher import find_matches
from projects.project_file import default_project_path, save_project
from settings.config import load_settings

from .dependency_dialog import DependencyInstallDialog
from .ffmpeg_install_dialog import FfmpegInstallDialog
from .process_dialog import ProcessProgressDialog
from .review_dialog import ReviewDialog
from .settings_dialog import SettingsDialog
from .transcribe_dialog import TranscribeProgressDialog


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

        settings_button = QPushButton("Settings...")
        settings_button.clicked.connect(self._open_settings)
        layout.addWidget(settings_button)

        layout.addStretch(1)

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
            QMessageBox.information(self, "Settings saved", "Your settings have been saved.")

    def _import_video(self) -> None:
        if not media.is_ffmpeg_available():
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
            return
        video_path = Path(path_str)

        needed = missing_groups(["asr"])
        if needed:
            dep_dialog = DependencyInstallDialog(needed, self)
            if not dep_dialog.exec() or not dep_dialog.succeeded:
                return

        with tempfile.TemporaryDirectory(prefix="foulplay_") as tmp:
            workdir = Path(tmp)
            progress_dialog = TranscribeProgressDialog(
                video_path, self.settings.performance, workdir, self
            )
            progress_dialog.start()
            if progress_dialog.exec() != TranscribeProgressDialog.DialogCode.Accepted:
                if progress_dialog.error:
                    QMessageBox.critical(self, "Transcription failed", progress_dialog.error)
                return

            transcript = progress_dialog.transcript
            assert transcript is not None

        matches = find_matches(transcript, self.settings.words)
        review_dialog = ReviewDialog(matches, self)
        if review_dialog.exec() != ReviewDialog.DialogCode.Accepted:
            return

        decisions = review_dialog.collect_decisions()
        project_path = default_project_path(video_path)
        save_project(project_path, video_path, transcript, decisions)

        if not any(d.include for d in decisions):
            QMessageBox.information(self, "Nothing to process", "No edits were confirmed; nothing to process.")
            return

        needed = missing_groups(["separation"])
        if needed:
            dep_dialog = DependencyInstallDialog(needed, self)
            if not dep_dialog.exec() or not dep_dialog.succeeded:
                return

        default_output = video_path.with_name(f"{video_path.stem} (Cleaned).mkv")
        output_str, _ = QFileDialog.getSaveFileName(
            self, "Save cleaned video as...", str(default_output), "Matroska video (*.mkv)"
        )
        if not output_str:
            return
        output_path = Path(output_str)

        with tempfile.TemporaryDirectory(prefix="foulplay_") as tmp:
            workdir = Path(tmp)
            process_dialog = ProcessProgressDialog(
                video_path, transcript, decisions, self.settings, workdir, output_path, self
            )
            process_dialog.start()
            if process_dialog.exec() != ProcessProgressDialog.DialogCode.Accepted:
                if process_dialog.error:
                    QMessageBox.critical(self, "Processing failed", process_dialog.error)
                return

        QMessageBox.information(
            self,
            "Done",
            f"Cleaned video saved to:\n{output_path}\n\n"
            "It has a new 'English (Cleaned)' audio track and subtitle track "
            "you can switch to in your player.",
        )
