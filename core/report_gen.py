"""Generates a plain-text report of every applied edit, saved alongside the
output video, so a user can check and verify exactly what was changed
without having to scrub through the video itself.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from core.transcript import Transcript
from projects.project_file import EditDecision


def _format_timestamp(seconds: float) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes):02d}:{secs:05.2f}"


def _highlighted_sentence(sentence_text: str, phrase_text: str) -> str:
    upper = phrase_text.strip().rstrip(".,!?;:")
    if not upper:
        return sentence_text
    return (
        sentence_text.replace(phrase_text, phrase_text.upper(), 1)
        if phrase_text in sentence_text
        else sentence_text
    )


def build_change_report(
    source_video: Path,
    transcript: Transcript,
    edits: list[EditDecision],
) -> str:
    included = [e for e in edits if e.include]
    included.sort(key=lambda e: transcript.words[e.word_index].start)

    lines = [
        "FoulPlay Change Report",
        f"Source: {source_video}",
        f"Generated: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Total edits: {len(included)}",
        "",
    ]

    if not included:
        lines.append("(No edits were applied.)")
        return "\n".join(lines)

    for edit in included:
        span_words = transcript.words[edit.word_index : edit.word_index + edit.word_span]
        start_word = span_words[0]
        end_word = span_words[-1]
        phrase_text = " ".join(w.text for w in span_words)
        sentence = transcript.sentence_by_id(start_word.sentence_id)
        context = _highlighted_sentence(sentence.text, phrase_text) if sentence else "(unknown context)"
        lines.append(
            f"{_format_timestamp(start_word.start)} - {_format_timestamp(end_word.end)}  "
            f'"{phrase_text}" -> "{edit.replacement}"'
        )
        lines.append(f"  Context: {context}")
        lines.append("")

    return "\n".join(lines)


def save_change_report(
    source_video: Path,
    transcript: Transcript,
    edits: list[EditDecision],
    output_path: Path,
) -> Path:
    report = build_change_report(source_video, transcript, edits)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return output_path
