"""Subtitle-assisted hybrid transcription.

Runs a full-video Whisper pass (accurate model by default; the fast model
only if the user has explicitly opted into prioritize_speed -- see
settings.config.PerformanceSettings), then -- only when a subtitle was
supplied -- uses it purely as a safety net for words that pass might have
missed (quiet dialogue, background noise; a subtitle's text has no such
acoustic dependency), paying for a slower, more accurate re-pass only on
the small set of regions that actually need it. A subtitle is never used
to restrict transcription scope, only to catch what the full-coverage
pass might have gotten wrong. Speed and subtitle-assist are independent
knobs: attaching a subtitle does not, by itself, trade away baseline
transcript quality.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pysubs2
from pydub import AudioSegment

from core import media
from core.profanity_matcher import Match, find_matches
from core.subtitle_sync import SubtitleEvent, sync_subtitle_to_transcript
from core.transcribe import ProgressCallback, transcribe_audio
from core.transcript import Sentence, Transcript, Word
from settings.config import PerformanceSettings, WordEntry

logger = logging.getLogger(__name__)

EventCallback = Callable[[str], None]

_CROSS_CHECK_BUFFER_SECONDS = 7.0


@dataclass
class HybridStats:
    """Summarizes what the subtitle safety net actually did, so the
    Review page can surface it without the user having had to watch the
    Transcribe page's activity log scroll by."""

    subtitle_used: bool = False
    synced: bool = False
    candidates_checked: int = 0
    confirmed_additional: int = 0
    needs_verification_ids: set[int] = field(default_factory=set)


def _format_ts(seconds: float) -> str:
    total_minutes, secs = divmod(max(seconds, 0), 60)
    hours, minutes = divmod(int(total_minutes), 60)
    if hours:
        return f"{hours}:{int(minutes):02d}:{int(secs):02d}"
    return f"{int(minutes)}:{int(secs):02d}"


def load_subtitle_events(subtitle_path: Path) -> list[SubtitleEvent]:
    subs = pysubs2.load(str(subtitle_path))
    events = []
    for line in subs:
        text = line.plaintext.strip().replace("\n", " ")
        if not text:
            continue
        events.append(SubtitleEvent(text=text, start=line.start / 1000.0, end=line.end / 1000.0))
    return events


def _pseudo_transcript_from_events(events: list[SubtitleEvent]) -> Transcript:
    """Adapts subtitle events into a Transcript-shaped structure so the
    existing find_matches() can scan them without new matching logic --
    each event becomes one pseudo-sentence whose words all share its
    start/end. Subtitle timing isn't word-precise, so this is only used to
    know WHICH words to look for and roughly WHERE -- never for muting.
    """
    words: list[Word] = []
    sentences: list[Sentence] = []
    for i, event in enumerate(events):
        tokens = event.text.split()
        if not tokens:
            continue
        for token in tokens:
            words.append(Word(text=token, start=event.start, end=event.end, sentence_id=i))
        sentences.append(Sentence(id=i, text=event.text, start=event.start, end=event.end))
    return Transcript(words=words, sentences=sentences)


def _find_covering_sentence(transcript: Transcript, start: float, end: float) -> Sentence | None:
    best: Sentence | None = None
    best_overlap = 0.0
    for s in transcript.sentences:
        overlap = min(s.end, end) - max(s.start, start)
        if overlap > best_overlap:
            best_overlap = overlap
            best = s
    return best


def _matches_overlap(matches: list[Match], start: float, end: float) -> bool:
    return any(m.word.start <= end and m.word.end >= start for m in matches)


def _next_sentence_id(transcript: Transcript) -> int:
    return max((s.id for s in transcript.sentences), default=-1) + 1


def _rebuild_sentence_text(transcript: Transcript, sentence_id: int) -> None:
    words = sorted((w for w in transcript.words if w.sentence_id == sentence_id), key=lambda w: w.start)
    sentence = transcript.sentence_by_id(sentence_id)
    if sentence is not None and words:
        sentence.text = " ".join(w.text for w in words)
        sentence.start = words[0].start
        sentence.end = words[-1].end


def _flag_needs_verification(
    transcript: Transcript, window_start: float, window_end: float, subtitle_text: str, needs_ids: set[int]
) -> None:
    covering = _find_covering_sentence(transcript, window_start, window_end)
    if covering is not None:
        needs_ids.add(covering.id)
        return
    # No sentence at all here (interpreted as silence) -- synthesize a
    # placeholder from the subtitle's own text/corrected timing so Review
    # has something to act on.
    new_id = _next_sentence_id(transcript)
    transcript.sentences.append(Sentence(id=new_id, text=subtitle_text, start=window_start, end=window_end))
    for token in subtitle_text.split():
        transcript.words.append(Word(text=token, start=window_start, end=window_end, sentence_id=new_id))
    needs_ids.add(new_id)


