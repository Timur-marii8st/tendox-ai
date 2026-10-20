"""Invalid scope/time must fail before opening a database transaction."""

from datetime import UTC, datetime

import pytest

from procurement.storage.eis_index_query import search_eis_index


@pytest.mark.parametrize(
    ("scope", "now"),
    [("ACTIVE", datetime(2026, 10, 4, tzinfo=UTC)), ("ALL_CACHED", datetime(2026, 10, 4))],
)
def test_invalid_scope_or_naive_clock_rejected_without_io(scope, now):
    class NoDatabase:
        def transaction(self, *args, **kwargs):
            pytest.fail("invalid request reached database")

    with pytest.raises(ValueError, match="INDEX_QUERY_INVALID"):
        search_eis_index(NoDatabase(), "tenant", "бумага", now=now, search_scope=scope)
