"""Generates a plain-text report of every changed sentence, saved alongside
the output video, so a user can check and verify exactly what was changed
without having to scrub through the video itself.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from core.sentence_edit import SentenceEdit, audio_text_for_sentence, subtitle_text_for_sentence
from core.transcript import Transcript


def _format_timestamp(seconds: float) -> str:
    """H:MM:SS(.ss), matching how video players display elapsed time --
    hours are only shown once the clip is long enough to need them, rather
    than letting minutes run past 59 (e.g. "70:15" instead of "1:10:15")."""
    total_minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(int(total_minutes), 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:05.2f}"
    return f"{minutes:02d}:{secs:05.2f}"


def build_change_report(
    source_video: Path,
    transcript: Transcript,
    sentence_edits: dict[int, SentenceEdit],
) -> str:
    changed = [
        edit for edit in sentence_edits.values() if edit.edit_enabled and (edit.excluded_word_indices or edit.custom_subtitle_text)
    ]
    changed.sort(key=lambda e: transcript.sentence_by_id(e.sentence_id).start)

    lines = [
        "FoulPlay Change Report",
        f"Source: {source_video}",
        f"Generated: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Total changed sentences: {len(changed)}",
        "",
    ]

    if not changed:
        lines.append("(No edits were applied.)")
        return "\n".join(lines)

    for edit in changed:
        sentence = transcript.sentence_by_id(edit.sentence_id)
        audio_text = audio_text_for_sentence(transcript, sentence, edit)
        subtitle_text = subtitle_text_for_sentence(transcript, sentence, edit)

        lines.append(f"{_format_timestamp(sentence.start)} - {_format_timestamp(sentence.end)}")
        lines.append(f"  Original:  {sentence.text}")
        lines.append(f"  Audio:     {audio_text}")
        if subtitle_text != audio_text:
            lines.append(f"  Subtitles: {subtitle_text}")
        lines.append("")

    return "\n".join(lines)


def save_change_report(
    source_video: Path,
    transcript: Transcript,
    sentence_edits: dict[int, SentenceEdit],
    output_path: Path,
) -> Path:
    report = build_change_report(source_video, transcript, sentence_edits)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return output_path