def _splice_slice(transcript: Transcript, slice_transcript: Transcript, window_start: float, window_end: float) -> None:
    covering = _find_covering_sentence(transcript, window_start, window_end)
    if covering is None:
        target_id = _next_sentence_id(transcript)
        transcript.sentences.append(Sentence(id=target_id, text="", start=window_start, end=window_end))
    else:
        target_id = covering.id

    removed = [w for w in transcript.words if window_start <= w.start < window_end]
    affected_sentence_ids = {w.sentence_id for w in removed} | {target_id}
    if removed:
        transcript.words = [w for w in transcript.words if w not in removed]

    for w in slice_transcript.words:
        transcript.words.append(
            Word(text=w.text, start=w.start + window_start, end=w.end + window_start, sentence_id=target_id)
        )

    for sentence_id in affected_sentence_ids:
        _rebuild_sentence_text(transcript, sentence_id)


def hybrid_transcribe(
    video_path: Path,
    subtitle_path: Path | None,
    performance: PerformanceSettings,
    word_entries: list[WordEntry],
    workdir: Path,
    on_event: EventCallback | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[Transcript, HybridStats]:
    """Returns (transcript, stats)."""

    def emit(message: str) -> None:
        if on_event:
            on_event(message)

    stats = HybridStats(subtitle_used=subtitle_path is not None)

    audio_path = workdir / "extracted_audio.wav"
    emit("Extracting audio...")
    media.extract_audio(video_path, audio_path)

    baseline_model = performance.whisper_fast_model_size if performance.prioritize_speed else performance.whisper_model_size
    baseline_label = "fast" if performance.prioritize_speed else "full-quality"
    emit(f"Running {baseline_label} transcription pass (model={baseline_model})...")
    transcript = transcribe_audio(
        audio_path,
        model_size=baseline_model,
        language=performance.whisper_language,
        vad_filter=performance.whisper_vad_filter,
        beam_size=performance.whisper_beam_size,
        prefer_gpu=performance.prefer_gpu,
        on_progress=on_progress,
    )

    baseline_matches = find_matches(transcript, word_entries)
    for m in baseline_matches:
        emit(f"Found flagged word '{m.matched_term}' at {_format_ts(m.word.start)}")

    if subtitle_path is None:
        return transcript, stats

    try:
        events = load_subtitle_events(subtitle_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load subtitle file %s: %s", subtitle_path, exc)
        emit("Could not read the supplied subtitle file -- continuing without subtitle assist.")
        return transcript, stats

    sync = sync_subtitle_to_transcript(events, transcript)
    if sync is None:
        emit("Could not reliably sync subtitle to video -- continuing without subtitle assist.")
        return transcript, stats
    stats.synced = True
    emit(f"Synced subtitle to video (offset: {sync.offset:+.1f}s, scale: {sync.scale:.4f})")

    pseudo = _pseudo_transcript_from_events(events)
    subtitle_matches = find_matches(pseudo, word_entries)
    if not subtitle_matches:
        emit("Subtitle contains no flagged words.")
        return transcript, stats

    emit(
        f"Subtitle mentions {len(subtitle_matches)} possible flagged word(s); cross-checking against the baseline pass..."
    )

    total_duration = media.probe(video_path).duration_seconds
    full_audio = AudioSegment.from_file(audio_path)
    accurate_model = performance.whisper_model_size

    for sm in subtitle_matches:
        raw_start = sync.correct(sm.word.start)
        raw_end = sync.correct(sm.word.end)
        window_start = max(raw_start - _CROSS_CHECK_BUFFER_SECONDS, 0.0)
        window_end = min(raw_end + _CROSS_CHECK_BUFFER_SECONDS, total_duration)

        if _matches_overlap(baseline_matches, window_start, window_end):
            continue  # already covered by the baseline pass

        if window_end <= window_start:
            continue

        stats.candidates_checked += 1
        emit(
            f"Subtitle mentions '{sm.matched_term}' near {_format_ts(raw_start)} but the baseline pass "
            "didn't catch it -- re-checking with the accurate model..."
        )

        slice_path = workdir / f"slice_{int(window_start * 1000)}.wav"
        segment = full_audio[int(window_start * 1000) : int(window_end * 1000)]
        segment.export(slice_path, format="wav")

        try:
            slice_transcript = transcribe_audio(
                slice_path,
                model_size=accurate_model,
                language=performance.whisper_language,
                vad_filter=False,
                beam_size=performance.whisper_beam_size,
                prefer_gpu=performance.prefer_gpu,
            )
        finally:
            slice_path.unlink(missing_ok=True)

        confirm_matches = find_matches(slice_transcript, word_entries)
        if not confirm_matches:
            emit(
                f"Still couldn't confirm '{sm.matched_term}' near {_format_ts(raw_start)} -- "
                "flagging for manual review."
            )
            _flag_needs_verification(transcript, window_start, window_end, sm.sentence.text, stats.needs_verification_ids)
            continue

        stats.confirmed_additional += 1
        emit(f"Confirmed '{sm.matched_term}' near {_format_ts(raw_start)} with the accurate model.")
        _splice_slice(transcript, slice_transcript, window_start, window_end)

    return transcript, stats
