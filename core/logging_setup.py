"""App-wide logging setup.

Writes a detailed, rotating log file to %LOCALAPPDATA%\\FoulPlay\\logs so a
user can grab it (via the "Copy Log" button in the main window) and hand
it over when something goes wrong, without needing to reproduce the issue
live or dig through a terminal.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

from settings.config import get_config_dir

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3

_configured = False


def get_log_dir() -> Path:
    log_dir = get_config_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_log_file_path() -> Path:
    return get_log_dir() / "foulplay.log"


def setup_logging(level: int = logging.DEBUG) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        get_log_file_path(), maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if not getattr(sys, "frozen", False):
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    _install_excepthook()
    logging.getLogger(__name__).info("Logging initialized -> %s", get_log_file_path())


def _install_excepthook() -> None:
    logger = logging.getLogger("unhandled")

    def _excepthook(exc_type, exc_value, exc_tb):
        logger.critical(
            "Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook


def read_recent_log_text(max_bytes: int = 2_000_000) -> str:
    path = get_log_file_path()
    if not path.exists():
        return "(no log file yet)"
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="replace")
