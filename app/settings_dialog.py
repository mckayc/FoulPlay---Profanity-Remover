"""Settings dialog: word list management, audio edit mode, subtitle behavior."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from settings.config import (
    WHISPER_MODEL_SIZES,
    AppSettings,
    AudioEditMode,
    SubtitleTextMode,
    WordEntry,
    save_settings,
)

WORD_COL, REPLACEMENTS_COL, ENABLED_COL = 0, 1, 2


class WordListTab(QWidget):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings

        layout = QVBoxLayout(self)

        info = QLabel(
            "Words to filter. Separate multiple replacement options with a comma -- "
            "one will be chosen at random each time the word is replaced."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Word", "Replacement(s)", "Enabled"])
        self.table.horizontalHeader().setSectionResizeMode(WORD_COL, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(REPLACEMENTS_COL, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(ENABLED_COL, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        self._populate()

        button_row = QHBoxLayout()
        add_button = QPushButton("Add word")
        add_button.clicked.connect(self._add_row)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self._remove_selected)
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

    def _populate(self) -> None:
        self.table.setRowCount(0)
        for entry in self._settings.words:
            self._append_row(entry.word, ", ".join(entry.replacements), entry.enabled)

    def _append_row(self, word: str, replacements: str, enabled: bool) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, WORD_COL, QTableWidgetItem(word))
        self.table.setItem(row, REPLACEMENTS_COL, QTableWidgetItem(replacements))
        enabled_item = QTableWidgetItem()
        enabled_item.setFlags(enabled_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        enabled_item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        self.table.setItem(row, ENABLED_COL, enabled_item)

    def _add_row(self) -> None:
        self._append_row("", "", True)
        self.table.setCurrentCell(self.table.rowCount() - 1, WORD_COL)

    def _remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def collect(self) -> list[WordEntry]:
        entries: list[WordEntry] = []
        for row in range(self.table.rowCount()):
            word = self.table.item(row, WORD_COL).text().strip()
            if not word:
                continue
            replacements_text = self.table.item(row, REPLACEMENTS_COL).text().strip()
            replacements = [r.strip() for r in replacements_text.split(",") if r.strip()]
            enabled = self.table.item(row, ENABLED_COL).checkState() == Qt.CheckState.Checked
            entries.append(WordEntry(word=word, replacements=replacements, enabled=enabled))
        return entries


class AudioEditTab(QWidget):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings

        layout = QFormLayout(self)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Silence", AudioEditMode.SILENCE)
        self.mode_combo.addItem("Volume reduction", AudioEditMode.VOLUME)
        self.mode_combo.addItem("Beep", AudioEditMode.BEEP)
        index = self.mode_combo.findData(settings.audio_edit.mode)
        self.mode_combo.setCurrentIndex(max(index, 0))
        layout.addRow("When a word is removed:", self.mode_combo)

        self.volume_spin = QDoubleSpinBox()
        self.volume_spin.setRange(-60.0, 0.0)
        self.volume_spin.setSuffix(" dB")
        self.volume_spin.setValue(settings.audio_edit.volume_db)
        layout.addRow("Volume reduction level:", self.volume_spin)

        self.beep_spin = QDoubleSpinBox()
        self.beep_spin.setRange(200.0, 4000.0)
        self.beep_spin.setSuffix(" Hz")
        self.beep_spin.setValue(settings.audio_edit.beep_frequency_hz)
        layout.addRow("Beep frequency:", self.beep_spin)

        self.pad_before_spin = QDoubleSpinBox()
        self.pad_before_spin.setRange(0.0, 1000.0)
        self.pad_before_spin.setSuffix(" ms")
        self.pad_before_spin.setValue(settings.audio_edit.pad_before_ms)
        layout.addRow("Extra spacing before word:", self.pad_before_spin)

        self.pad_after_spin = QDoubleSpinBox()
        self.pad_after_spin.setRange(0.0, 1000.0)
        self.pad_after_spin.setSuffix(" ms")
        self.pad_after_spin.setValue(settings.audio_edit.pad_after_ms)
        layout.addRow("Extra spacing after word:", self.pad_after_spin)

        self.fade_spin = QDoubleSpinBox()
        self.fade_spin.setRange(0.0, 100.0)
        self.fade_spin.setSuffix(" ms")
        self.fade_spin.setValue(settings.audio_edit.fade_ms)
        layout.addRow("Fade at edit boundaries:", self.fade_spin)

    def collect(self):
        from settings.config import AudioEditSettings

        return AudioEditSettings(
            mode=self.mode_combo.currentData(),
            volume_db=self.volume_spin.value(),
            beep_frequency_hz=self.beep_spin.value(),
            pad_before_ms=self.pad_before_spin.value(),
            pad_after_ms=self.pad_after_spin.value(),
            fade_ms=self.fade_spin.value(),
        )


class SubtitleTab(QWidget):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Every cleaned video gets three subtitle tracks: the full unedited transcript, "
            "a version with profanity replaced throughout, and a substitute-only track that "
            "stays hidden except during edited lines."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        forced_group = QGroupBox("Substitute-only track content")
        forced_layout = QFormLayout(forced_group)
        self.forced_text_combo = QComboBox()
        self.forced_text_combo.addItem("Replacement word only", SubtitleTextMode.WORD_ONLY)
        self.forced_text_combo.addItem("Full sentence", SubtitleTextMode.FULL_SENTENCE)
        index = self.forced_text_combo.findData(settings.subtitles.forced_text_mode)
        self.forced_text_combo.setCurrentIndex(max(index, 0))
        forced_layout.addRow("Show:", self.forced_text_combo)
        layout.addWidget(forced_group)
        layout.addStretch(1)

    def collect(self):
        from settings.config import SubtitleSettings

        return SubtitleSettings(
            forced_text_mode=self.forced_text_combo.currentData(),
        )


class TranscriptionTab(QWidget):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QFormLayout(self)

        self.model_combo = QComboBox()
        self.model_combo.addItems(WHISPER_MODEL_SIZES)
        if settings.performance.whisper_model_size in WHISPER_MODEL_SIZES:
            self.model_combo.setCurrentText(settings.performance.whisper_model_size)
        model_note = QLabel(
            "Larger models are more accurate but slower, especially on CPU. "
            "'medium' is a reasonable default; try 'large-v3' if you're missing words."
        )
        model_note.setWordWrap(True)
        layout.addRow("Whisper model:", self.model_combo)
        layout.addRow("", model_note)

        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("Auto-detect", "")
        index = self.language_combo.findData(settings.performance.whisper_language)
        self.language_combo.setCurrentIndex(max(index, 0))
        layout.addRow("Language:", self.language_combo)

        self.vad_checkbox = QCheckBox("Skip music/effects-only stretches (reduces hallucinated text)")
        self.vad_checkbox.setChecked(settings.performance.whisper_vad_filter)
        layout.addRow("", self.vad_checkbox)

        self.beam_size_spin = QSpinBox()
        self.beam_size_spin.setRange(1, 10)
        self.beam_size_spin.setValue(settings.performance.whisper_beam_size)
        beam_note = QLabel("Higher = more thorough search for the best transcription, but slower.")
        beam_note.setWordWrap(True)
        layout.addRow("Beam size:", self.beam_size_spin)
        layout.addRow("", beam_note)

        self.prefer_gpu_checkbox = QCheckBox("Use GPU acceleration when available")
        self.prefer_gpu_checkbox.setChecked(settings.performance.prefer_gpu)
        layout.addRow("", self.prefer_gpu_checkbox)

    def collect(self):
        from settings.config import PerformanceSettings

        return PerformanceSettings(
            whisper_model_size=self.model_combo.currentText(),
            whisper_language=self.language_combo.currentData(),
            whisper_vad_filter=self.vad_checkbox.isChecked(),
            whisper_beam_size=self.beam_size_spin.value(),
            prefer_gpu=self.prefer_gpu_checkbox.isChecked(),
        )


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FoulPlay Settings")
        self.resize(640, 480)
        self._settings = settings

        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        self.word_tab = WordListTab(settings)
        self.audio_tab = AudioEditTab(settings)
        self.subtitle_tab = SubtitleTab(settings)
        self.transcription_tab = TranscriptionTab(settings)
        tabs.addTab(self.word_tab, "Word List")
        tabs.addTab(self.audio_tab, "Audio Edit")
        tabs.addTab(self.subtitle_tab, "Subtitles")
        tabs.addTab(self.transcription_tab, "Transcription")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        self._settings.words = self.word_tab.collect()
        self._settings.audio_edit = self.audio_tab.collect()
        self._settings.subtitles = self.subtitle_tab.collect()
        self._settings.performance = self.transcription_tab.collect()
        try:
            save_settings(self._settings)
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", f"Could not save settings:\n{exc}")
            return
        self.accept()
