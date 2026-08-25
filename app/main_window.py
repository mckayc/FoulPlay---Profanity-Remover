"""Main application window: a single-window wizard (QStackedWidget) that
walks Home -> Transcribe -> Review -> Process -> Done, instead of opening a
new top-level dialog window for each step.
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import media
from core.dependencies import missing_groups
from core.hardware import Accelerator, get_hardware_report
from core.hybrid_transcribe import HybridStats
from core.logging_setup import get_log_file_path, read_recent_log_text
from core.profanity_matcher import find_matches
from core.sentence_edit import SentenceEdit, build_default_sentence_edits
from core.transcript import Transcript
from core.version import APP_VERSION
from projects.project_file import default_project_path, load_project, save_project
from settings.config import load_settings

from .dependency_dialog import DependencyInstallDialog
from .ffmpeg_install_dialog import FfmpegInstallDialog
from .process_dialog import ProcessPage
from .review_dialog import ReviewPage
from .settings_dialog import SettingsDialog
from .transcribe_dialog import TranscribePage

logger = logging.getLogger(__name__)

_ERROR_LOG_HINT = "\n\nIf this keeps happening, use the \"Copy Log\" button to grab diagnostic details."


def _resolve_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "."))
        return base / "data" / "icon.ico"
    return Path(__file__).resolve().parent.parent / "data" / "icon.ico"


class HomePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        title = QLabel(
            f"<h2>FoulPlay <span style='font-size:10pt; font-weight:normal; color:#5B6270;'>v{APP_VERSION}</span></h2>"
            "<p>Create a family-friendly audio &amp; subtitle track for your movies.</p>"
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        hardware_box = QGroupBox("Hardware")
        hardware_layout = QVBoxLayout(hardware_box)
        self.hardware_label = QLabel()
        self.hardware_label.setWordWrap(True)
        hardware_layout.addWidget(self.hardware_label)
        layout.addWidget(hardware_box)

        self.import_button = QPushButton("Import Video...")
        self.import_button.setProperty("accent", True)
        layout.addWidget(self.import_button)

        self.open_project_button = QPushButton("Open Project...")
        self.open_project_button.setToolTip(
            "Resume a previously transcribed video (.fpproj) without re-transcribing it."
        )
        layout.addWidget(self.open_project_button)

        self.settings_button = QPushButton("Settings...")
        layout.addWidget(self.settings_button)

        layout.addStretch(1)

        log_row = QHBoxLayout()
        self.log_label = QLabel(f"Log file: {get_log_file_path()}")
        self.log_label.setProperty("muted", True)
        self.log_label.setWordWrap(True)
        log_row.addWidget(self.log_label, 1)
        self.copy_log_button = QPushButton("Copy Log")
        self.copy_log_button.setToolTip("Copy the diagnostic log to your clipboard to share when something goes wrong.")
        log_row.addWidget(self.copy_log_button)
        layout.addLayout(log_row)

    def refresh_hardware_report(self) -> None:
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


class DonePage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch(1)

        title = QLabel("<h2>Done</h2>")
        layout.addWidget(title)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.start_over_button = QPushButton("Start Over")
        self.start_over_button.setProperty("accent", True)
        layout.addWidget(self.start_over_button)

        layout.addStretch(2)

    def show_result(self, output_path: Path, report_path: Path) -> None:
        self.message_label.setText(
            f"Cleaned video saved to:\n{output_path}\n\n"
            "It has a new 'English (Cleaned)' audio track and three subtitle tracks "
            "(unedited, substituted, and substitute-only) you can switch to in your player.\n\n"
            f"A change report was also saved to:\n{report_path}"
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"FoulPlay - Profanity Remover (v{APP_VERSION})")
        self.resize(780, 600)

        icon_path = _resolve_icon_path()
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.settings = load_settings()

        # State carried across the current Import/Open Project -> Review ->
        # Process flow. Cleared on returning Home.
        self._video_path: Path | None = None
        self._transcript: Transcript | None = None
        self._sentence_edits: dict[int, SentenceEdit] = {}
        self._transcribe_workdir: str | None = None
        self._process_workdir: str | None = None

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home_page = HomePage()
        self.transcribe_page = TranscribePage()
        self.review_page = ReviewPage()
        self.process_page = ProcessPage()
        self.done_page = DonePage()
        for page in (self.home_page, self.transcribe_page, self.review_page, self.process_page, self.done_page):
            self.stack.addWidget(page)

        self.home_page.import_button.clicked.connect(self._import_video)
        self.home_page.open_project_button.clicked.connect(self._open_project)
        self.home_page.settings_button.clicked.connect(self._open_settings)
        self.home_page.copy_log_button.clicked.connect(self._copy_log)

        self.transcribe_page.finished_ok.connect(self._on_transcribed)
        self.transcribe_page.failed.connect(self._on_transcribe_failed)
        self.transcribe_page.cancelled.connect(self._go_home)

        self.review_page.confirmed.connect(self._on_review_confirmed)
        self.review_page.cancelled.connect(self._go_home)

        self.process_page.finished_ok.connect(self._on_processed)
        self.process_page.failed.connect(self._on_process_failed)
        self.process_page.cancelled.connect(self._go_home)

        self.done_page.start_over_button.clicked.connect(self._go_home)

        self.home_page.refresh_hardware_report()
        self.stack.setCurrentWidget(self.home_page)

    def _bring_to_front(self) -> None:
        self.raise_()
        self.activateWindow()

    def _go_home(self) -> None:
        self._cleanup_workdirs()
        self._video_path = None
        self._transcript = None
        self._sentence_edits = {}
        self.home_page.refresh_hardware_report()
        self.stack.setCurrentWidget(self.home_page)

    def _cleanup_workdirs(self) -> None:
        for attr in ("_transcribe_workdir", "_process_workdir"):
            path = getattr(self, attr)
            if path:
                shutil.rmtree(path, ignore_errors=True)
                setattr(self, attr, None)

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

    # ----- Import Video -----

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

        self._video_path = video_path
        self._transcribe_workdir = tempfile.mkdtemp(prefix="foulplay_")
        subtitle_path = self._acquire_subtitle(video_path, Path(self._transcribe_workdir))
        self.stack.setCurrentWidget(self.transcribe_page)
        self.transcribe_page.start(
            video_path, subtitle_path, self.settings.performance, self.settings.words, Path(self._transcribe_workdir)
        )

    def _acquire_subtitle(self, video_path: Path, workdir: Path) -> Path | None:
        """Offers to use an available subtitle (embedded or sidecar) as a
        safety net for hybrid transcription, or lets the user browse for
        one. Purely additive -- declining or finding none falls back to
        today's single-pass transcription."""
        sidecar = media.find_sidecar_subtitle(video_path)
        if sidecar is not None:
            reply = QMessageBox.question(
                self,
                "Use subtitle file?",
                f"Found a matching subtitle file:\n{sidecar.name}\n\n"
                "Use it as a safety net to help catch profanity the fast transcription pass "
                "might miss (e.g. from quiet dialogue or background noise)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                logger.info("Using sidecar subtitle: %s", sidecar)
                return sidecar

        try:
            probe = media.probe(video_path)
        except Exception:  # noqa: BLE001
            probe = None

        if probe is not None and probe.subtitle_streams:
            reply = QMessageBox.question(
                self,
                "Use embedded subtitle?",
                "This video has an embedded subtitle track. Use it as a safety net to help catch "
                "profanity the fast transcription pass might miss?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                extracted = workdir / "embedded_subtitle.srt"
                try:
                    media.extract_subtitle(video_path, extracted)
                    logger.info("Using embedded subtitle extracted to: %s", extracted)
                    return extracted
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to extract embedded subtitle: %s", exc)
                    QMessageBox.warning(
                        self, "Subtitle extraction failed", f"Could not extract the embedded subtitle:\n{exc}"
                    )

        reply = QMessageBox.question(
            self,
            "Browse for a subtitle file?",
            "No subtitle was auto-detected. Browse for one to use as a safety net during "
            "transcription? (Optional -- transcription works fine without one.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            path_str, _ = QFileDialog.getOpenFileName(
                self, "Select a subtitle file", "", "Subtitle files (*.srt *.ass *.vtt);;All files (*.*)"
            )
            if path_str:
                logger.info("Using manually-selected subtitle: %s", path_str)
                return Path(path_str)

        return None

    def _on_transcribed(self, transcript: Transcript, stats: HybridStats) -> None:
        self._bring_to_front()
        self._transcript = transcript
        self._start_review(needs_verification_ids=stats.needs_verification_ids, summary_note=self._build_summary_note(stats))

    def _build_summary_note(self, stats: HybridStats) -> str | None:
        if not stats.subtitle_used:
            return None
        if not stats.synced:
            return "Subtitle safety net: could not reliably sync the subtitle to the video, so it wasn't used."
        parts = [f"checked {stats.candidates_checked} subtitle-flagged spot(s) the baseline pass missed"]
        if stats.confirmed_additional:
            parts.append(f"confirmed {stats.confirmed_additional} additional word(s)")
        if stats.needs_verification_ids:
            parts.append(f"{len(stats.needs_verification_ids)} still need manual verification (see warnings below)")
        return "Subtitle safety net: " + "; ".join(parts) + "."

    def _on_transcribe_failed(self, message: str) -> None:
        self._bring_to_front()
        logger.error("Transcription failed: %s", message)
        self._cleanup_workdirs()
        QMessageBox.critical(self, "Transcription failed", message + _ERROR_LOG_HINT)
        self._go_home()

    # ----- Open Project -----

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
            "Loaded project: %s (%d sentences, %d words, %d prior sentence edits)",
            project.source_video,
            len(project.transcript.sentences),
            len(project.transcript.words),
            len(project.sentence_edits),
        )
        self._video_path = project.source_video
        self._transcript = project.transcript
        self._start_review(project.sentence_edits)

    # ----- Review -----

    def _start_review(
        self,
        prior_edits: dict[int, SentenceEdit] | None = None,
        needs_verification_ids: set[int] | None = None,
        summary_note: str | None = None,
    ) -> None:
        assert self._transcript is not None
        matches = find_matches(self._transcript, self.settings.words)
        default_edits = build_default_sentence_edits(self._transcript, matches, needs_verification_ids)
        self.review_page.set_sentence_edits(self._transcript, default_edits, prior_edits, summary_note)
        self.stack.setCurrentWidget(self.review_page)

    def _on_review_confirmed(self, sentence_edits: dict[int, SentenceEdit]) -> None:
        assert self._video_path is not None
        assert self._transcript is not None

        changed_count = sum(
            1 for e in sentence_edits.values() if e.edit_enabled and (e.excluded_word_indices or e.custom_subtitle_text)
        )
        logger.info(
            "Review confirmed: %d of %d sentence(s) have an active edit", changed_count, len(sentence_edits)
        )
        self._sentence_edits = sentence_edits
        project_path = default_project_path(self._video_path)
        save_project(project_path, self._video_path, self._transcript, sentence_edits)

        if changed_count == 0:
            QMessageBox.information(self, "Nothing to process", "No edits were confirmed; nothing to process.")
            self._go_home()
            return

        needed = missing_groups(["separation"])
        if needed:
            logger.info("Missing dependency groups for processing: %s", [g.key for g in needed])
            dep_dialog = DependencyInstallDialog(needed, self)
            if not dep_dialog.exec() or not dep_dialog.succeeded:
                logger.info("User declined/cancelled dependency install for processing")
                self._go_home()
                return

        default_output = self._video_path.with_name(f"{self._video_path.stem} (Cleaned).mkv")
        output_str, _ = QFileDialog.getSaveFileName(
            self, "Save cleaned video as...", str(default_output), "Matroska video (*.mkv)"
        )
        if not output_str:
            logger.info("Processing cancelled: no output path chosen")
            self._go_home()
            return
        output_path = Path(output_str)
        logger.info("Output path: %s", output_path)

        self._process_workdir = tempfile.mkdtemp(prefix="foulplay_")
        self.stack.setCurrentWidget(self.process_page)
        self.process_page.start(
            self._video_path,
            self._transcript,
            sentence_edits,
            self.settings,
            Path(self._process_workdir),
            output_path,
        )

    # ----- Process -----

    def _on_processed(self, output_path: Path) -> None:
        self._bring_to_front()
        logger.info("Processing complete: %s", output_path)
        report_path = output_path.with_name(f"{output_path.stem} - Changes.txt")
        self._cleanup_workdirs()
        self.done_page.show_result(output_path, report_path)
        self.stack.setCurrentWidget(self.done_page)

    def _on_process_failed(self, message: str) -> None:
        self._bring_to_front()
        logger.error("Processing failed: %s", message)
        self._cleanup_workdirs()
        QMessageBox.critical(self, "Processing failed", message + _ERROR_LOG_HINT)
        self._go_home()
