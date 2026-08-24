"""ffmpeg/ffprobe wrappers for probing media and extracting audio.

ffmpeg is treated as an external system dependency rather than something we
bundle or pip-install, to keep the distributable small -- most users either
already have it or can get it with a one-line winget/choco install.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from core import proc

logger = logging.getLogger(__name__)

FFMPEG_INSTALL_HINT = (
    "FFmpeg was not found on your system PATH. Install it, e.g. with "
    "'winget install Gyan.FFmpeg' in a terminal, then restart FoulPlay."
)


class FfmpegNotFoundError(RuntimeError):
    pass


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        logger.error("Required tool '%s' not found on PATH", name)
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
    logger.info("Probing media file: %s", path)
    result = proc.run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    media_probe = MediaProbe(
        duration_seconds=float(data.get("format", {}).get("duration", 0.0) or 0.0),
        audio_streams=[s for s in streams if s.get("codec_type") == "audio"],
        subtitle_streams=[s for s in streams if s.get("codec_type") == "subtitle"],
        video_streams=[s for s in streams if s.get("codec_type") == "video"],
    )
    logger.info(
        "Probe result: duration=%.1fs video=%d audio=%d subtitle=%d",
        media_probe.duration_seconds,
        len(media_probe.video_streams),
        len(media_probe.audio_streams),
        len(media_probe.subtitle_streams),
    )
    return media_probe


def extract_audio(source: Path, dest_wav: Path, stream_index: int = 0) -> None:
    """Extract one audio stream as 16kHz mono PCM WAV (Whisper's expected input)."""
    ffmpeg = require_tool("ffmpeg")
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
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
    ]
    logger.debug("Running: %s", " ".join(cmd))
    try:
        proc.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg audio extraction failed: %s\nstderr: %s", exc, exc.stderr)
        raise
    logger.info("Extracted audio stream %d from %s -> %s", stream_index, source, dest_wav)
