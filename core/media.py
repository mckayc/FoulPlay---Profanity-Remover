"""ffmpeg/ffprobe wrappers for probing media and extracting audio.

ffmpeg is treated as an external system dependency rather than something we
bundle or pip-install, to keep the distributable small -- most users either
already have it or can get it with a one-line winget/choco install.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

FFMPEG_INSTALL_HINT = (
    "FFmpeg was not found on your system PATH. Install it, e.g. with "
    "'winget install Gyan.FFmpeg' in a terminal, then restart FoulPlay."
)


class FfmpegNotFoundError(RuntimeError):
    pass


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FfmpegNotFoundError(FFMPEG_INSTALL_HINT)
    return path


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@dataclass
class MediaProbe:
    duration_seconds: float
    audio_streams: list[dict]
    subtitle_streams: list[dict]
    video_streams: list[dict]


def probe(path: Path) -> MediaProbe:
    ffprobe = require_tool("ffprobe")
    result = subprocess.run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    return MediaProbe(
        duration_seconds=float(data.get("format", {}).get("duration", 0.0) or 0.0),
        audio_streams=[s for s in streams if s.get("codec_type") == "audio"],
        subtitle_streams=[s for s in streams if s.get("codec_type") == "subtitle"],
        video_streams=[s for s in streams if s.get("codec_type") == "video"],
    )


def extract_audio(source: Path, dest_wav: Path, stream_index: int = 0) -> None:
    """Extract one audio stream as 16kHz mono PCM WAV (Whisper's expected input)."""
    ffmpeg = require_tool("ffmpeg")
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-map",
            f"0:a:{stream_index}",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-vn",
            str(dest_wav),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
