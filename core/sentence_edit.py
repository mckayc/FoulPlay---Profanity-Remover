"""Per-sentence edit state and the text-reconstruction helpers shared by
the Review UI and the processing pipeline.

Editing works per sentence rather than per flagged word: each sentence
with at least one match gets a SentenceEdit tracking which of its words
are currently excluded (muted from audio / omitted from subtitles), plus
independent control over the final subtitle text. This lets audio and
subtitles diverge -- e.g. dropping "the hell" entirely from audio for a
clean-sounding gap while subtitles still read "the heck" -- since audio
can only ever be muted, never made to say a replacement word.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.profanity_matcher import Match
from core.transcript import Sentence, Transcript


@dataclass
class SentenceEdit:
    sentence_id: int
    edit_enabled: bool = True
    mirror: bool = True
    # (start_index, end_index_inclusive, replacement) for each ORIGINAL
    # match in this sentence -- kept as a fixed reference for Reset and for
    # forced-subtitle timing, independent of the user's current word
    # selection below.
    flagged_spans: list[tuple[int, int, str]] = field(default_factory=list)
    # Current include/exclude state, word_index -> excluded. A superset of
    # the flagged words is possible (user excluded an adjacent word too);
    # a subset is possible (user restored a flagged word).
    excluded_word_indices: set[int] = field(default_factory=set)
    # None = auto-generate from the current word selection; set once the
    # user types in the unmirrored Subtitle box.
    custom_subtitle_text: str | None = None

    def flagged_word_indices(self) -> set[int]:
        indices: set[int] = set()
        for start, end, _replacement in self.flagged_spans:
            indices.update(range(start, end + 1))
        return indices

    def replacement_for_span_start(self, word_index: int) -> str | None:
        for start, _end, replacement in self.flagged_spans:
            if start == word_index:
                return replacement
        return None


def build_default_sentence_edits(transcript: Transcript, matches: list[Match]) -> dict[int, SentenceEdit]:
    by_sentence: dict[int, list[Match]] = {}
    for m in matches:
        by_sentence.setdefault(m.sentence.id, []).append(m)

    result: dict[int, SentenceEdit] = {}
    for sentence_id, sentence_matches in by_sentence.items():
        spans: list[tuple[int, int, str]] = []
        excluded: set[int] = set()
        for m in sentence_matches:
            end_index = m.word_index + m.word_span - 1
            spans.append((m.word_index, end_index, m.proposed_replacement))
            excluded.update(range(m.word_index, end_index + 1))
        result[sentence_id] = SentenceEdit(
            sentence_id=sentence_id,
            flagged_spans=spans,
            excluded_word_indices=excluded,
        )
    return result


def _sentence_word_indices(transcript: Transcript, sentence: Sentence) -> list[int]:
    return [i for i, w in enumerate(transcript.words) if w.sentence_id == sentence.id]


def audio_text_for_sentence(transcript: Transcript, sentence: Sentence, edit: SentenceEdit) -> str:
    if not edit.edit_enabled:
        return sentence.text
    parts = [
        transcript.words[i].text for i in _sentence_word_indices(transcript, sentence) if i not in edit.excluded_word_indices
    ]
    return " ".join(parts)


def subtitle_text_for_sentence(transcript: Transcript, sentence: Sentence, edit: SentenceEdit) -> str:
    if not edit.edit_enabled:
        return sentence.text
    if edit.mirror:
        return audio_text_for_sentence(transcript, sentence, edit)
    if edit.custom_subtitle_text is not None:
        return edit.custom_subtitle_text

    flagged = edit.flagged_word_indices()
    parts = []
    for i in _sentence_word_indices(transcript, sentence):
        if i not in edit.excluded_word_indices:
            parts.append(transcript.words[i].text)
            continue
        if i in flagged:
            replacement = edit.replacement_for_span_start(i)
            if replacement is not None:
                parts.append(replacement)
            # non-start words of a flagged span are dropped (replacement
            # already inserted at the span's start index)
        # manually-excluded, non-flagged words are dropped entirely
    return " ".join(parts)
