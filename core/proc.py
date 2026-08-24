"""subprocess.run/Popen wrappers that suppress the console window Windows
otherwise flashes open for every spawned console-subsystem process (ffmpeg,
ffprobe, pip, winget, Demucs, powershell, ...) when the parent is a
windowed (no-console) app like this one. Use these instead of calling
subprocess directly anywhere in the app.
"""

from __future__ import annotations

import subprocess
import sys

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _no_window_kwargs(kwargs: dict) -> dict:
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", _CREATE_NO_WINDOW)
    return kwargs


def run(cmd, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **_no_window_kwargs(kwargs))


def popen(cmd, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(cmd, **_no_window_kwargs(kwargs))
