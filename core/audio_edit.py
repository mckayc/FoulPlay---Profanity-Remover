"""Applies per-word audio edits (silence/volume/beep) to the isolated vocal
stem, with short fades at cut boundaries to avoid clicks, then remixes the
edited vocals back with the accompaniment stem.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydub import AudioSegment
from pydub.generators import Sine

from core.transcript import Transcript
from projects.project_file import EditDecision
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


def edit_vocals(
    vocals_path: Path,
    transcript: Transcript,
    edits: list[EditDecision],
    settings: AudioEditSettings,
    output_path: Path,
) -> Path:
    audio = AudioSegment.from_file(vocals_path)
    fade_ms = int(settings.fade_ms)
    pad_before_ms = int(settings.pad_before_ms)
    pad_after_ms = int(settings.pad_after_ms)

    included = [e for e in edits if e.include]
    included.sort(key=lambda e: transcript.words[e.word_index].start)
    logger.info(
        "Applying %d audio edit(s), mode=%s, pad_before=%dms, pad_after=%dms, fade=%dms",
        len(included),
        settings.mode,
        pad_before_ms,
        pad_after_ms,
        fade_ms,
    )

    for edit in included:
        start_word = transcript.words[edit.word_index]
        end_word = transcript.words[edit.word_index + edit.word_span - 1]
        start_ms = max(int(start_word.start * 1000) - pad_before_ms, 0)
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
        phrase_text = " ".join(
            w.text for w in transcript.words[edit.word_index : edit.word_index + edit.word_span]
        )
        logger.debug(
            "Edited word(s) #%d '%s' [%.2fs-%.2fs] -> '%s'",
            edit.word_index,
            phrase_text,
            start_word.start,
            end_word.end,
            edit.replacement,
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
