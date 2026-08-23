"""Dialog that installs missing dependency groups on demand.

Shown the first time a feature needs a dependency group that isn't
installed yet (e.g. faster-whisper for transcription). Runs pip install in
a background thread and streams output so the user can see progress on
what can be a multi-hundred-megabyte download.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from core.dependencies import DependencyGroup, install_group


class _InstallWorker(QThread):
    output = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, groups: list[DependencyGroup]) -> None:
        super().__init__()
        self._groups = groups

    def run(self) -> None:
        try:
            for group in self._groups:
                self.output.emit(f"--- Installing: {group.label} ---")
                install_group(group, on_output=self.output.emit)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit()


class DependencyInstallDialog(QDialog):
    """Presents missing groups, installs them on confirmation."""

    def __init__(self, groups: list[DependencyGroup], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Install required components")
        self.resize(560, 420)
        self._groups = groups
        self._worker: _InstallWorker | None = None
        self.succeeded = False

        layout = QVBoxLayout(self)

        total_mb = sum(g.approx_size_mb for g in groups)
        intro = QLabel(
            "FoulPlay keeps its base install small and downloads AI components "
            "only when you actually use them. This step needs the following "
            f"(~{total_mb} MB total, one-time download):"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        for group in groups:
            item = QLabel(f"• <b>{group.label}</b> (~{group.approx_size_mb} MB) — {group.used_for}")
            item.setWordWrap(True)
            layout.addWidget(item)

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
        self.log.show()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(False)

        self._worker = _InstallWorker(self._groups)
        self._worker.output.connect(self.log.appendPlainText)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self) -> None:
        self.succeeded = True
        self.log.appendPlainText("\nDone.")
        self.accept()

    def _on_failure(self, message: str) -> None:
        self.log.appendPlainText(f"\nInstall failed: {message}")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Close")
