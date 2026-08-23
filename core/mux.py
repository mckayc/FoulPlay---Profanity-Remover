"""Final MKV mux: original video/audio/subtitle streams preserved untouched
(stream-copied), plus the new cleaned audio track and generated subtitle
track(s), combined into a single output file via ffmpeg.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.media import require_tool


def mux_final(
    source_video: Path,
    cleaned_audio_wav: Path,
    output_path: Path,
    original_audio_count: int,
    original_subtitle_count: int,
    clean_subtitles_srt: Path | None = None,
    forced_subtitles_srt: Path | None = None,
) -> Path:
    ffmpeg = require_tool("ffmpeg")

    inputs = ["-i", str(source_video), "-i", str(cleaned_audio_wav)]
    maps = ["-map", "0", "-map", "1:a"]
    next_input_index = 2

    if clean_subtitles_srt is not None:
        inputs += ["-i", str(clean_subtitles_srt)]
        maps += ["-map", str(next_input_index)]
        next_input_index += 1

    if forced_subtitles_srt is not None:
        inputs += ["-i", str(forced_subtitles_srt)]
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
    if clean_subtitles_srt is not None:
        cmd += [f"-c:s:{sub_index}", "srt"]
        cmd += [
            f"-metadata:s:s:{sub_index}",
            "language=eng",
            f"-metadata:s:s:{sub_index}",
            "title=English (Cleaned)",
        ]
        sub_index += 1

    if forced_subtitles_srt is not None:
        cmd += [f"-c:s:{sub_index}", "srt"]
        cmd += [
            f"-metadata:s:s:{sub_index}",
            "language=eng",
            f"-metadata:s:s:{sub_index}",
            "title=English (Forced - Cleaned)",
            f"-disposition:s:{sub_index}",
            "forced",
        ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd += [str(output_path)]

    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return output_path
