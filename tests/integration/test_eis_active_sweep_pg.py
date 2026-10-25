"""Batch presence preserves version/projection semantics and tenant isolation."""

from uuid import uuid4

from sqlalchemy import event
from test_eis_223_index_pg import storage as storage

from procurement.storage import eis_notice_index
from procurement.storage.eis_notice_index import bind_ready_window, ingest_ready_window
from test_eis_active_sweep import h
from test_eis_public_candidate_recovery import _responses, _zip


def test_batch_presence_uses_one_select_and_does_not_leak_other_tenant(storage, monkeypatch):
    company = "sweep-presence-" + uuid4().hex
    monkeypatch.setattr(h, "COMPANY", company)
    numbers = ("0122100003226000971", "0122100003226000972", "0122100003226000973")
    initial, prepared = _responses()
    for tenant, number in ((company, numbers[0]), (company + "-foreign", numbers[1])):
        ingest_ready_window(
            storage,
            tenant,
            bind_ready_window(
                "getDocsIP/PRIZ/50/2026-09-25/17+03:00",
                initial,
                prepared,
                {initial.archive_urls[0]: _zip(number)},
            ),
            actor_id="synthetic",
        )
    calls = []

    def track(conn, cursor, statement, params, context, executemany):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "eis_notice_search_keys" in statement
        ):
            calls.append(statement)

    engine = storage._engine
    event.listen(engine, "before_cursor_execute", track)
    try:
        assert h.read_present(storage, numbers) == frozenset({numbers[0]})
        assert len(calls) == 1
    finally:
        event.remove(engine, "before_cursor_execute", track)
    # Model an interrupted projection without mutating append-only evidence.
    with monkeypatch.context() as patch:
        patch.setattr(eis_notice_index, "insert_search_keys", lambda *args, **kwargs: None)
        ingest_ready_window(
            storage,
            company,
            bind_ready_window(
                "getDocsIP/PRIZ/50/2026-09-25/18+03:00",
                initial,
                prepared,
                {initial.archive_urls[0]: _zip(numbers[2])},
            ),
            actor_id="synthetic",
        )
    assert h.read_present(storage, (numbers[2],)) == frozenset()
    assert h.read_present(storage, numbers) == frozenset({numbers[0]})
