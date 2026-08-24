"""Builds the three subtitle tracks that always accompany a cleaned video:

  1. Unedited -- the full transcript verbatim, no substitutions (build_unedited_subtitles)
  2. Substituted -- normal subtitles with replacement words swapped in throughout (build_clean_subtitles)
  3. Substitute-only -- hidden except during edited lines, so the edit is
     visible even to a viewer with subtitles off (build_forced_subtitles)
"""

from __future__ import annotations

import pysubs2

from core.transcript import Transcript, Word
from projects.project_file import EditDecision
from settings.config import SubtitleTextMode


def _seconds_to_ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def build_unedited_subtitles(transcript: Transcript) -> pysubs2.SSAFile:
    """The full transcript verbatim -- no words replaced -- so the original
    dialogue can always be checked against what got changed.
    """
    return build_clean_subtitles(transcript, edits=[])


def build_clean_subtitles(transcript: Transcript, edits: list[EditDecision]) -> pysubs2.SSAFile:
    # For a phrase edit (word_span > 1), the replacement text goes at the
    # first word's position; the rest of the span is dropped from the
    # reconstructed text so it doesn't appear twice.
    replacement_by_index: dict[int, str] = {}
    skip_indices: set[int] = set()
    for e in edits:
        if not e.include:
            continue
        replacement_by_index[e.word_index] = e.replacement
        for offset in range(1, e.word_span):
            skip_indices.add(e.word_index + offset)

    sentence_words: dict[int, list[tuple[int, Word]]] = {}
    for index, word in enumerate(transcript.words):
        sentence_words.setdefault(word.sentence_id, []).append((index, word))

    subs = pysubs2.SSAFile()
    for sentence in transcript.sentences:
        words = sentence_words.get(sentence.id, [])
        if words:
            parts = [
                replacement_by_index.get(index, word.text)
                for index, word in words
                if index not in skip_indices
            ]
            text = " ".join(parts)
        else:
            text = sentence.text
        subs.append(
            pysubs2.SSAEvent(start=_seconds_to_ms(sentence.start), end=_seconds_to_ms(sentence.end), text=text)
        )
    return subs


def build_forced_subtitles(
    transcript: Transcript,
    edits: list[EditDecision],
    text_mode: SubtitleTextMode,
) -> pysubs2.SSAFile:
    included = [e for e in edits if e.include]
    subs = pysubs2.SSAFile()

    if text_mode == SubtitleTextMode.WORD_ONLY:
        for edit in included:
            start_word = transcript.words[edit.word_index]
            end_word = transcript.words[edit.word_index + edit.word_span - 1]
            subs.append(
                pysubs2.SSAEvent(
                    start=_seconds_to_ms(start_word.start),
                    end=_seconds_to_ms(end_word.end),
                    text=f"[{edit.replacement}]",
                )
            )
        return subs

    # FULL_SENTENCE: reuse the clean-text reconstruction, but only for
    # sentences that actually contain an included edit.
    clean_subs = build_clean_subtitles(transcript, edits)
    sentence_ids_with_edits = {transcript.words[e.word_index].sentence_id for e in included}
    for sentence, event in zip(transcript.sentences, clean_subs, strict=True):
        if sentence.id in sentence_ids_with_edits:
            subs.append(event)
    return subs
