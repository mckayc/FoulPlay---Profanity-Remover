"""Builds subtitle files from the transcript + confirmed edit decisions.

Produces:
  * a "clean" subtitle track with replacement words substituted in place
    of the filtered words, for normal viewing with subtitles on
  * an optional "forced" track containing only the edited lines (word-only
    or full-sentence, per settings) so the edit is visible even to viewers
    who don't have subtitles enabled
"""

from __future__ import annotations

import pysubs2

from core.transcript import Transcript, Word
from projects.project_file import EditDecision
from settings.config import SubtitleTextMode


def _seconds_to_ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def build_clean_subtitles(transcript: Transcript, edits: list[EditDecision]) -> pysubs2.SSAFile:
    replacement_by_index = {e.word_index: e.replacement for e in edits if e.include}

    sentence_words: dict[int, list[tuple[int, Word]]] = {}
    for index, word in enumerate(transcript.words):
        sentence_words.setdefault(word.sentence_id, []).append((index, word))

    subs = pysubs2.SSAFile()
    for sentence in transcript.sentences:
        words = sentence_words.get(sentence.id, [])
        if words:
            text = " ".join(replacement_by_index.get(index, word.text) for index, word in words)
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
            word = transcript.words[edit.word_index]
            subs.append(
                pysubs2.SSAEvent(
                    start=_seconds_to_ms(word.start),
                    end=_seconds_to_ms(word.end),
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
