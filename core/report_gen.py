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


def _highlighted_sentence(sentence_text: str, word_text: str) -> str:
    upper = word_text.strip().rstrip(".,!?;:")
    if not upper:
        return sentence_text
    return sentence_text.replace(word_text, word_text.upper(), 1) if word_text in sentence_text else sentence_text


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
        word = transcript.words[edit.word_index]
        sentence = transcript.sentence_by_id(word.sentence_id)
        context = _highlighted_sentence(sentence.text, word.text) if sentence else "(unknown context)"
        lines.append(
            f"{_format_timestamp(word.start)} - {_format_timestamp(word.end)}  "
            f'"{word.text}" -> "{edit.replacement}"'
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
