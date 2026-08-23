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

import logging
import shutil
import sys
from pathlib import Path

from settings.config import get_config_dir

logger = logging.getLogger(__name__)

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
    directory if it isn't there yet (the expensive part -- embeddable
    Python + pip, done once). Returns the runtime python path. No-op
    (returns sys.executable) when not frozen.

    The lightweight worker script(s) (ml_worker.py) are re-synced from the
    template on every call, even when the heavy runtime already exists --
    an app update can ship a fixed/updated worker without requiring a full
    runtime re-bootstrap, so an existing install doesn't get stuck running
    a stale worker script forever.
    """
    if not is_frozen():
        return sys.executable

    managed_dir = _managed_runtime_dir()
    managed_python = managed_dir / "python.exe"
    template_dir = _bundled_runtime_template()

    if managed_python.exists():
        _sync_worker_scripts(template_dir, managed_dir)
        return str(managed_python)

    if not template_dir.exists():
        logger.error("Bundled runtime template not found at %s", template_dir)
        raise RuntimeSetupError(
            f"Bundled runtime template not found at {template_dir}. This build was not "
            "packaged correctly -- see packaging/build_runtime_template.py."
        )

    logger.info("Bootstrapping managed ML runtime: %s -> %s", template_dir, managed_dir)
    managed_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template_dir, managed_dir, dirs_exist_ok=True)

    if not managed_python.exists():
        logger.error("Runtime copy to %s did not produce python.exe", managed_dir)
        raise RuntimeSetupError(f"Runtime copy to {managed_dir} did not produce python.exe.")

    logger.info("Managed ML runtime ready at %s", managed_python)
    return str(managed_python)


def _sync_worker_scripts(template_dir: Path, managed_dir: Path) -> None:
    if not template_dir.exists():
        return
    for script in template_dir.glob("*.py"):
        dest = managed_dir / script.name
        try:
            if not dest.exists() or dest.read_bytes() != script.read_bytes():
                shutil.copy2(script, dest)
                logger.info("Synced updated worker script: %s", dest)
        except OSError as exc:
            logger.warning("Could not sync worker script %s: %s", script.name, exc)


__all__ = [
    "RuntimeSetupError",
    "ensure_runtime_ready",
    "get_ml_worker_script",
    "get_runtime_python",
    "is_frozen",
    "is_runtime_ready",
]
