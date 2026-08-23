"""Auto-installs FFmpeg via winget when it's missing, instead of bundling a
static binary in the installer (keeps the installer smaller) or requiring
a manual install step (keeps the app self-serve).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

WINGET_PACKAGE_ID = "Gyan.FFmpeg"

MANUAL_INSTALL_HINT = (
    "FFmpeg was not found and winget is unavailable on this system. Install FFmpeg "
    "manually (e.g. download from https://www.gyan.dev/ffmpeg/builds/ and add it to "
    "your PATH), then restart FoulPlay."
)


def is_winget_available() -> bool:
    return shutil.which("winget") is not None


class FfmpegInstallError(RuntimeError):
    pass


def install_ffmpeg_via_winget(on_output: Callable[[str], None] | None = None) -> None:
    if not is_winget_available():
        raise FfmpegInstallError(MANUAL_INSTALL_HINT)

    cmd = [
        "winget",
        "install",
        "--id",
        WINGET_PACKAGE_ID,
        "-e",
        "--source",
        "winget",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert process.stdout is not None
    for line in process.stdout:
        if on_output:
            on_output(line.rstrip())
    process.wait()

    if process.returncode != 0:
        raise FfmpegInstallError(f"winget install failed (exit code {process.returncode}).")
