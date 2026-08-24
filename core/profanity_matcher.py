"""Matches transcript words against the configured profanity word list,
grouping hits with their sentence for full context in the review screen.

Word-list entries can be a single word ("fuck") or a multi-word phrase
("oh my god"); phrases match a run of consecutive words in the transcript
exactly (no inflection variance -- these are fixed idioms), while single
words use the inflection-aware matching in _matches_root.
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
    word_index: int  # index of the FIRST word in transcript.words
    word_span: int  # number of consecutive transcript words this match covers (>=1)
    word: Word  # the first word in the span
    sentence: Sentence
    matched_term: str  # normalized word, or space-joined normalized phrase
    proposed_replacement: str
    occurrence_in_sentence: int  # nth occurrence (0-based) of matched_term within the sentence
    include: bool = True
    override_replacement: str | None = None

    @property
    def replacement(self) -> str:
        return self.override_replacement if self.override_replacement is not None else self.proposed_replacement


def _entry_tokens(entry: WordEntry) -> list[str]:
    return [t for t in (normalize_word(t) for t in entry.word.strip().split()) if t]


def find_matches(transcript: Transcript, word_entries: list[WordEntry]) -> list[Match]:
    # Longer phrases first, then longer single roots, so e.g. a listed
    # "jesus christ" phrase wins over a lone "christ" entry, and a listed
    # "asshole" wins over a listed "ass" for a word that matches both.
    candidates = [
        (_entry_tokens(e), e) for e in word_entries if e.enabled and e.word.strip()
    ]
    candidates = [(tokens, e) for tokens, e in candidates if tokens]
    candidates.sort(key=lambda pair: (len(pair[0]), len(pair[0][0])), reverse=True)

    if not candidates:
        return []

    words = transcript.words
    n = len(words)
    occurrence_counts: dict[tuple[int, str], int] = {}
    matches: list[Match] = []

    i = 0
    while i < n:
        word = words[i]
        normalized = normalize_word(word.text)
        if not normalized:
            i += 1
            continue

        matched_entry: WordEntry | None = None
        matched_span = 1
        matched_phrase = normalized

        for tokens, entry in candidates:
            span = len(tokens)
            if i + span > n:
                continue
            if span == 1:
                if _matches_root(normalized, tokens[0]):
                    matched_entry = entry
                    matched_span = 1
                    matched_phrase = normalized
                    break
            else:
                candidate_words = words[i : i + span]
                if any(w.sentence_id != word.sentence_id for w in candidate_words):
                    continue
                candidate_normalized = [normalize_word(w.text) for w in candidate_words]
                if candidate_normalized == tokens:
                    matched_entry = entry
                    matched_span = span
                    matched_phrase = " ".join(candidate_normalized)
                    break

        if matched_entry is None:
            i += 1
            continue

        sentence = transcript.sentence_by_id(word.sentence_id)
        if sentence is None:
            i += 1
            continue

        key = (word.sentence_id, matched_phrase)
        occurrence = occurrence_counts.get(key, 0)
        occurrence_counts[key] = occurrence + 1

        replacement_pool = matched_entry.replacements or [matched_entry.word]
        proposed = random.choice(replacement_pool)

        matches.append(
            Match(
                word_index=i,
                word_span=matched_span,
                word=word,
                sentence=sentence,
                matched_term=matched_phrase,
                proposed_replacement=proposed,
                occurrence_in_sentence=occurrence,
            )
        )

        i += matched_span  # skip past the matched span so it isn't matched again

    logger.info(
        "Profanity matching found %d hit(s) against %d configured word/phrase entries",
        len(matches),
        len(candidates),
    )
    return matches


def find_highlight_span(sentence_text: str, matched_term: str, occurrence_index: int) -> tuple[int, int] | None:
    """Locate the character span of the nth occurrence of matched_term (a
    single word or a space-joined phrase) as whole word(s).
    """
    tokens = matched_term.split(" ")
    token_patterns = [r"\b" + re.escape(t) + r"\w*" for t in tokens]
    pattern = re.compile(r"[^\w]+".join(token_patterns), re.IGNORECASE)

    count = 0
    for m in pattern.finditer(sentence_text):
        # Split like normalize_word does (word chars + apostrophes are kept
        # together, e.g. "god's" stays one token) so this check doesn't
        # spuriously split contractions into two tokens and reject a
        # correct match.
        matched_tokens = [normalize_word(t) for t in re.split(r"[^\w']+", m.group()) if t]
        if " ".join(matched_tokens) == matched_term:
            if count == occurrence_index:
                return m.span()
            count += 1
    return None
