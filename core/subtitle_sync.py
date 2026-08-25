"""Syncs a subtitle file's timeline to the video's real timeline via fuzzy
text matching against a baseline transcript.

A subtitle sourced separately from the video (a downloaded release, a
different cut) is frequently offset -- sometimes by a constant amount,
sometimes by a framerate-driven drift that grows over the runtime. Using
its timestamps to locate audio without correcting for this first would
send hybrid transcription's targeted re-pass to the wrong place. This
module fits a linear correction (real_time = scale * subtitle_time +
offset) from confident text anchors, and refuses to guess if the anchors
are too sparse or inconsistent to trust.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass

from core.transcript import Transcript

logger = logging.getLogger(__name__)

_MIN_SIMILARITY = 0.6
_MIN_ANCHOR_TEXT_LEN = 8
_MAX_ANCHOR_CANDIDATES = 30
_MIN_ANCHORS = 4
_SEARCH_WINDOW_SECONDS = 600.0
_MAX_RESIDUAL_STD_SECONDS = 2.0
_MIN_SCALE = 0.5
_MAX_SCALE = 1.5


@dataclass
class SubtitleEvent:
    text: str
    start: float
    end: float


@dataclass
class SyncResult:
    offset: float
    scale: float
    anchor_count: int
    residual_std: float

    def correct(self, seconds: float) -> float:
        return self.scale * seconds + self.offset


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _pick_anchor_candidates(events: list[SubtitleEvent], count: int) -> list[SubtitleEvent]:
    usable = [e for e in events if len(_normalize(e.text)) >= _MIN_ANCHOR_TEXT_LEN]
    if len(usable) <= count:
        return usable
    step = len(usable) / count
    return [usable[int(i * step)] for i in range(count)]


def sync_subtitle_to_transcript(events: list[SubtitleEvent], transcript: Transcript) -> SyncResult | None:
    """Returns None ("don't guess") if too few confident anchors are found,
    or if the fit's residuals are too scattered to trust."""
    candidates = _pick_anchor_candidates(events, _MAX_ANCHOR_CANDIDATES)
    if len(candidates) < _MIN_ANCHORS:
        logger.info("Subtitle sync: only %d usable anchor candidate(s), skipping", len(candidates))
        return None

    sentence_texts = [(s.start, _normalize(s.text)) for s in transcript.sentences if s.text.strip()]

    pairs: list[tuple[float, float]] = []  # (subtitle_time, matched_transcript_time)
    for event in candidates:
        target = _normalize(event.text)
        best_ratio = 0.0
        best_time: float | None = None
        for start, text in sentence_texts:
            if abs(start - event.start) > _SEARCH_WINDOW_SECONDS:
                continue
            ratio = difflib.SequenceMatcher(None, target, text).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_time = start
        if best_ratio >= _MIN_SIMILARITY and best_time is not None:
            pairs.append((event.start, best_time))

    if len(pairs) < _MIN_ANCHORS:
        logger.info("Subtitle sync: only %d confident anchor(s) matched, skipping", len(pairs))
        return None

    n = len(pairs)
    sum_x = sum(p[0] for p in pairs)
    sum_y = sum(p[1] for p in pairs)
    sum_xx = sum(p[0] * p[0] for p in pairs)
    sum_xy = sum(p[0] * p[1] for p in pairs)
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-6:
        scale = 1.0
        offset = (sum_y - sum_x) / n
    else:
        scale = (n * sum_xy - sum_x * sum_y) / denom
        offset = (sum_y - scale * sum_x) / n

    residuals = [y - (scale * x + offset) for x, y in pairs]
    mean_residual = sum(residuals) / n
    variance = sum((r - mean_residual) ** 2 for r in residuals) / n
    std = variance**0.5

    if std > _MAX_RESIDUAL_STD_SECONDS or not (_MIN_SCALE <= scale <= _MAX_SCALE):
        logger.info(
            "Subtitle sync: fit too inconsistent (residual std=%.2fs, scale=%.3f) from %d anchor(s), skipping",
            std,
            scale,
            n,
        )
        return None

    logger.info(
        "Subtitle sync: fit offset=%.2fs scale=%.4f from %d anchor(s), residual std=%.2fs",
        offset,
        scale,
        n,
        std,
    )
    return SyncResult(offset=offset, scale=scale, anchor_count=n, residual_std=std)
