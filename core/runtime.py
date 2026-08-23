"""Resolves which Python interpreter runs pip-installs and ML subprocess
calls (Whisper, Demucs).

In a dev/unfrozen run, that's simply the current interpreter (the venv
FoulPlay is running under) -- pip-installing into it and importing packages
from it are the same thing, which is how milestones 1-5 were built and
verified.

Once PyInstaller freezes the app, `sys.executable` is the frozen exe
itself: it has no `-m pip` and can't import arbitrary packages. So instead,
ML work runs against a separate, per-user "runtime" environment -- a small
bundled Windows-embeddable Python + pip, copied to %LOCALAPPDATA% on first
use, that heavy packages (torch/faster-whisper/demucs) get installed into
on demand. This keeps the installer itself small.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from settings.config import get_config_dir

RUNTIME_DIR_NAME = "runtime"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bundled_runtime_template() -> Path:
    """Location of the runtime template as bundled by PyInstaller (only
    meaningful when frozen; see packaging/foulplay.spec).
    """
    base = Path(getattr(sys, "_MEIPASS", "."))
    return base / "runtime_template"


def _managed_runtime_dir() -> Path:
    return get_config_dir() / RUNTIME_DIR_NAME


class RuntimeSetupError(RuntimeError):
    pass


def get_ml_worker_script() -> Path:
    """Path to core/ml_worker.py as an on-disk file the runtime interpreter
    can run directly (`<runtime_python> <script> ...`), never via package
    import -- the runtime interpreter (managed or dev venv) doesn't have
    the rest of this app's package structure importable.
    """
    if not is_frozen():
        return Path(__file__).resolve().parent / "ml_worker.py"
    return _managed_runtime_dir() / "ml_worker.py"


def get_runtime_python() -> str:
    """Returns the path/command to use for pip-installs and ML subprocess
    calls. Raises RuntimeSetupError if a frozen app's managed runtime
    hasn't been bootstrapped yet (see ensure_runtime_ready()).
    """
    if not is_frozen():
        return sys.executable

    managed_python = _managed_runtime_dir() / "python.exe"
    if not managed_python.exists():
        raise RuntimeSetupError(
            "The ML runtime hasn't been set up yet. Call ensure_runtime_ready() first."
        )
    return str(managed_python)


def is_runtime_ready() -> bool:
    if not is_frozen():
        return True
    return (_managed_runtime_dir() / "python.exe").exists()


def ensure_runtime_ready() -> str:
    """Copies the bundled runtime template to the per-user managed runtime
    directory if it isn't there yet. Returns the runtime python path.
    No-op (returns sys.executable) when not frozen.
    """
    if not is_frozen():
        return sys.executable

    managed_dir = _managed_runtime_dir()
    managed_python = managed_dir / "python.exe"
    if managed_python.exists():
        return str(managed_python)

    template_dir = _bundled_runtime_template()
    if not template_dir.exists():
        raise RuntimeSetupError(
            f"Bundled runtime template not found at {template_dir}. This build was not "
            "packaged correctly -- see packaging/build_runtime_template.py."
        )

    managed_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template_dir, managed_dir, dirs_exist_ok=True)

    if not managed_python.exists():
        raise RuntimeSetupError(f"Runtime copy to {managed_dir} did not produce python.exe.")

    return str(managed_python)


__all__ = [
    "RuntimeSetupError",
    "ensure_runtime_ready",
    "get_ml_worker_script",
    "get_runtime_python",
    "is_frozen",
    "is_runtime_ready",
]
