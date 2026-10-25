"""Restore the accepted production6 projection and observe deployed SQL search.

This one-corpus worker runs only on the private disposable replay network.
The existing Source10 decoder supplies inline/fragment rows; no capture occurs.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import signal
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine, text

ROOT = Path("/replay")
PACKAGE = Path("/package")
REPORT = Path("/report")
MANIFEST_SHA = "143e11fa6bf30626fee13c565a16a92229cb2c70c58b341d1cc5fc2204845f38"
PLAN_SHA = "b52ba50d9f0fd97e1eee6e3392c27c8aadb9f6fc5f033c736849777166414bdb"
CODEC_SHA = "aedfa38581670ab6d7bf7139315bdf13749dafce1f9d3b97b96dbae818745532"
SUITE_SHA = "ae2969110cf59b8bc980876a70e029db8eb0711b1e3e212eee3861485e173cb2"
ADMIN = "host=replay-pg dbname=eis_replay user=postgres"
APP = "postgresql+psycopg://procurement_app@replay-pg/eis_replay"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    assert len(data) <= 16_777_216
    with (REPORT / name).open("xb") as stream:
        stream.write(data)


def progress(stage, **values):
    print(json.dumps({"stage": stage, **values}), flush=True)


def json_text(value):
    # Preserve database JSON numbers as numbers; default=str would corrupt them.
    if isinstance(value, Decimal):
        assert value.is_finite()
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + ":" + json_text(v) for k, v in value.items()) + "}"
    if isinstance(value, (tuple, list)):
        return "[" + ",".join(json_text(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def rows(codec, spec, descriptor, plan):
    stats = {"rows": 0, "bytes": 0}
    inline = iter(codec._iter_verified_inline_rows(PACKAGE, spec, descriptor, plan, stats))
    fragments = {item.logical_ordinal: item for item in descriptor.fragmented_rows}
    deadline = codec._SqliteDeadlineV3(timeout_seconds=3600)
    whole = hashlib.sha256()
    previous = None
    for ordinal in range(descriptor.rows):
        if ordinal in fragments:
            line, key, row = codec._read_fragmented_row_v3(
                PACKAGE, spec, fragments[ordinal], plan, deadline
            )
        else:
            line, key, row = next(inline)
        token = codec._key_token(key)
        assert previous is None or token > previous
        previous = token
        assert row["company_id"] == plan.tenant
        whole.update(len(line).to_bytes(8, "big") + line)
        yield row
    assert next(inline, None) is None
    assert whole.hexdigest() == descriptor.ordered_rows_sha256
    assert stats["rows"] + len(fragments) == descriptor.rows


def restore(codec, plan, manifest):
    started = time.monotonic()
    with psycopg.connect(ADMIN, autocommit=True) as connection:
        runtime = {
            "server_version_num": connection.execute("SHOW server_version_num").fetchone()[0],
            "timezone": connection.execute("SHOW timezone").fetchone()[0],
        }
        collation, ctype = connection.execute(
            "SELECT datcollate,datctype FROM pg_database WHERE datname=current_database()"
        ).fetchone()
        runtime.update(database_collation=collation, database_ctype=ctype)
        assert all(value == getattr(manifest.runtime, key) for key, value in runtime.items())
        connection.execute("SET statement_timeout='900s'")
        connection.execute("SET lock_timeout='1s'")
        assert connection.execute("SELECT current_database()").fetchone()[0] == "eis_replay"
        assert (
            connection.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
            ).fetchone()[0]
            == 0
        )
        connection.execute("CREATE ROLE procurement_app LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT")
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute("ALTER ROLE procurement_app SET default_transaction_read_only=on")
        connection.execute("ALTER ROLE procurement_app SET statement_timeout='30s'")
        connection.execute("ALTER ROLE procurement_app SET lock_timeout='1s'")
        types = {
            "TEXT",
            "INTEGER",
            "JSONB",
            "NUMERIC",
            "TEXT[]",
            "TIMESTAMP WITH TIME ZONE",
            "VARCHAR(64)",
        }
        for spec in plan.relations:
            definitions = []
            for column in spec.columns:
                assert column.sql_type in types
                definitions.append(
                    sql.SQL("{} {} {}").format(
                        sql.Identifier(column.name),
                        sql.SQL(column.sql_type),
                        sql.SQL("" if column.nullable else "NOT NULL"),
                    )
                )
            definitions.append(
                sql.SQL("PRIMARY KEY ({})").format(
                    sql.SQL(",").join(map(sql.Identifier, spec.primary_key))
                )
            )
            connection.execute(
                sql.SQL("CREATE TABLE {} ({})").format(
                    sql.Identifier(spec.name), sql.SQL(",").join(definitions)
                )
            )
        descriptors = {item.name: item for item in manifest.relations}
        for spec in plan.relations:
            t0 = time.monotonic()
            with (
                connection.transaction(),
                connection.cursor().copy(
                    sql.SQL("COPY {} ({}) FROM STDIN").format(
                        sql.Identifier(spec.name),
                        sql.SQL(",").join(sql.Identifier(c.name) for c in spec.columns),
                    )
                ) as copy,
            ):
                count = 0
                for row in rows(codec, spec, descriptors[spec.name], plan):
                    copy.write_row(
                        [
                            Jsonb(row[c.name], dumps=json_text)
                            if c.kind == "JSON" and row[c.name] is not None
                            else row[c.name]
                            for c in spec.columns
                        ]
                    )
                    count += 1
            progress("RESTORED", relation=spec.name, rows=count, seconds=time.monotonic() - t0)
        for spec in plan.relations:
            for index in spec.indexes:
                assert index.predicate is None
                connection.execute(
                    sql.SQL("CREATE {} INDEX {} ON {} USING {} ({})").format(
                        sql.SQL("UNIQUE" if index.unique else ""),
                        sql.Identifier(index.name),
                        sql.Identifier(spec.name),
                        sql.SQL(index.method),
                        sql.SQL(",").join(map(sql.Identifier, index.columns)),
                    )
                )
        for spec in plan.relations:
            for number, foreign in enumerate(spec.foreign_keys):
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {} ADD CONSTRAINT {} FOREIGN KEY ({}) REFERENCES {} ({})"
                    ).format(
                        sql.Identifier(spec.name),
                        sql.Identifier(f"replay_fk_{spec.name}_{number}"),
                        sql.SQL(",").join(map(sql.Identifier, foreign.columns)),
                        sql.Identifier(foreign.target_relation),
                        sql.SQL(",").join(map(sql.Identifier, foreign.target_columns)),
                    )
                )
            connection.execute(
                sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                    sql.Identifier(spec.name)
                )
            )
            connection.execute(
                sql.SQL("ALTER TABLE {} FORCE ROW LEVEL SECURITY").format(sql.Identifier(spec.name))
            )
            connection.execute(
                sql.SQL(
                    "CREATE POLICY tenant ON {} "
                    "USING (company_id=current_setting('app.company_id',true))"
                ).format(sql.Identifier(spec.name))
            )
            connection.execute(
                sql.SQL("GRANT SELECT ON {} TO procurement_app").format(sql.Identifier(spec.name))
            )
            connection.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(spec.name)))
        schema = {}
        for spec in plan.relations:
            actual_columns = connection.execute(
                "SELECT a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull "
                "FROM pg_attribute a WHERE a.attrelid=%s::regclass "
                "AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum",
                (spec.name,),
            ).fetchall()
            normalized = [
                (n, t.upper().replace("CHARACTER VARYING", "VARCHAR"), not nonnull)
                for n, t, nonnull in actual_columns
            ]
            assert normalized == [(c.name, c.sql_type, c.nullable) for c in spec.columns]
            schema[spec.name] = actual_columns
        constraints = connection.execute(
            "SELECT count(*),bool_and(convalidated) FROM pg_constraint WHERE contype='f'"
        ).fetchone()
    return {
        "seconds": time.monotonic() - started,
        "foreign_keys": constraints[0],
        "foreign_keys_validated": constraints[1],
        "schema_columns_verified": schema,
        "database_runtime_parity": runtime,
        "projection_exceptions": {
            s.name: list(s.omitted_source_columns)
            for s in plan.relations
            if s.omitted_source_columns
        },
    }


def database_hashes(codec, plan, manifest, phase):
    started = time.monotonic()
    result = {}
    descriptors = {d.name: d for d in manifest.relations}
    with psycopg.connect(ADMIN, row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute("SET statement_timeout='900s'")
        for spec in plan.relations:
            columns = [
                sql.SQL("{}::text AS {}").format(sql.Identifier(c.name), sql.Identifier(c.name))
                if c.kind == "JSON"
                else sql.Identifier(c.name)
                for c in spec.columns
            ]
            kinds = {c.name: c.kind for c in spec.columns}
            order = [
                sql.SQL('{} COLLATE "C"').format(sql.Identifier(k))
                if kinds[k] == "TEXT"
                else sql.Identifier(k)
                for k in spec.primary_key
            ]
            whole = hashlib.sha256()
            count = 0
            with connection.cursor(name="readback_" + spec.name) as cursor:
                cursor.execute(
                    sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                        sql.SQL(",").join(columns),
                        sql.Identifier(spec.name),
                        sql.SQL(",").join(order),
                    )
                )
                while batch := cursor.fetchmany(1):
                    for row in batch:
                        for column in spec.columns:
                            if column.kind == "JSON" and row[column.name] is not None:
                                row[column.name] = json.loads(row[column.name], parse_float=Decimal)
                        line = codec.encode_row(spec, row)
                        whole.update(len(line).to_bytes(8, "big") + line)
                        count += 1
            expected = descriptors[spec.name]
            result[spec.name] = {"rows": count, "ordered_rows_sha256": whole.hexdigest()}
            assert count == expected.rows and whole.hexdigest() == expected.ordered_rows_sha256, (
                "READBACK_MISMATCH:" + spec.name
            )
            progress(phase, relation=spec.name, rows=count)
    return {"status": "PASS", "seconds": time.monotonic() - started, "relations": result}


def alarm(_signum, _frame):
    raise TimeoutError("SEARCH_WALL_TIMEOUT")


def search(suite, clock):
    from procurement.storage.eis_223_index import search_notice223_index
    from procurement.storage.eis_index_query import search_eis_index
    from procurement.storage.repository import PostgresStorage

    engine = create_engine(APP)
    storage = PostgresStorage(engine)
    with storage.transaction(suite["company_id"], consistent_read=True) as connection:
        isolation = dict(
            connection.execute(
                text(
                    "SELECT current_user, current_setting('transaction_read_only') AS read_only, "
                    "current_setting('row_security') AS row_security, "
                    "current_setting('transaction_isolation') AS isolation, "
                    "current_setting('statement_timeout') AS statement_timeout"
                )
            )
            .mappings()
            .one()
        )
        assert isolation["read_only"] == "on" and isolation["row_security"] == "on"
        role = dict(
            connection.execute(
                text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            .mappings()
            .one()
        )
        assert not role["rolsuper"] and not role["rolbypassrls"]
    with storage.transaction("foreign-replay-tenant", consistent_read=True) as connection:
        tables = (
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            )
            .scalars()
            .all()
        )
        foreign_rows = {
            name: connection.scalar(text(f'SELECT count(*) FROM "{name}"')) for name in tables
        }
        assert all(count == 0 for count in foreign_rows.values())
    refusals = []
    for default_readonly in (True, False):
        try:
            with engine.begin() as connection:
                if not default_readonly:
                    connection.execute(text("SET TRANSACTION READ WRITE"))
                connection.execute(text("UPDATE eis_notice_versions SET title=title WHERE false"))
        except Exception as error:
            code = getattr(getattr(error, "orig", error), "sqlstate", None)
            assert code in ({"25006", "42501"} if default_readonly else {"42501"})
            refusals.append(code)
        else:
            raise AssertionError("APP_WRITE_NOT_REFUSED")
    attempts, traversals = [], []
    signal.signal(signal.SIGALRM, alarm)
    for index, case in enumerate(suite["cases"]):
        for repeat in range(1, suite["repeats"] + 1):
            cursor, pages, traversal = None, 0, {"case_id": case["case_id"], "repeat": repeat}
            for page in range(1, suite["continuation_budget_per_traversal"] + 2):
                at = datetime.now(UTC).isoformat()
                started = time.perf_counter_ns()
                name = f"q{index + 1:02d}-r{repeat}-p{page:02d}.json"
                attempt = {
                    "case_id": case["case_id"],
                    "law": case["law"],
                    "query": case["query"],
                    "scope": case["deadline_mode"],
                    "repeat": repeat,
                    "page": page,
                    "started_at": at,
                    "cache_role": "FIRST_OBSERVED_AFTER_RESTORE_HASH_ANALYZE"
                    if repeat == 1 and page == 1
                    else "LATER_OBSERVED",
                    "cursor_in_sha256": hashlib.sha256(cursor.encode()).hexdigest()
                    if cursor
                    else None,
                }
                save(name.replace(".json", "-started.json"), attempt)
                try:
                    signal.setitimer(signal.ITIMER_REAL, suite["per_call_wall_seconds"])
                    if case["law"] == "44":
                        response = search_eis_index(
                            storage,
                            suite["company_id"],
                            case["query"],
                            now=clock,
                            limit=suite["page_size"],
                            search_scope=case["deadline_mode"],
                            paginate=True,
                            cursor=cursor,
                        )
                    else:
                        response = search_notice223_index(
                            storage,
                            suite["company_id"],
                            case["query"],
                            now=clock,
                            limit=suite["page_size"],
                            paginate=True,
                            cursor=cursor,
                        )
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    elapsed = str(Decimal(time.perf_counter_ns() - started) / Decimal(1_000_000))
                    payload = response.model_dump(mode="json")
                    save(name, payload)
                    cursor = response.next_cursor
                    ids = [
                        item.purchase_number if case["law"] == "44" else item.notice.purchase_number
                        for item in response.matched
                    ]
                    attempt.update(
                        status="SUCCEEDED",
                        duration_ms=elapsed,
                        result_file=name,
                        result_sha256=digest(REPORT / name),
                        returned=len(ids),
                        matched_count=response.matched_count,
                        ordered_ids=ids,
                        next_cursor_present=cursor is not None,
                    )
                    pages += 1
                except Exception as error:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    attempt.update(
                        status="TIMEOUT"
                        if isinstance(error, TimeoutError)
                        or getattr(getattr(error, "orig", error), "sqlstate", None) == "57014"
                        else "ERROR",
                        duration_ms=str(
                            Decimal(time.perf_counter_ns() - started) / Decimal(1_000_000)
                        ),
                        error_type=type(error).__name__,
                        sqlstate=getattr(getattr(error, "orig", error), "sqlstate", None),
                    )
                    cursor = None
                attempts.append(attempt)
                save(name.replace(".json", "-attempt.json"), attempt)
                progress(
                    "QUERY",
                    **{
                        k: attempt[k]
                        for k in ("case_id", "repeat", "page", "status", "duration_ms")
                    },
                )
                if attempt["status"] != "SUCCEEDED" or cursor is None:
                    break
            traversal.update(
                pages=pages,
                status="INCOMPLETE_ERROR"
                if attempt["status"] != "SUCCEEDED"
                else "INCOMPLETE_BUDGET"
                if cursor
                else "COMPLETE",
                terminal_cursor_present=cursor is not None,
            )
            traversals.append(traversal)
    engine.dispose()
    return {
        "boundary": "SQL_STORAGE",
        "attempts": attempts,
        "traversals": traversals,
        "app_isolation": isolation,
        "foreign_tenant_rows": foreign_rows,
        "app_role": role,
        "app_write_refusal_sqlstates": refusals,
        "precision": "UNKNOWN",
        "recall": "UNKNOWN",
        "quality_reason": "No independent ground-truth labels",
        "latency_limitations": "Copy environment; includes DB/fetch/comparison, excludes HTTP/UI; "
        "first observed is not machine cold",
    }


def main():
    started = time.monotonic()
    assert digest(PACKAGE / "manifest.json") == MANIFEST_SHA
    assert digest(PACKAGE / "plan.json") == PLAN_SHA
    assert digest(ROOT / "codec.py") == CODEC_SHA
    assert digest(ROOT / "suite.json") == SUITE_SHA
    assert sys.dont_write_bytecode and sys.pycache_prefix == "/tmp/replay-empty-pycache"
    assert not Path(sys.pycache_prefix).exists()
    spec = importlib.util.spec_from_file_location("production6_codec", ROOT / "codec.py")
    codec = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = codec
    spec.loader.exec_module(codec)
    plan, _ = codec.load_capture_plan(PACKAGE / "plan.json")
    manifest = codec.CaptureManifestV3.model_validate_json((PACKAGE / "manifest.json").read_bytes())
    suite = json.loads((ROOT / "suite.json").read_bytes())
    save(
        "schedule.json",
        {
            "planned_traversals": [
                {"case_id": case["case_id"], "repeat": repeat, "status": "NOT_ATTEMPTED"}
                for case in suite["cases"]
                for repeat in range(1, suite["repeats"] + 1)
            ]
        },
    )
    result = {
        "schema": "production6-isolated-replay-result-v1",
        "status": "INCOMPLETE",
        "manifest_sha256": MANIFEST_SHA,
        "suite_sha256": SUITE_SHA,
        "clock": manifest.clock.isoformat(),
    }
    try:
        result["restore"] = restore(codec, plan, manifest)
        save("restore.json", result["restore"])
        result["readback_before"] = database_hashes(codec, plan, manifest, "HASH_BEFORE")
        save("readback-before.json", result["readback_before"])
        result["search"] = search(suite, manifest.clock)
        expected_sources = json.loads((ROOT / "expected-source.json").read_bytes())
        loaded = {}
        for name, module in tuple(sys.modules.items()):
            if name == "procurement" or name.startswith("procurement."):
                path = Path(module.__file__)
                relative = path.relative_to(ROOT / "deployed-src").as_posix()
                assert path.suffix == ".py" and digest(path) == expected_sources[relative]["sha256"]
                loaded[name] = {"relative_path": relative, "sha256": digest(path)}
        result["loaded_deployed_modules"] = loaded
        assert not Path(sys.pycache_prefix).exists()
        save("search.json", result["search"])
        result["readback_after"] = database_hashes(codec, plan, manifest, "HASH_AFTER")
        save("readback-after.json", result["readback_after"])
        assert result["readback_before"]["relations"] == result["readback_after"]["relations"]
        result["status"] = "RESTORED_AND_SEARCH_OBSERVED"
    except Exception as error:
        result["error_type"] = type(error).__name__
        result["sqlstate"] = getattr(error, "sqlstate", None)
        result["diagnostic"] = (
            str(error)[:300]
            if isinstance(error, AssertionError)
            else "See phase and SQLSTATE; no credential-bearing exception text retained"
        )
        raise
    finally:
        result["elapsed_seconds"] = time.monotonic() - started
        save("result.json", result)
        progress("TERMINAL", status=result["status"], seconds=result["elapsed_seconds"])


if __name__ == "__main__":
    main()
