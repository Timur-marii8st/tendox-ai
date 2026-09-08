"""Запуск: uv run python -m procurement evaluate case.json --actor local-user."""

import sys

from procurement.cli import main

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

raise SystemExit(main())
