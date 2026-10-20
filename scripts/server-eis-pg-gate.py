"""Запустить PostgreSQL gate только в отдельной заранее созданной тестовой БД."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.engine import make_url

TEST_DATABASE = "procurement_eis_test_20260928"


def main() -> int:
    for name in ("DATABASE_URL", "DATABASE_ADMIN_URL"):
        url = make_url(os.environ[name]).set(database=TEST_DATABASE)
        os.environ[name] = url.render_as_string(hide_password=False)
    return pytest.main(
        [
            "-q",
            "--tb=no",
            "/app/tests/integration/test_eis_notice_index_pg.py",
            "/app/tests/integration/test_eis_document_queue_pg.py",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
