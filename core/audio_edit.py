"""Applies per-sentence audio edits (silence/volume/beep) to the isolated
vocal stem, with short fades at cut boundaries to avoid clicks, then
remixes the edited vocals back with the accompaniment stem.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydub import AudioSegment
from pydub.generators import Sine

from core.sentence_edit import SentenceEdit
from core.transcript import Transcript
from settings.config import AudioEditMode, AudioEditSettings

logger = logging.getLogger(__name__)


def _apply_fade_envelope(segment: AudioSegment, fade_ms: int) -> AudioSegment:
    fade_ms = min(fade_ms, len(segment) // 2)
    if fade_ms <= 0:
        return segment
    return segment.fade_in(fade_ms).fade_out(fade_ms)


def _match_format(segment: AudioSegment, reference: AudioSegment) -> AudioSegment:
    if segment.frame_rate != reference.frame_rate:
        segment = segment.set_frame_rate(reference.frame_rate)
    if segment.channels != reference.channels:
        segment = segment.set_channels(reference.channels)
    return segment


# Fricatives (s, f, v, z, "sh", "th") and, to a lesser extent, "h" build up
# gradually and quietly rather than starting sharply like a plosive or
# vowel does. Whisper's word-start timestamps are derived from an
# attention/alignment mechanism that tends to mark a word as "starting"
# once its acoustic signature is clearly distinguishable -- for a
# fricative, that point lands measurably after the sound has actually
# begun, since the onset is quiet and noise-like rather than a sudden
# spike. The practical effect: without extra lead-in, the first part of
# words like "shit" or "stupid" audibly survives the mute. Order doesn't
# matter here since every pattern gets the same extra padding.
_SOFT_ONSET_PATTERNS = ("sh", "th", "s", "f", "v", "z", "h")
_SOFT_ONSET_EXTRA_MS = 80


def _extra_lead_in_ms(word_text: str) -> int:
    normalized = word_text.strip().lower().lstrip("\"'([{-")
    if any(normalized.startswith(pattern) for pattern in _SOFT_ONSET_PATTERNS):
        return _SOFT_ONSET_EXTRA_MS
    return 0


def _contiguous_runs(indices: set[int]) -> list[tuple[int, int]]:
    """Groups a set of word indices into (start, end_inclusive) runs of
    consecutive indices, so adjacent excluded words are muted as one
    combined window instead of getting separate, potentially overlapping
    fade/pad treatment.
    """
    if not indices:
        return []
    ordered = sorted(indices)
    runs: list[tuple[int, int]] = []
    run_start = ordered[0]
    prev = ordered[0]
    for idx in ordered[1:]:
        if idx == prev + 1:
            prev = idx
            continue
        runs.append((run_start, prev))
        run_start = idx
        prev = idx
    runs.append((run_start, prev))
    return runs


def edit_vocals(
    vocals_path: Path,
    transcript: Transcript,
    sentence_edits: dict[int, SentenceEdit],
    settings: AudioEditSettings,
    output_path: Path,
) -> Path:
    audio = AudioSegment.from_file(vocals_path)
    fade_ms = int(settings.fade_ms)
    pad_before_ms = int(settings.pad_before_ms)
    pad_after_ms = int(settings.pad_after_ms)

    windows: list[tuple[int, int]] = []  # (start_word_index, end_word_index_inclusive)
    for edit in sentence_edits.values():
        if not edit.edit_enabled or not edit.excluded_word_indices:
            continue
        windows.extend(_contiguous_runs(edit.excluded_word_indices))
    windows.sort(key=lambda run: transcript.words[run[0]].start)

    logger.info(
        "Applying %d audio mute window(s), mode=%s, pad_before=%dms, pad_after=%dms, fade=%dms",
        len(windows),
        settings.mode,
        pad_before_ms,
        pad_after_ms,
        fade_ms,
    )

    for start_index, end_index in windows:
        start_word = transcript.words[start_index]
        end_word = transcript.words[end_index]
        extra_lead_in = _extra_lead_in_ms(start_word.text)
        start_ms = max(int(start_word.start * 1000) - pad_before_ms - extra_lead_in, 0)
        end_ms = min(int(end_word.end * 1000) + pad_after_ms, len(audio))
        if end_ms <= start_ms:
            continue

        segment = audio[start_ms:end_ms]

        if settings.mode == AudioEditMode.SILENCE:
            replacement = AudioSegment.silent(duration=len(segment), frame_rate=audio.frame_rate)
            replacement = _match_format(replacement, audio)
        elif settings.mode == AudioEditMode.VOLUME:
            replacement = segment.apply_gain(settings.volume_db)
        else:  # BEEP
            tone = Sine(settings.beep_frequency_hz).to_audio_segment(duration=len(segment), volume=-6.0)
            replacement = _match_format(tone, audio)

        replacement = _apply_fade_envelope(replacement, fade_ms)
        audio = audio[:start_ms] + replacement + audio[end_ms:]
        muted_text = " ".join(w.text for w in transcript.words[start_index : end_index + 1])
        logger.debug(
            "Muted word(s) #%d-%d '%s' [%.2fs-%.2fs] (extra_lead_in=%dms)",
            start_index,
            end_index,
            muted_text,
            start_word.start,
            end_word.end,
            extra_lead_in,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(output_path, format="wav")
    logger.info("Edited vocal stem written to %s", output_path)
    return output_path


def remix(vocals_path: Path, accompaniment_path: Path, output_path: Path) -> Path:
    vocals = AudioSegment.from_file(vocals_path)
    accompaniment = AudioSegment.from_file(accompaniment_path)
    mixed = accompaniment.overlay(vocals)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mixed.export(output_path, format="wav")
    logger.info("Remixed audio written to %s", output_path)
    return output_path
