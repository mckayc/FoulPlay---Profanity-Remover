"""Matches transcript words against the configured profanity word list,
grouping hits with their sentence for full context in the review screen.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass

from core.transcript import Sentence, Transcript, Word
from settings.config import WordEntry

logger = logging.getLogger(__name__)

_STRIP_RE = re.compile(r"^[^\w']+|[^\w']+$")

# Common inflectional endings a listed root word might carry in real speech
# (e.g. "fuck" -> "fucking"/"fucked"/"fucker", "ass" -> "asses"). Deliberately
# NOT open-ended prefix or substring matching -- that would also flag
# unrelated words like "hello" (starts with "hell") or "class"/"grass"
# (contain "ass"). Requiring the remainder after the root to be one of
# these known suffixes keeps matches to genuine inflections of the word.
_INFLECTION_SUFFIXES = ("", "s", "es", "ed", "ing", "er", "ers", "y", "ty", "in", "it")


def normalize_word(text: str) -> str:
    return _STRIP_RE.sub("", text).lower()


def _matches_root(normalized_word: str, root: str) -> bool:
    """True if normalized_word is exactly root, or root plus a recognized
    inflectional suffix (including a doubled trailing consonant before a
    vowel suffix, e.g. "shit" -> "shitting").
    """
    if not root or not normalized_word.startswith(root):
        return False
    remainder = normalized_word[len(root):]
    if remainder in _INFLECTION_SUFFIXES:
        return True
    if remainder and remainder[0] == root[-1] and remainder[1:] in _INFLECTION_SUFFIXES:
        return True
    return False


@dataclass
class Match:
    word_index: int  # index into transcript.words
    word: Word
    sentence: Sentence
    matched_term: str
    proposed_replacement: str
    occurrence_in_sentence: int  # nth occurrence (0-based) of matched_term within the sentence
    include: bool = True
    override_replacement: str | None = None

    @property
    def replacement(self) -> str:
        return self.override_replacement if self.override_replacement is not None else self.proposed_replacement


def find_matches(transcript: Transcript, word_entries: list[WordEntry]) -> list[Match]:
    # Longest root first, so e.g. a listed "asshole" wins over a listed "ass"
    # for a word that matches both.
    roots = sorted(
        (
            (e.word.strip().lower(), e)
            for e in word_entries
            if e.enabled and e.word.strip()
        ),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    if not roots:
        return []

    occurrence_counts: dict[tuple[int, str], int] = {}
    matches: list[Match] = []

    for index, word in enumerate(transcript.words):
        normalized = normalize_word(word.text)
        if not normalized:
            continue
        entry = next((e for root, e in roots if _matches_root(normalized, root)), None)
        if entry is None:
            continue
        sentence = transcript.sentence_by_id(word.sentence_id)
        if sentence is None:
            continue

        key = (word.sentence_id, normalized)
        occurrence = occurrence_counts.get(key, 0)
        occurrence_counts[key] = occurrence + 1

        replacement_pool = entry.replacements or [entry.word]
        proposed = random.choice(replacement_pool)

        matches.append(
            Match(
                word_index=index,
                word=word,
                sentence=sentence,
                matched_term=normalized,
                proposed_replacement=proposed,
                occurrence_in_sentence=occurrence,
            )
        )

    logger.info("Profanity matching found %d hit(s) against %d configured word(s)", len(matches), len(roots))
    return matches


def find_highlight_span(sentence_text: str, matched_term: str, occurrence_index: int) -> tuple[int, int] | None:
    """Locate the character span of the nth occurrence of matched_term as a whole word."""
    pattern = re.compile(r"\b" + re.escape(matched_term) + r"\w*", re.IGNORECASE)
    count = 0
    for m in pattern.finditer(sentence_text):
        if normalize_word(m.group()) == matched_term:
            if count == occurrence_index:
                return m.span()
            count += 1
    return None
