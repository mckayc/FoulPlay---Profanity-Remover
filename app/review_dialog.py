"""Review & Confirm page.

One card per flagged sentence, with independently editable Audio and
Subtitle representations. Audio can only ever be muted -- never made to
say a replacement word -- so the two need to be able to diverge, e.g.
dropping "the hell" entirely from audio for a clean-sounding gap while
subtitles still read "the heck".
"""

from __future__ import annotations

import copy
import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.sentence_edit import SentenceEdit, subtitle_text_for_sentence
from core.transcript import Transcript

from .style import TEXT, TEXT_MUTED


class ClickableWordsLabel(QLabel):
    """Renders a sentence as individually clickable words; clicking a word
    toggles it between included (normal) and excluded (struck-through).
    """

    word_toggled = Signal(int)  # word_index

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(True)
        self.setOpenExternalLinks(False)
        self.linkActivated.connect(self._on_link_activated)

    def _on_link_activated(self, href: str) -> None:
        self.word_toggled.emit(int(href))

    def render_words(
        self,
        word_indices: list[int],
        words_text: dict[int, str],
        excluded: set[int],
        enabled: bool,
    ) -> None:
        parts = []
        for index in word_indices:
            text = html.escape(words_text[index])
            if not enabled:
                parts.append(f'<span style="color:#9aa0aa;">{text}</span>')
            elif index in excluded:
                parts.append(
                    f'<a href="{index}" style="color:#c0392b; text-decoration: line-through;">{text}</a>'
                )
            else:
                parts.append(f'<a href="{index}" style="color:#1e2126; text-decoration: none;">{text}</a>')
        self.setText(" ".join(parts))


class SentenceCard(QFrame):
    def __init__(
        self,
        transcript: Transcript,
        sentence_id: int,
        default_edit: SentenceEdit,
        initial_edit: SentenceEdit,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("matchRow", True)
        self.transcript = transcript
        self.sentence = transcript.sentence_by_id(sentence_id)
        self._default_edit = default_edit
        self.edit = initial_edit
        self._word_indices = [i for i, w in enumerate(transcript.words) if w.sentence_id == sentence_id]
        self._words_text = {i: transcript.words[i].text for i in self._word_indices}

        layout = QVBoxLayout(self)

        if self.edit.needs_verification:
            warning_label = QLabel(
                "⚠ Subtitle suggests profanity here that couldn't be confirmed -- please check manually."
            )
            warning_label.setProperty("warning", True)
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)

        header = QHBoxLayout()
        context_label = QLabel(self._build_context_html(transcript, sentence_id))
        context_label.setTextFormat(Qt.TextFormat.RichText)
        context_label.setWordWrap(True)
        header.addWidget(context_label, 1)
        self.edit_checkbox = QCheckBox("Edit")
        self.edit_checkbox.setChecked(self.edit.edit_enabled)
        self.edit_checkbox.toggled.connect(self._on_edit_toggled)
        header.addWidget(self.edit_checkbox)
        layout.addLayout(header)

        columns = QHBoxLayout()

        audio_col = QVBoxLayout()
        audio_header = QHBoxLayout()
        audio_header.addWidget(QLabel("<b>Audio</b>"))
        self.reset_button = QToolButton()
        self.reset_button.setText("↺")
        self.reset_button.setToolTip("Reset this sentence to defaults")
        self.reset_button.clicked.connect(self._on_reset)
        audio_header.addWidget(self.reset_button)
        audio_header.addStretch(1)
        audio_col.addLayout(audio_header)
        self.audio_label = ClickableWordsLabel()
        self.audio_label.word_toggled.connect(self._on_word_toggled)
        audio_col.addWidget(self.audio_label)
        columns.addLayout(audio_col, 1)

        subtitle_col = QVBoxLayout()
        subtitle_header = QHBoxLayout()
        subtitle_header.addWidget(QLabel("<b>Subtitles</b>"))
        subtitle_header.addStretch(1)
        self.mirror_checkbox = QCheckBox("Mirror the subtitles with the audio")
        self.mirror_checkbox.setChecked(self.edit.mirror)
        self.mirror_checkbox.toggled.connect(self._on_mirror_toggled)
        subtitle_header.addWidget(self.mirror_checkbox)
        subtitle_col.addLayout(subtitle_header)
        self.subtitle_edit = QPlainTextEdit()
        self.subtitle_edit.setFixedHeight(60)
        self.subtitle_edit.textChanged.connect(self._on_subtitle_text_changed)
        subtitle_col.addWidget(self.subtitle_edit)
        columns.addLayout(subtitle_col, 1)

        layout.addLayout(columns)

        self._refresh()

    @staticmethod
    def _build_context_html(transcript: Transcript, sentence_id: int) -> str:
        """A single flowing paragraph -- muted-colored previous/next
        sentences around the current one in its normal (non-bold) text
        color -- instead of separate stacked lines with an "Original:"
        label, which wasted vertical space for little benefit. All three
        pieces are wrapped in real <span> tags (not just escaped text) so
        Qt's rich-text auto-detection actually kicks in and decodes the
        escaped entities -- a plain escaped string with no markup around
        it gets shown as literal text (e.g. "don&#x27;t") instead of being
        interpreted, which was a real bug in the old previous/next labels.
        """
        sentence = transcript.sentence_by_id(sentence_id)
        previous_sentence = transcript.sentence_by_id(sentence_id - 1)
        next_sentence = transcript.sentence_by_id(sentence_id + 1)

        parts = []
        if previous_sentence is not None:
            parts.append(f'<span style="color:{TEXT_MUTED};">… {html.escape(previous_sentence.text)}</span>')
        parts.append(f'<span style="color:{TEXT}; font-weight:600;">{html.escape(sentence.text)}</span>')
        if next_sentence is not None:
            parts.append(f'<span style="color:{TEXT_MUTED};">{html.escape(next_sentence.text)} …</span>')
        return " ".join(parts)

    def _refresh(self) -> None:
        enabled = self.edit.edit_enabled
        excluded = self.edit.excluded_word_indices if enabled else set()
        self.audio_label.render_words(self._word_indices, self._words_text, excluded, enabled)

        self.mirror_checkbox.setEnabled(enabled)

        subtitle_text = subtitle_text_for_sentence(self.transcript, self.sentence, self.edit)
        self.subtitle_edit.blockSignals(True)
        if self.subtitle_edit.toPlainText() != subtitle_text:
            self.subtitle_edit.setPlainText(subtitle_text)
        self.subtitle_edit.setReadOnly(not enabled or self.edit.mirror)
        self.subtitle_edit.blockSignals(False)

    def _on_word_toggled(self, word_index: int) -> None:
        if not self.edit.edit_enabled:
            return
        if word_index in self.edit.excluded_word_indices:
            self.edit.excluded_word_indices.discard(word_index)
        else:
            self.edit.excluded_word_indices.add(word_index)
        self._refresh()

    def _on_edit_toggled(self, checked: bool) -> None:
        self.edit.edit_enabled = checked
        self._refresh()

    def _on_mirror_toggled(self, checked: bool) -> None:
        self.edit.mirror = checked
        self.edit.custom_subtitle_text = None
        self._refresh()

    def _on_subtitle_text_changed(self) -> None:
        if self.edit.mirror or not self.edit.edit_enabled:
            return
        self.edit.custom_subtitle_text = self.subtitle_edit.toPlainText()

    def _on_reset(self) -> None:
        self.edit = copy.deepcopy(self._default_edit)
        self.edit_checkbox.blockSignals(True)
        self.edit_checkbox.setChecked(True)
        self.edit_checkbox.blockSignals(False)
        self.mirror_checkbox.blockSignals(True)
        self.mirror_checkbox.setChecked(True)
        self.mirror_checkbox.blockSignals(False)
        self._refresh()


