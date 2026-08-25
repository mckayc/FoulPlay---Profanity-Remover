"""Rough time estimates for the transcription step, based on ballpark
faster-whisper throughput per model size and device. These are not
measured benchmarks -- purely to set expectations on the pre-run screen
before a user commits to potentially transcribing a full movie.
"""

from __future__ import annotations

# (low, high) estimated processing-seconds-per-video-second, CPU int8.
_CPU_REALTIME_FACTORS: dict[str, tuple[float, float]] = {
    "tiny": (0.2, 0.4),
    "base": (0.3, 0.6),
    "small": (0.6, 1.1),
    "medium": (1.8, 3.0),
    "large-v2": (3.5, 5.5),
    "large-v3": (3.5, 5.5),
}
_GPU_SPEEDUP = 6.0  # rough CUDA speedup over CPU int8; DirectML isn't used for Whisper here


def estimate_transcription_minutes(duration_seconds: float, model_size: str, use_gpu: bool) -> tuple[float, float]:
    low, high = _CPU_REALTIME_FACTORS.get(model_size, (1.0, 2.0))
    if use_gpu:
        low /= _GPU_SPEEDUP
        high /= _GPU_SPEEDUP
    low_minutes = duration_seconds * low / 60.0
    high_minutes = duration_seconds * high / 60.0
    return max(low_minutes, 0.5), max(high_minutes, 1.0)


def format_minutes_range(low_minutes: float, high_minutes: float) -> str:
    def fmt(m: float) -> str:
        if m < 1:
            return "under a minute"
        if m < 60:
            return f"{round(m)} min"
        return f"{m / 60:.1f} hr"

    low_str, high_str = fmt(low_minutes), fmt(high_minutes)
    if low_str == high_str:
        return high_str
    return f"{low_str} - {high_str}"
