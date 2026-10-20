"""Hydration cursor stays bounded and closes even if its consumer fails."""

import pytest

from procurement.storage.eis_index_query import _stream_notice_rows


@pytest.mark.parametrize("failure", [None, "SNAPSHOT_INVALID", "EVENT_READ_FAILED"])
def test_stream_is_statement_local_bounded_and_closed(failure):
    trace = []
    statement = object()

    class Cursor:
        def mappings(self):
            return self

        def partitions(self, size):
            assert size == 2
            trace.append("first")
            yield [{"number": 1}, {"number": 2}]
            trace.append("second")
            yield [{"number": 3}]

        def close(self):
            trace.append("close")

    class Connection:
        def execute(self, stmt, *, execution_options):
            assert stmt is statement
            assert execution_options == {"yield_per": 2}
            trace.append("execute")
            return Cursor()

    def consume():
        with _stream_notice_rows(Connection(), statement, 2) as batches:
            for batch in batches:
                assert len(batch) <= 2
                trace.append("event_query")
                if failure:
                    raise ValueError(failure)

    if failure:
        with pytest.raises(ValueError, match=failure):
            consume()
        assert trace == ["execute", "first", "event_query", "close"]
    else:
        consume()
        assert trace == ["execute", "first", "event_query", "second", "event_query", "close"]