class ReviewPage(QWidget):
    confirmed = Signal(object)  # dict[int, SentenceEdit]
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[SentenceCard] = []

        layout = QVBoxLayout(self)

        title = QLabel("<h2>Review flagged sentences</h2>")
        layout.addWidget(title)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self._content)
        layout.addWidget(self.scroll, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.cancelled.emit)
        button_row.addWidget(cancel_button)
        confirm_button = QPushButton("Confirm")
        confirm_button.setProperty("accent", True)
        confirm_button.clicked.connect(self._on_confirm)
        button_row.addWidget(confirm_button)
        layout.addLayout(button_row)

    def set_sentence_edits(
        self,
        transcript: Transcript,
        default_edits: dict[int, SentenceEdit],
        prior_edits: dict[int, SentenceEdit] | None = None,
        summary_note: str | None = None,
    ) -> None:
        prior_edits = prior_edits or {}

        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._cards = []
        if not default_edits:
            text = "No words from your filter list were found in this video."
            if summary_note:
                text += "\n" + summary_note
            self.info_label.setText(text)
            return

        text = (
            f"Found flagged words in {len(default_edits)} sentence(s). Click a word in the Audio "
            "column to mute/unmute it, uncheck Edit to leave a sentence untouched, or uncheck "
            "Mirror to write custom subtitles independent of the audio."
        )
        if summary_note:
            text += "\n" + summary_note
        self.info_label.setText(text)
        for sentence_id in sorted(default_edits):
            default_edit = default_edits[sentence_id]
            initial_edit = copy.deepcopy(prior_edits.get(sentence_id, default_edit))
            card = SentenceCard(transcript, sentence_id, default_edit, initial_edit)
            self._cards.append(card)
            self._content_layout.addWidget(card)

    def _on_confirm(self) -> None:
        self.confirmed.emit({card.sentence.id: card.edit for card in self._cards})
