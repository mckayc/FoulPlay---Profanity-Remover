"""Review & Confirm screen.

Shows every flagged word in full sentence context so the user can judge
how the word is being used, then include/exclude the edit and customize
the replacement before committing to processing.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    def __init__(self, match: Match, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.match = match
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(self)

        self.include_checkbox = QCheckBox()
        self.include_checkbox.setChecked(match.include)
        self.include_checkbox.setToolTip("Include this edit")
        layout.addWidget(self.include_checkbox)

        sentence_label = QLabel(_render_sentence_html(match))
        sentence_label.setTextFormat(Qt.TextFormat.RichText)
        sentence_label.setWordWrap(True)
        layout.addWidget(sentence_label, 1)

        arrow_label = QLabel("→")
        layout.addWidget(arrow_label)

        self.replacement_edit = QLineEdit(match.replacement)
        self.replacement_edit.setFixedWidth(140)
        layout.addWidget(self.replacement_edit)

        self.include_checkbox.toggled.connect(self._update_enabled_state)
        self._update_enabled_state(match.include)

    def _update_enabled_state(self, checked: bool) -> None:
        self.replacement_edit.setEnabled(checked)

    def to_decision(self) -> EditDecision:
        return EditDecision(
            word_index=self.match.word_index,
            include=self.include_checkbox.isChecked(),
            replacement=self.replacement_edit.text().strip() or self.match.proposed_replacement,
        )


class ReviewDialog(QDialog):
    def __init__(self, matches: list[Match], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review flagged words")
        self.resize(760, 560)

        layout = QVBoxLayout(self)

        if not matches:
            layout.addWidget(QLabel("No words from your filter list were found in this video."))
        else:
            info = QLabel(
                f"Found {len(matches)} word(s) matching your filter list. "
                "Uncheck any you want to keep, or edit the replacement."
            )
            info.setWordWrap(True)
            layout.addWidget(info)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            self._rows: list[_MatchRow] = []
            for match in matches:
                row = _MatchRow(match)
                self._rows.append(row)
                content_layout.addWidget(row)

            scroll.setWidget(content)
            layout.addWidget(scroll, 1)

        if not matches:
            self._rows = []

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Confirm")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def collect_decisions(self) -> list[EditDecision]:
        return [row.to_decision() for row in self._rows]
