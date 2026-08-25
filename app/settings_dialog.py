"""Settings dialog: word list management, audio edit mode, subtitle behavior."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from settings.config import (
    WHISPER_MODEL_SIZES,
    WORD_CATEGORIES,
    WORD_CATEGORY_LABELS,
    AppSettings,
    AudioEditMode,
    SubtitleTextMode,
    WordEntry,
    save_settings,
)


class _WordRow(QWidget):
    removed = Signal(object)  # emits self

    def __init__(self, entry: WordEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self.enabled_checkbox = QCheckBox()
        self.enabled_checkbox.setChecked(entry.enabled)
        self.enabled_checkbox.setToolTip("Include this word")
        layout.addWidget(self.enabled_checkbox)

        self.word_edit = QLineEdit(entry.word)
        self.word_edit.setPlaceholderText("word or phrase")
        layout.addWidget(self.word_edit, 1)

        self.replacements_edit = QLineEdit(", ".join(entry.replacements))
        self.replacements_edit.setPlaceholderText("replacement(s), comma-separated")
        layout.addWidget(self.replacements_edit, 1)

        remove_button = QPushButton("✕")
        remove_button.setFixedWidth(28)
        remove_button.setToolTip("Remove this word")
        remove_button.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(remove_button)

    def to_entry(self, category: str) -> WordEntry | None:
        word = self.word_edit.text().strip()
        if not word:
            return None
        replacements = [r.strip() for r in self.replacements_edit.text().split(",") if r.strip()]
        return WordEntry(
            word=word,
            replacements=replacements,
            enabled=self.enabled_checkbox.isChecked(),
            category=category,
        )


class _CategorySection(QGroupBox):
    def __init__(self, category: str, entries: list[WordEntry], parent: QWidget | None = None) -> None:
        label = WORD_CATEGORY_LABELS.get(category, category.title())
        super().__init__(label, parent)
        self.category = category
        self._rows: list[_WordRow] = []

        layout = QVBoxLayout(self)

        self.toggle_all_checkbox = QCheckBox(f'Enable all "{label}" words')
        self.toggle_all_checkbox.setChecked(all(e.enabled for e in entries) if entries else True)
        self.toggle_all_checkbox.toggled.connect(self._apply_toggle_all)
        layout.addWidget(self.toggle_all_checkbox)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._rows_container)

        for entry in entries:
            self._add_row(entry)

    def _add_row(self, entry: WordEntry) -> None:
        row = _WordRow(entry)
        row.removed.connect(self._remove_row)
        self._rows.append(row)
        self._rows_layout.addWidget(row)

    def add_new_word(self, word: str, replacements: list[str]) -> None:
        self._add_row(WordEntry(word=word, replacements=replacements, enabled=True, category=self.category))

    def _remove_row(self, row: _WordRow) -> None:
        self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def _apply_toggle_all(self, checked: bool) -> None:
        for row in self._rows:
            row.enabled_checkbox.setChecked(checked)

    def collect(self) -> list[WordEntry]:
        entries = []
        for row in self._rows:
            entry = row.to_entry(self.category)
            if entry is not None:
                entries.append(entry)
        return entries


class WordListTab(QWidget):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Words or phrases to filter, grouped by severity -- e.g. \"fuck\" or \"oh my god\". "
            "Uncheck a category's header to disable all its words at once, or toggle/edit "
            "individual entries below. Separate multiple replacement options with a comma -- "
            "one is chosen at random each time."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        add_row = QHBoxLayout()
        self.new_word_edit = QLineEdit()
        self.new_word_edit.setPlaceholderText("New word or phrase")
        add_row.addWidget(self.new_word_edit, 1)
        self.new_replacements_edit = QLineEdit()
        self.new_replacements_edit.setPlaceholderText("Replacement(s), comma-separated")
        add_row.addWidget(self.new_replacements_edit, 1)
        self.new_category_combo = QComboBox()
        for category in WORD_CATEGORIES:
            self.new_category_combo.addItem(WORD_CATEGORY_LABELS[category], category)
        self.new_category_combo.setCurrentIndex(WORD_CATEGORIES.index("custom"))
        add_row.addWidget(self.new_category_combo)
        add_button = QPushButton("Add word")
        add_button.clicked.connect(self._add_word)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        sections_layout = QVBoxLayout(content)
        sections_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        grouped: dict[str, list[WordEntry]] = {category: [] for category in WORD_CATEGORIES}
        for entry in settings.words:
            grouped.setdefault(entry.category, [])
            grouped[entry.category].append(entry)

        self._sections: dict[str, _CategorySection] = {}
        ordered_categories = list(WORD_CATEGORIES) + [c for c in grouped if c not in WORD_CATEGORIES]
        for category in ordered_categories:
            section = _CategorySection(category, grouped.get(category, []))
            self._sections[category] = section
            sections_layout.addWidget(section)

    def _add_word(self) -> None:
        word = self.new_word_edit.text().strip()
        if not word:
            return
        replacements = [r.strip() for r in self.new_replacements_edit.text().split(",") if r.strip()]
        category = self.new_category_combo.currentData()
        self._sections[category].add_new_word(word, replacements)
        self.new_word_edit.clear()
        self.new_replacements_edit.clear()

    def collect(self) -> list[WordEntry]:
        entries: list[WordEntry] = []
        for section in self._sections.values():
            entries.extend(section.collect())
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

        self.prioritize_speed_checkbox = QCheckBox("Prioritize speed over accuracy for the full-video pass")
        self.prioritize_speed_checkbox.setChecked(settings.performance.prioritize_speed)
        prioritize_speed_note = QLabel(
            "Off by default: the model above runs across the whole video for the best transcript "
            "and subtitle quality. Turning this on uses the faster model below for the full-video "
            "pass instead -- noticeably faster, but the transcript/subtitle text throughout the "
            "video will be less accurate. Either way, if you supply a subtitle file, it's used as "
            "an independent safety net to catch words the full-video pass might have missed -- "
            "that never depends on this setting."
        )
        prioritize_speed_note.setWordWrap(True)
        layout.addRow("", self.prioritize_speed_checkbox)
        layout.addRow("", prioritize_speed_note)

        self.fast_model_combo = QComboBox()
        self.fast_model_combo.addItems(WHISPER_MODEL_SIZES)
        if settings.performance.whisper_fast_model_size in WHISPER_MODEL_SIZES:
            self.fast_model_combo.setCurrentText(settings.performance.whisper_fast_model_size)
        fast_model_note = QLabel("Only used for the full-video pass when \"Prioritize speed\" above is checked.")
        fast_model_note.setWordWrap(True)
        layout.addRow("Fast model:", self.fast_model_combo)
        layout.addRow("", fast_model_note)

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
            whisper_fast_model_size=self.fast_model_combo.currentText(),
            prioritize_speed=self.prioritize_speed_checkbox.isChecked(),
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

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self._build_tabs(settings)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.RestoreDefaults
            | QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._reset_to_defaults)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_tabs(self, settings: AppSettings) -> None:
        self.word_tab = WordListTab(settings)
        self.audio_tab = AudioEditTab(settings)
        self.subtitle_tab = SubtitleTab(settings)
        self.transcription_tab = TranscriptionTab(settings)
        self.tabs.addTab(self.word_tab, "Word List")
        self.tabs.addTab(self.audio_tab, "Audio Edit")
        self.tabs.addTab(self.subtitle_tab, "Subtitles")
        self.tabs.addTab(self.transcription_tab, "Transcription")

    def _reset_to_defaults(self) -> None:
        reply = QMessageBox.question(
            self,
            "Restore defaults",
            "This discards your word list and all other customizations here, replacing them "
            "with FoulPlay's defaults. Nothing is saved until you click Save, so you can still "
            "Cancel out of this if you change your mind.\n\nRestore defaults now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from settings.config import get_default_settings

        defaults = get_default_settings()
        current_index = self.tabs.currentIndex()
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            widget.deleteLater()
        self._build_tabs(defaults)
        self.tabs.setCurrentIndex(current_index)

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
