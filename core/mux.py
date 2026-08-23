"""Final MKV mux: original video/audio/subtitle streams preserved untouched
(stream-copied), plus the new cleaned audio track and the three generated
subtitle tracks (unedited / substituted / substitute-only), combined into a
single output file via ffmpeg.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from core.media import require_tool

logger = logging.getLogger(__name__)


def mux_final(
    source_video: Path,
    cleaned_audio_wav: Path,
    output_path: Path,
    original_audio_count: int,
    original_subtitle_count: int,
    unedited_subtitles_srt: Path,
    clean_subtitles_srt: Path,
    forced_subtitles_srt: Path,
) -> Path:
    ffmpeg = require_tool("ffmpeg")

    subtitle_inputs = [
        (unedited_subtitles_srt, "English (Unedited)", False),
        (clean_subtitles_srt, "English (Cleaned)", False),
        (forced_subtitles_srt, "English (Forced - Cleaned)", True),
    ]

    inputs = ["-i", str(source_video), "-i", str(cleaned_audio_wav)]
    maps = ["-map", "0", "-map", "1:a"]
    next_input_index = 2
    for srt_path, _title, _forced in subtitle_inputs:
        inputs += ["-i", str(srt_path)]
        maps += ["-map", str(next_input_index)]
        next_input_index += 1

    new_audio_index = original_audio_count  # 0-based index among *output* audio streams
    cmd = [ffmpeg, "-y", *inputs, *maps, "-c", "copy", f"-c:a:{new_audio_index}", "aac"]
    cmd += [
        f"-metadata:s:a:{new_audio_index}",
        "language=eng",
        f"-metadata:s:a:{new_audio_index}",
        "title=English (Cleaned)",
    ]

    sub_index = original_subtitle_count  # 0-based index among *output* subtitle streams
    for _srt_path, title, forced in subtitle_inputs:
        cmd += [f"-c:s:{sub_index}", "srt"]
        cmd += [
            f"-metadata:s:s:{sub_index}",
            "language=eng",
            f"-metadata:s:s:{sub_index}",
            f"title={title}",
        ]
        if forced:
            cmd += [f"-disposition:s:{sub_index}", "forced"]
        sub_index += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd += [str(output_path)]

    logger.info("Muxing final file: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg mux failed: %s\nstderr: %s", exc, exc.stderr)
        raise
    logger.info("Mux complete -> %s", output_path)
    return output_path
