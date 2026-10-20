"""Projection decisions, immutable replay and rollback without source or database I/O."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.sql.dml import Insert
from sqlalchemy.sql.elements import Null, TextClause

from procurement.sources.eis_notice_conflicts import diagnose_notice_conflicts
from procurement.sources.eis_notice_projection import prepare_notice_projection
from procurement.storage import eis_notice_projection as subject
from procurement.storage.eis_notice_variants import _facts, _origin
from test_eis_notice_conflicts import TOKEN, bundle, notice


class Result:
    def __init__(self, rows, column=None):
        self.rows, self.column = rows, column

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def one_or_none(self):
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        row = self.one_or_none()
        return row[self.column] if row is not None else None


class Storage:
    def __init__(self):
        self.tables = {}
        self.writes = 0
        self.fail_table = None
        self.locks = []

    @contextmanager
    def transaction(self, *args, **kwargs):
        before, writes = deepcopy(self.tables), self.writes
        try:
            yield self
        except Exception:
            self.tables, self.writes = before, writes
            raise

    def execute(self, statement, params=None):
        if isinstance(statement, TextClause):
            self.locks.append(params)
            return Result([])
        if isinstance(statement, Insert):
            name = statement.table.name
            if name == self.fail_table:
                raise ValueError("INJECTED_LATE_FAILURE")
            values = statement.compile().params
            for key, expression in statement._values.items():
                if isinstance(expression, Null):
                    values[str(key)] = None
            self.tables.setdefault(name, []).append(deepcopy(values))
            self.writes += 1
            return Result([])
        table = statement.get_final_froms()[0].name
        params = statement.compile().params
        rows = self.tables.get(table, [])
        for name, value in params.items():
            column = name.rsplit("_", 1)[0]
            rows = [row for row in rows if row.get(column) == value]
        return Result(deepcopy(rows), next(iter(statement.selected_columns)).name)


def setup(monkeypatch, *, divergent=False):
    archives = (bundle(("a.xml", notice())),)
    if divergent:
        archives += (bundle(("b.xml", notice(start="2026-10-01T10:01:27+03:00"))),)
    diagnosis = diagnose_notice_conflicts(archives, TOKEN)
    receipt = SimpleNamespace(
        receipt_id="receipt",
        receipt_sha256="c" * 64,
        window_key="getDocsIP/PRIZ/77/2026-10-02+03:00",
        response_sha256="a" * 64,
        prepared_response_sha256="b" * 64,
        observed_at=datetime(2026, 10, 4, tzinfo=UTC),
        evidence=SimpleNamespace(
            archive_urls=tuple(f"https://example.invalid/{i}" for i in range(len(archives)))
        ),
    )
    prepared = prepare_notice_projection(archives, diagnosis)
    history = {}
    for candidate in prepared.candidates:
        items = [
            item
            for item in diagnosis.occurrences
            if item.purchase_number == candidate.purchase_number
        ]
        history[candidate.purchase_number, candidate.version_number] = dict(
            variants=[_facts(item).model_dump(mode="json") for item in items],
            origins=[
                dict(company_id="tenant", **_origin("receipt", item).model_dump(mode="json"))
                for item in items
            ],
        )
    monkeypatch.setattr(subject, "_receipt_and_diagnosis", lambda *_: (receipt, diagnosis))
    monkeypatch.setattr(subject, "_global_history", lambda *_: history)
    monkeypatch.setattr(subject, "insert_search_keys", lambda *_: None)
    monkeypatch.setattr(subject, "_assert_complete_history", lambda *_: None)
    return archives, prepared, history


def project(storage, archives):
    return subject.project_retained_notice_variants(
        storage, "tenant", "receipt", archives, actor_id="operator"
    )


def test_full_transport_projected_and_exact_replay_zero_writes(monkeypatch):
    archives, _, history = setup(monkeypatch)
    storage = Storage()
    first = project(storage, archives)
    assert (first.projected_count, first.held_count, first.replayed) == (1, 0, False)
    assert storage.locks[:2] == [{"tenant": "tenant"}, {"key": "tenant/eis-notice-variants"}]
    assert storage.tables["eis_feed_windows"][0]["intake_kind"] == "VARIANT_TRANSPORT"
    assert storage.tables["eis_feed_archives"][0]["content"] == archives[0]
    assert storage.tables["eis_feed_archives"][0]["record_count"] == 1
    writes = storage.writes
    # Later history must not rewrite the frozen decision or audit.
    next(iter(history.values()))["variants"].append({"xml_sha256": "f" * 64})
    replay = project(storage, archives)
    assert replay.replayed and replay.projected_count == 1 and storage.writes == writes


def test_divergent_pair_has_hold_and_full_two_member_transport(monkeypatch):
    archives, _, _ = setup(monkeypatch, divergent=True)
    storage = Storage()
    report = project(storage, archives)
    assert report.held_count == 1 and report.projected_count == 0
    assert report.occurrence_count == 2 and report.pair_count == 1
    decision = storage.tables["eis_notice_projection_decisions"][0]
    assert decision["status"] == "HOLD" and decision["snapshot"] is None
    assert decision["snapshot_sha256"] is None
    assert len(storage.tables["eis_feed_archives"]) == 2
    assert not storage.tables.get("eis_notice_versions")
    assert project(storage, archives).replayed


@pytest.mark.parametrize("same_sha", [False, True])
def test_existing_canonical_never_overwritten(monkeypatch, same_sha):
    archives, prepared, _ = setup(monkeypatch)
    candidate = prepared.candidates[0]
    canonical = dict(
        company_id="tenant",
        purchase_number=candidate.purchase_number,
        version_number=candidate.version_number,
        document_type=candidate.document_type,
        xml_sha256=candidate.xml_sha256 if same_sha else "f" * 64,
        source_member="older.xml",
    )
    storage = Storage()
    canonical = {**subject._json(subject.asdict(candidate.snapshot)), **canonical}
    storage.tables["eis_notice_versions"] = [canonical.copy()]
    report = project(storage, archives)
    assert (report.replayed_count, report.held_count) == ((1, 0) if same_sha else (0, 1))
    assert storage.tables["eis_notice_versions"] == [canonical]


@pytest.mark.parametrize("tamper", ["decision", "audit", "transport", "canonical"])
def test_replay_checks_saved_evidence_without_writes(monkeypatch, tamper):
    archives, _, _ = setup(monkeypatch)
    storage = Storage()
    project(storage, archives)
    if tamper == "decision":
        storage.tables["eis_notice_projection_decisions"][0]["input_sha256"] = "e" * 64
    elif tamper == "audit":
        storage.tables["audit_events"][0]["basis"]["receipt_sha256"] = "e" * 64
    elif tamper == "transport":
        storage.tables["eis_feed_archives"][0]["content"] = b"changed"
    else:
        storage.tables["eis_notice_versions"][0]["xml_sha256"] = "e" * 64
    writes = storage.writes
    with pytest.raises(ValueError, match="NOTICE_PROJECTION_"):
        project(storage, archives)
    assert storage.writes == writes


def test_late_audit_failure_rolls_back_whole_projection(monkeypatch):
    archives, _, _ = setup(monkeypatch)
    storage = Storage()
    storage.fail_table = "audit_events"
    with pytest.raises(ValueError, match="INJECTED_LATE_FAILURE"):
        project(storage, archives)
    assert storage.tables == {} and storage.writes == 0


def test_wrong_archive_binding_cannot_start_write_transaction(monkeypatch):
    _archives, _, _ = setup(monkeypatch)
    storage = Storage()
    other = (bundle(("different.xml", notice())),)
    with pytest.raises(ValueError, match="DIAGNOSIS_BINDING_MISMATCH"):
        project(storage, other)
    assert not storage.locks and storage.writes == 0


def test_global_variant_and_orphan_origin_fail_closed(monkeypatch):
    _, prepared, history = setup(monkeypatch)
    candidate = prepared.candidates[0]
    original = next(iter(history.values()))
    different = deepcopy(original)
    for key in ("variants", "origins"):
        extra = dict(different[key][0], xml_sha256="e" * 64)
        different[key].append(extra)
    assert subject._decision(candidate, different, None, "a" * 64)["status"] == "HOLD"
    orphan = deepcopy(original)
    orphan["origins"] = []
    decision = subject._decision(candidate, orphan, None, "a" * 64)
    assert decision["reason"] == "VARIANT_ORIGIN_INTEGRITY_UNRESOLVED"
    assert decision["snapshot"] is None


def test_global_incomplete_receipt_rejects_before_any_write(monkeypatch):
    archives, _, _ = setup(monkeypatch)
    storage = Storage()

    def incomplete(*_):
        raise ValueError("NOTICE_PROJECTION_GLOBAL_RECEIPT_INCOMPLETE")

    monkeypatch.setattr(subject, "_assert_complete_history", incomplete)
    with pytest.raises(ValueError, match="GLOBAL_RECEIPT_INCOMPLETE"):
        project(storage, archives)
    assert storage.tables == {} and storage.writes == 0


def test_same_sha_canonical_content_drift_does_not_replay(monkeypatch):
    archives, _, _ = setup(monkeypatch)
    storage = Storage()
    project(storage, archives)
    storage.tables["eis_notice_versions"][0]["title"] = "Different parsed content"
    writes = storage.writes
    with pytest.raises(ValueError, match="CANONICAL_REPLAY_CONFLICT"):
        project(storage, archives)
    assert storage.writes == writes


def test_receipt_changed_between_parse_and_lock_cannot_write(monkeypatch):
    archives, _, _ = setup(monkeypatch)
    previous = subject._receipt_and_diagnosis
    count = 0

    def changing(*args):
        nonlocal count
        count += 1
        receipt, diagnosis = previous(*args)
        if count == 2:
            receipt = deepcopy(receipt)
            receipt.receipt_sha256 = "f" * 64
        return receipt, diagnosis

    monkeypatch.setattr(subject, "_receipt_and_diagnosis", changing)
    storage = Storage()
    with pytest.raises(ValueError, match="RECEIPT_CHANGED"):
        project(storage, archives)
    assert storage.tables == {} and storage.writes == 0


@pytest.mark.parametrize("title_bytes, accepted", [(1400000, True), (2 * 1024 * 1024, False)])
def test_individual_snapshot_two_mib_bound(monkeypatch, title_bytes, accepted):
    from dataclasses import replace

    _, prepared, history = setup(monkeypatch)
    candidate = prepared.candidates[0]
    candidate = replace(candidate, snapshot=replace(candidate.snapshot, title="x" * title_bytes))
    if accepted:
        decision = subject._decision(candidate, next(iter(history.values())), None, "a" * 64)
        assert decision["status"] == "PROJECTED"
    else:
        with pytest.raises(ValueError, match="NOTICE_PROJECTION_SNAPSHOT_LIMIT"):
            subject._decision(candidate, next(iter(history.values())), None, "a" * 64)


def test_snapshot_limit_matches_runtime_and_frozen_schema():
    from pathlib import Path

    from procurement.storage.models import eis_notice_projection_decisions

    assert subject.MAX_SNAPSHOT_BYTES == 2 * 1024 * 1024
    constraint = next(
        c
        for c in eis_notice_projection_decisions.constraints
        if c.name == "ck_eis_projection_decision_snapshot"
    )
    assert "octet_length(snapshot::text) <= 2097152" in str(constraint.sqltext)
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261004_03_eis_notice_projection.py"
    )
    assert "octet_length(snapshot::text) <= 2097152" in migration.read_text(encoding="utf-8")
    assert subject.MAX_BATCH_PAYLOAD_BYTES == 24 * 1024 * 1024
