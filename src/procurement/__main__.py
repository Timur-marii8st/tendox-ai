"""Запуск локальных CLI-команд Syurai Procurement."""

import sys
from typing import TextIO

from procurement.cli import main


def _configure_utf8(stream: TextIO) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


_configure_utf8(sys.stdout)
_configure_utf8(sys.stderr)

raise SystemExit(main())
