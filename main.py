"""FoulPlay entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from core.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    setup_logging()
    logger.info("FoulPlay starting (argv=%s)", sys.argv)

    from app.main_window import MainWindow  # imported after logging is set up

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    logger.info("FoulPlay exiting with code %s", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
