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
    """Renders one flowing line: muted previous-sentence context, the
    current sentence as individually clickable words (click to toggle a
    word between included/excluded), then muted next-sentence context.
    Combining context and the editable sentence into a single line (rather
    than three stacked rows plus a separate "Original:" line) keeps each
    card to roughly two rows in the common case, wrapping only as the
    window narrows or the text runs long.
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

    def render(
        self,
        transcript: Transcript,
        sentence_id: int,
        word_indices: list[int],
        words_text: dict[int, str],
        excluded: set[int],
        enabled: bool,
    ) -> None:
        parts = []

        previous_sentence = transcript.sentence_by_id(sentence_id - 1)
        if previous_sentence is not None:
            parts.append(f'<span style="color:{TEXT_MUTED};">… {html.escape(previous_sentence.text)}</span>')

        for index in word_indices:
            text = html.escape(words_text[index])
            if not enabled:
                parts.append(f'<span style="color:{TEXT_MUTED};">{text}</span>')
            elif index in excluded:
                parts.append(
                    f'<a href="{index}" style="color:#c0392b; text-decoration: line-through;">{text}</a>'
                )
            else:
                parts.append(f'<a href="{index}" style="color:{TEXT}; text-decoration: none;">{text}</a>')

        next_sentence = transcript.sentence_by_id(sentence_id + 1)
        if next_sentence is not None:
            parts.append(f'<span style="color:{TEXT_MUTED};">{html.escape(next_sentence.text)} …</span>')

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

        # Row 1: controls. Kept to one row -- a warning indicator (when
        # present) plus the Edit/Mirror checkboxes and reset button.
        header = QHBoxLayout()
        if self.edit.needs_verification:
            warning_label = QLabel("⚠ needs verification")
            warning_label.setProperty("warning", True)
            warning_label.setToolTip(
                "Subtitle suggests profanity here that couldn't be confirmed -- please check manually."
            )
            header.addWidget(warning_label)
        header.addStretch(1)
        self.reset_button = QToolButton()
        self.reset_button.setText("↺")
        self.reset_button.setToolTip("Reset this sentence to defaults")
        self.reset_button.clicked.connect(self._on_reset)
        header.addWidget(self.reset_button)
        self.edit_checkbox = QCheckBox("Edit")
        self.edit_checkbox.setToolTip("Uncheck to leave this sentence completely untouched in both audio and subtitles.")
        self.edit_checkbox.setChecked(self.edit.edit_enabled)
        self.edit_checkbox.toggled.connect(self._on_edit_toggled)
        header.addWidget(self.edit_checkbox)
        self.mirror_checkbox = QCheckBox("Mirror subtitles")
        self.mirror_checkbox.setToolTip(
            "When checked, subtitles automatically match the audio (same words removed, no replacement "
            "text). Uncheck to write custom subtitle text instead."
        )
        self.mirror_checkbox.setChecked(self.edit.mirror)
        self.mirror_checkbox.toggled.connect(self._on_mirror_toggled)
        header.addWidget(self.mirror_checkbox)
        layout.addLayout(header)

        # Row 2: previous context + clickable current-sentence words (click
        # to mute/unmute) + next context, all in one flowing line. No
        # separate "Original:" line -- crossed-out words already show what
        # was removed, so nothing is lost by not repeating the sentence.
        self.words_label = ClickableWordsLabel()
        self.words_label.word_toggled.connect(self._on_word_toggled)
        layout.addWidget(self.words_label)

        # Row 3 (conditional): only shown when Mirror is off, since that's
        # the only time subtitle text can differ from the audio words above.
        self.subtitle_row = QWidget()
        subtitle_row_layout = QHBoxLayout(self.subtitle_row)
        subtitle_row_layout.setContentsMargins(0, 0, 0, 0)
        subtitle_row_layout.addWidget(QLabel("Subtitles:"))
        self.subtitle_edit = QPlainTextEdit()
        self.subtitle_edit.setFixedHeight(44)
        self.subtitle_edit.textChanged.connect(self._on_subtitle_text_changed)
        subtitle_row_layout.addWidget(self.subtitle_edit, 1)
        layout.addWidget(self.subtitle_row)

        self._refresh()

    def _refresh(self) -> None:
        enabled = self.edit.edit_enabled
        excluded = self.edit.excluded_word_indices if enabled else set()
        self.words_label.render(
            self.transcript, self.sentence.id, self._word_indices, self._words_text, excluded, enabled
        )

        self.mirror_checkbox.setEnabled(enabled)

        show_subtitle_row = enabled and not self.edit.mirror
        self.subtitle_row.setVisible(show_subtitle_row)
        if show_subtitle_row:
            subtitle_text = subtitle_text_for_sentence(self.transcript, self.sentence, self.edit)
            self.subtitle_edit.blockSignals(True)
            if self.subtitle_edit.toPlainText() != subtitle_text:
                self.subtitle_edit.setPlainText(subtitle_text)
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
            f"Found flagged words in {len(default_edits)} sentence(s). Click a word below to mute/unmute "
            "it, uncheck Edit to leave a sentence untouched, or uncheck Mirror to write custom subtitles "
            "independent of the audio."
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
