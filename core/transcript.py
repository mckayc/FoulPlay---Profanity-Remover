"""Shared transcript data model.

This is the unified internal representation produced by either the ASR
path (core/transcribe.py) or the forced-alignment path (core/align.py,
milestone 6), and consumed by profanity matching, the review UI, and
subtitle generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Word:
    text: str
    start: float
    end: float
    sentence_id: int


@dataclass
class Sentence:
    id: int
    text: str
    start: float
    end: float


@dataclass
class Transcript:
    words: list[Word] = field(default_factory=list)
    sentences: list[Sentence] = field(default_factory=list)
    source_language: str = "en"

    def sentence_by_id(self, sentence_id: int) -> Sentence | None:
        for sentence in self.sentences:
            if sentence.id == sentence_id:
                return sentence
        return None
