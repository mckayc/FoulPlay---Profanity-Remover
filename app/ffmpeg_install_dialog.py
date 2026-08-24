"""Dialog offering to auto-install FFmpeg via winget when it's missing."""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from core.ffmpeg_installer import MANUAL_INSTALL_HINT, install_ffmpeg_via_winget, is_winget_available

logger = logging.getLogger(__name__)


class _FfmpegInstallWorker(QThread):
    output = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def run(self) -> None:
        try:
            install_ffmpeg_via_winget(on_output=self.output.emit)
        except Exception as exc:  # noqa: BLE001
            logger.exception("FFmpeg install worker failed")
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit()


class FfmpegInstallDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FFmpeg required")
        self.resize(520, 380)
        self.succeeded = False
        self._worker: _FfmpegInstallWorker | None = None

        layout = QVBoxLayout(self)

        if not is_winget_available():
            info = QLabel(MANUAL_INSTALL_HINT)
            info.setWordWrap(True)
            layout.addWidget(info)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            buttons.accepted.connect(self.reject)
            layout.addWidget(buttons)
            return

        info = QLabel(
            "FoulPlay needs FFmpeg, which wasn't found on your system. "
            "It can be installed automatically via winget (Windows' built-in package manager)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # marquee/busy mode -- winget gives no real percentage
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.hide()
        layout.addWidget(self.log)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Install")
        self.buttons.accepted.connect(self._start_install)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _start_install(self) -> None:
        self.progress_bar.show()
        self.log.show()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(False)

        self._worker = _FfmpegInstallWorker()
        self._worker.output.connect(self.log.appendPlainText)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self) -> None:
        self.succeeded = True
        self.progress_bar.hide()
        self.log.appendPlainText("\nDone. Please restart FoulPlay to finish setup.")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Close")

    def _on_failure(self, message: str) -> None:
        self.progress_bar.hide()
        self.log.appendPlainText(f"\nInstall failed: {message}")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Close")
