"""Review & Confirm page.

Shows every flagged word in full sentence context so the user can judge
how the word is being used, then include/exclude the edit and customize
the replacement before committing to processing.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.profanity_matcher import Match, find_highlight_span
from projects.project_file import EditDecision


def _render_sentence_html(match: Match) -> str:
    text = match.sentence.text
    span = find_highlight_span(text, match.matched_term, match.occurrence_in_sentence)
    if span is None:
        return html.escape(text)
    start, end = span
    before = html.escape(text[:start])
    target = html.escape(text[start:end])
    after = html.escape(text[end:])
    return f'{before}<b style="color:#c0392b;">{target}</b>{after}'


class _MatchRow(QFrame):
    def __init__(self, match: Match, prior: EditDecision | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.match = match
        self.setProperty("matchRow", True)

        initial_include = prior.include if prior is not None else match.include
        initial_replacement = prior.replacement if prior is not None else match.replacement

        layout = QHBoxLayout(self)

        self.include_checkbox = QCheckBox()
        self.include_checkbox.setChecked(initial_include)
        self.include_checkbox.setToolTip("Include this edit")
        layout.addWidget(self.include_checkbox)

        sentence_label = QLabel(_render_sentence_html(match))
        sentence_label.setTextFormat(Qt.TextFormat.RichText)
        sentence_label.setWordWrap(True)
        layout.addWidget(sentence_label, 1)

        arrow_label = QLabel("→")
        layout.addWidget(arrow_label)

        self.replacement_edit = QLineEdit(initial_replacement)
        self.replacement_edit.setFixedWidth(140)
        layout.addWidget(self.replacement_edit)

        self.include_checkbox.toggled.connect(self._update_enabled_state)
        self._update_enabled_state(initial_include)

    def _update_enabled_state(self, checked: bool) -> None:
        self.replacement_edit.setEnabled(checked)

    def to_decision(self) -> EditDecision:
        return EditDecision(
            word_index=self.match.word_index,
            include=self.include_checkbox.isChecked(),
            replacement=self.replacement_edit.text().strip() or self.match.proposed_replacement,
        )


class ReviewPage(QWidget):
    confirmed = Signal(list)  # list[EditDecision]
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_MatchRow] = []

        layout = QVBoxLayout(self)

        title = QLabel("<h2>Review flagged words</h2>")
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

    def set_matches(
        self,
        matches: list[Match],
        prior_decisions: dict[int, EditDecision] | None = None,
    ) -> None:
        prior_decisions = prior_decisions or {}

        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._rows = []
        if not matches:
            self.info_label.setText("No words from your filter list were found in this video.")
            return

        self.info_label.setText(
            f"Found {len(matches)} word(s) matching your filter list. "
            "Uncheck any you want to keep, or edit the replacement."
        )
        for match in matches:
            row = _MatchRow(match, prior=prior_decisions.get(match.word_index))
            self._rows.append(row)
            self._content_layout.addWidget(row)

    def _on_confirm(self) -> None:
        self.confirmed.emit([row.to_decision() for row in self._rows])
