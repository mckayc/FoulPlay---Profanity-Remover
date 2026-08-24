"""Builds the three subtitle tracks that always accompany a cleaned video:

  1. Unedited -- the full transcript verbatim, no substitutions (build_unedited_subtitles)
  2. Substituted -- normal subtitles reflecting each sentence's edited text (build_clean_subtitles)
  3. Substitute-only -- hidden except during edited lines, so the edit is
     visible even to a viewer with subtitles off (build_forced_subtitles)
"""

from __future__ import annotations

import pysubs2

from core.sentence_edit import SentenceEdit, subtitle_text_for_sentence
from core.transcript import Transcript
from settings.config import SubtitleTextMode


def _seconds_to_ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def build_unedited_subtitles(transcript: Transcript) -> pysubs2.SSAFile:
    """The full transcript verbatim -- no words replaced -- so the original
    dialogue can always be checked against what got changed.
    """
    return build_clean_subtitles(transcript, sentence_edits={})


def build_clean_subtitles(transcript: Transcript, sentence_edits: dict[int, SentenceEdit]) -> pysubs2.SSAFile:
    subs = pysubs2.SSAFile()
    for sentence in transcript.sentences:
        edit = sentence_edits.get(sentence.id)
        text = subtitle_text_for_sentence(transcript, sentence, edit) if edit else sentence.text
        subs.append(
            pysubs2.SSAEvent(start=_seconds_to_ms(sentence.start), end=_seconds_to_ms(sentence.end), text=text)
        )
    return subs


def build_forced_subtitles(
    transcript: Transcript,
    sentence_edits: dict[int, SentenceEdit],
    text_mode: SubtitleTextMode,
) -> pysubs2.SSAFile:
    subs = pysubs2.SSAFile()

    if text_mode == SubtitleTextMode.WORD_ONLY:
        for edit in sentence_edits.values():
            if not edit.edit_enabled:
                continue
            for start, end, replacement in edit.flagged_spans:
                # Only show it if the whole flagged span is still excluded
                # -- if the user manually restored any word in it, this
                # particular flag no longer applies.
                if not all(i in edit.excluded_word_indices for i in range(start, end + 1)):
                    continue
                start_word = transcript.words[start]
                end_word = transcript.words[end]
                subs.append(
                    pysubs2.SSAEvent(
                        start=_seconds_to_ms(start_word.start),
                        end=_seconds_to_ms(end_word.end),
                        text=f"[{replacement}]",
                    )
                )
        subs.sort()
        return subs

    # FULL_SENTENCE: reuse the clean-text reconstruction, but only for
    # sentences that actually have an active edit with something excluded.
    clean_subs = build_clean_subtitles(transcript, sentence_edits)
    changed_sentence_ids = {
        sentence_id
        for sentence_id, edit in sentence_edits.items()
        if edit.edit_enabled and edit.excluded_word_indices
    }
    for sentence, event in zip(transcript.sentences, clean_subs, strict=True):
        if sentence.id in changed_sentence_ids:
            subs.append(event)
    return subs
