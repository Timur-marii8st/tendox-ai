"""Read-only pilot benchmark: local API latency and bounded public-page evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import TypeAdapter
from sqlalchemy import create_engine, exists, select

from procurement.sources.eis_index_search import search_query_keys_v1
from procurement.sources.eis_public import search_public_eis
from procurement.sources.eis_search_benchmark import (
    BenchmarkItem,
    BenchmarkLabel,
    BenchmarkObservation,
    BenchmarkSuite,
    EvidenceRef,
    ReferenceCorpusEntry,
    ReferenceMembership,
    latency_summary,
    quality_summary,
    source_age_seconds,
    source_overlap,
)
from procurement.storage.eis_index_query import EisIndexedSearchResult
from procurement.storage.models import eis_notice_versions
from procurement.storage.repository import PostgresStorage

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def _token(path: Path) -> str:
    value = os.environ.get("EIS_PILOT_TOKEN")
    if value:
        return value
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("EIS_PILOT_TOKEN="):
            return line.partition("=")[2].strip().strip("\"'")
    raise ValueError("PILOT_TOKEN_UNAVAILABLE")


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _evidence(path: Path, root: Path, locator: str) -> EvidenceRef:
    return EvidenceRef(
        path=path.relative_to(root).as_posix(), sha256=_digest(path.read_bytes()), locator=locator
    )


def _safe_error(error: Exception) -> str:
    # Request/validation exception strings may contain headers, bodies or local paths.
    return type(error).__name__


def report(root: Path, labels_path: Path | None = None) -> None:
    meta = json.loads((root / "run.json").read_text(encoding="utf-8"))
    suite = BenchmarkSuite.model_validate_json((root / "suite.json").read_bytes())
    observations = TypeAdapter(list[BenchmarkObservation]).validate_json(
        (root / "observations.json").read_bytes()
    )
    labels = (
        TypeAdapter(list[BenchmarkLabel]).validate_json(labels_path.read_bytes())
        if labels_path
        else []
    )
    membership_path = root / "reference-membership.json"
    membership = (
        ReferenceMembership.model_validate_json(membership_path.read_bytes())
        if membership_path.exists()
        else None
    )
    if membership and (membership.company_id, membership.run_id) != (
        meta["company_id"],
        meta["run_id"],
    ):
        raise ValueError("MEMBERSHIP_TENANT_MISMATCH")
    for observation in observations:
        if (observation.company_id, observation.run_id) != (meta["company_id"], meta["run_id"]):
            raise ValueError("OBSERVATION_TENANT_MISMATCH")
        if observation.evidence:
            _verify_evidence(root, observation.evidence)
    for label in labels:
        _verify_evidence(root, label.evidence)
    cases: list[dict[str, object]] = []
    templates: list[dict[str, object]] = []
    markdown = [
        "# Бенчмарк поиска ЕИС",
        "",
        f"Run: `{meta['run_id']}`; tenant: `{meta['company_id']}`.",
        "",
        "Локальный индекс и ЕИС имеют разные scope. "
        "Пересечение номеров не является recall всей ЕИС.",
        "Quality без REVIEWED evidence-bound разметки — UNKNOWN. Допуск и прибыль не оценивались.",
        "p50/p95: nearest rank по успешным запросам, без ожидания cooldown; "
        "ошибки показаны отдельно.",
        "Возраст source watermark не доказывает свежесть корпуса; "
        "ingest watermark не заменяет source.",
        "",
        "| Запрос | API успех/всего | API p50 / p95 мс | FAIL в top-10 | "
        "ЕИС уникальных raw | Пересечение с API top-100 | Precision@10 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for query in suite.queries:
        local = [
            item
            for item in observations
            if item.query_id == query.id and item.source == "LOCAL_INDEX"
        ]
        public = [
            item
            for item in observations
            if item.query_id == query.id and item.source == "EIS_PUBLIC"
        ]
        valid_local = [item for item in local if item.status == "SUCCEEDED"]
        last = valid_local[-1] if valid_local else None
        quality = quality_summary(last, labels).model_dump(mode="json") if last else None
        raw_ids = {
            number for item in public if item.status == "SUCCEEDED" for number in item.raw_numbers
        }
        page_sets = [set(item.raw_numbers) for item in public if item.status == "SUCCEEDED"]
        repeated = sum(
            bool(ids) and ids in page_sets[:index] for index, ids in enumerate(page_sets)
        )
        overlap = None
        if last and any(item.status == "SUCCEEDED" for item in public):
            reference = next(item for item in public if item.status == "SUCCEEDED").model_copy(
                update={
                    "raw_numbers": tuple(sorted(raw_ids)),
                    "evidence": _evidence(
                        root / "observations.json", root, f"EIS_PUBLIC query_id={query.id}"
                    ),
                }
            )
            overlap = source_overlap(reference, last).model_dump(mode="json")
        latency = latency_summary(local)
        failed_top = (
            sum(item.application_status == "FAIL" for item in last.items[:10]) if last else None
        )
        case: dict[str, object] = {
            "query_id": query.id,
            "query": query.query,
            "intent": query.intent,
            "local_latency": latency.model_dump(mode="json"),
            "public_latency": latency_summary(public).model_dump(mode="json"),
            "quality": quality,
            "source_overlap": overlap,
            "public_unique_raw_count": len(raw_ids),
            "public_repeated_page_count": repeated,
            "public_identifier_completeness": "KNOWN_CHECKED_PAGES"
            if public
            and all(item.status == "SUCCEEDED" and item.unidentified_count == 0 for item in public)
            else "UNKNOWN",
            "failed_in_local_top10": failed_top,
            "source_watermark_age_seconds": last.source_watermark_age_seconds if last else None,
            "ingestion_watermark_age_seconds": last.ingestion_watermark_age_seconds
            if last
            else None,
            "indexed_current_notices": last.indexed_current_notices if last else None,
            "matched_count": last.matched_count if last else None,
            "effective_query_keys": last.effective_query_keys if last else None,
            "local_reference_present_count": len(
                raw_ids & {entry.purchase_number for entry in membership.entries}
            )
            if membership and raw_ids and raw_ids.issubset(set(membership.requested_numbers))
            else None,
            "reference_membership_observed_at": membership.observed_at.isoformat()
            if membership
            else None,
        }
        cases.append(case)
        precision = quality["precision_at_k"] if quality else None
        markdown.append(
            f"| {query.query} | {latency.success_count}/{latency.sample_count} | "
            f"{latency.success_p50_ms} / {latency.success_p95_ms} | {failed_top} | "
            f"{len(raw_ids) if public else 'не проверено'} | "
            f"{overlap['shared_count'] if overlap else 'не проверено'} | "
            f"{precision if precision is not None else 'UNKNOWN'} |"
        )
        if last and last.evidence:
            for index, item in enumerate(last.items[:10]):
                templates.append(
                    BenchmarkLabel(
                        company_id=last.company_id,
                        query_id=query.id,
                        purchase_number=item.purchase_number,
                        source_sha256=item.source_sha256,
                        verdict="UNKNOWN",
                        review_status="PROVISIONAL",
                        reviewer="awaiting-review",
                        reason=f"Проверить intent: {query.intent}; title: {item.title}",
                        evidence=last.evidence.model_copy(update={"locator": f"matched[{index}]"}),
                    ).model_dump(mode="json")
                )
    summary = {
        **meta,
        "cases": cases,
        "local_latency": latency_summary(
            [item for item in observations if item.source == "LOCAL_INDEX"]
        ).model_dump(mode="json"),
        "source_freshness": "UNKNOWN",
        "corpus_coverage": "UNKNOWN",
        "full_corpus_recall": None,
        "reviewed_label_count": sum(label.review_status == "REVIEWED" for label in labels),
        "labels_sha256": _digest(labels_path.read_bytes()) if labels_path else None,
        "reviewed_labels": [
            label.model_dump(mode="json") for label in labels if label.review_status == "REVIEWED"
        ],
        "observations_sha256": _digest((root / "observations.json").read_bytes()),
        "membership_evidence": _evidence(membership_path, root, "entries").model_dump(mode="json")
        if membership
        else None,
    }
    (root / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    template_path = root / "labels-template.json"
    if not template_path.exists():
        template_path.write_text(
            json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "report": str(root / "report.md"),
                "cases": len(cases),
                "local_latency": summary["local_latency"],
                "reviewed_labels": summary["reviewed_label_count"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def _verify_evidence(root: Path, evidence: EvidenceRef) -> None:
    path = (root / evidence.path).resolve()
    if (
        not path.is_relative_to(root.resolve())
        or not path.is_file()
        or _digest(path.read_bytes()) != evidence.sha256
    ):
        raise ValueError("BENCHMARK_EVIDENCE_MISMATCH")


def collect_membership(root: Path) -> None:
    """Read exact current-known versions for captured public IDs; no source download."""
    meta = json.loads((root / "run.json").read_text(encoding="utf-8"))
    if meta["company_id"] != "local-eis-supplier":
        raise ValueError("MEMBERSHIP_TENANT_MISMATCH")
    target = root / "reference-membership.json"
    if target.exists():
        raise ValueError("MEMBERSHIP_ALREADY_CAPTURED")
    observations = TypeAdapter(list[BenchmarkObservation]).validate_json(
        (root / "observations.json").read_bytes()
    )
    for observation in observations:
        if (observation.company_id, observation.run_id) != (meta["company_id"], meta["run_id"]):
            raise ValueError("OBSERVATION_TENANT_MISMATCH")
        if observation.evidence:
            _verify_evidence(root, observation.evidence)
    numbers = sorted(
        {
            number
            for item in observations
            if item.source == "EIS_PUBLIC" and item.status == "SUCCEEDED"
            for number in item.raw_numbers
        }
    )
    if not numbers or len(numbers) > 800:
        raise ValueError("MEMBERSHIP_REFERENCE_SIZE_INVALID")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    storage = PostgresStorage(engine)
    newer = eis_notice_versions.alias("newer")
    columns = (
        "purchase_number",
        "version_number",
        "document_type",
        "title",
        "xml_sha256",
        "source_member",
        "published_at",
        "deadline",
    )
    try:
        with storage.transaction(meta["company_id"], consistent_read=True) as connection:
            rows = (
                connection.execute(
                    select(*(eis_notice_versions.c[key] for key in columns)).where(
                        eis_notice_versions.c.company_id == meta["company_id"],
                        eis_notice_versions.c.purchase_number.in_(numbers),
                        ~exists(
                            select(newer.c.purchase_number).where(
                                newer.c.company_id == eis_notice_versions.c.company_id,
                                newer.c.purchase_number == eis_notice_versions.c.purchase_number,
                                newer.c.version_number > eis_notice_versions.c.version_number,
                            )
                        ),
                    )
                )
                .mappings()
                .all()
            )
            result = ReferenceMembership(
                company_id=meta["company_id"],
                run_id=meta["run_id"],
                observed_at=datetime.now(UTC),
                requested_numbers=tuple(numbers),
                entries=tuple(ReferenceCorpusEntry.model_validate(dict(row)) for row in rows),
            )
        target.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "reference_numbers": len(numbers),
                    "present_in_current_known_index": len(rows),
                    "coverage": "UNKNOWN",
                }
            ),
            flush=True,
        )
    finally:
        engine.dispose()
    report(root)


def run(
    suite_path: Path,
    output: Path,
    api_url: str,
    token_file: Path,
    repeats: int,
    public_enabled: bool,
) -> None:
    # Credentials are only sent inside the private deployment, never to arbitrary upstreams.
    parsed = urlsplit(api_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"api", "127.0.0.1"}
        or parsed.username
        or parsed.password
    ):
        raise ValueError("BENCHMARK_API_URL_INVALID")
    if not 3 <= repeats <= 10:
        raise ValueError("BENCHMARK_REPEAT_COUNT_INVALID")
    suite = BenchmarkSuite.model_validate_json(suite_path.read_bytes())
    if len({item.id for item in suite.queries}) != len(suite.queries):
        raise ValueError("BENCHMARK_QUERY_IDS_NOT_UNIQUE")
    root = output / "local-eis-supplier" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    root.mkdir(parents=True, exist_ok=False)
    meta = {
        "company_id": "local-eis-supplier",
        "run_id": root.name,
        "started_at": datetime.now(UTC).isoformat(),
        "suite_sha256": _digest(suite_path.read_bytes()),
        "repeats": repeats,
        "public_enabled": public_enabled,
        "api_url": api_url,
        "provider_status": "NOT_TESTED",
        "python_version": platform.python_version(),
        "runner_sha256": _digest(Path(__file__).read_bytes()),
        "engine_code_sha256": {
            name: _digest(
                (Path(__file__).resolve().parents[1] / "src" / "procurement" / path).read_bytes()
            )
            for name, path in {
                "index_search": "sources/eis_index_search.py",
                "index_query": "storage/eis_index_query.py",
                "public_parser": "sources/eis_public.py",
                "benchmark_metrics": "sources/eis_search_benchmark.py",
            }.items()
        },
    }
    (root / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (root / "runner.py").write_bytes(Path(__file__).read_bytes())
    for name, code_relpath in {
        "index_search": "sources/eis_index_search.py",
        "index_query": "storage/eis_index_query.py",
        "public_parser": "sources/eis_public.py",
        "benchmark_metrics": "sources/eis_search_benchmark.py",
    }.items():
        (root / f"code-{name}.py").write_bytes(
            (
                Path(__file__).resolve().parents[1] / "src" / "procurement" / code_relpath
            ).read_bytes()
        )
    (root / "suite.json").write_bytes(suite_path.read_bytes())
    observations: list[BenchmarkObservation] = []

    def save(observation: BenchmarkObservation) -> None:
        observations.append(observation)
        (root / "observations.json").write_text(
            TypeAdapter(list[BenchmarkObservation]).dump_json(observations, indent=2).decode(),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "query_id": observation.query_id,
                    "source": observation.source,
                    "status": observation.status,
                    "page": observation.page_number,
                    "ms": str(observation.duration_ms),
                    "raw_ids": len(set(observation.raw_numbers)),
                    "error": observation.error_code,
                }
            ),
            flush=True,
        )

    print(json.dumps({"evidence_directory": str(root)}), flush=True)
    with httpx.Client(
        timeout=30,
        follow_redirects=False,
        headers={"Authorization": f"Bearer {_token(token_file)}"},
    ) as client:
        for query in suite.queries:
            for sample in range(repeats):
                path = root / f"{query.id}-api-{sample + 1}.json"
                request_url = str(
                    httpx.URL(api_url + "/v1/tender-discovery/eis-index").copy_add_param(
                        "query", query.query
                    )
                )
                started = time.perf_counter_ns()
                try:
                    with client.stream(
                        "GET",
                        api_url + "/v1/tender-discovery/eis-index",
                        params={"query": query.query},
                    ) as response:
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_RESPONSE_BYTES:
                                raise ValueError("RESPONSE_TOO_LARGE")
                        path.write_bytes(body)
                        response.raise_for_status()
                        result = EisIndexedSearchResult.model_validate_json(body)
                    observed = datetime.now(UTC)
                    save(
                        BenchmarkObservation(
                            **{key: meta[key] for key in ("company_id", "run_id")},
                            query_id=query.id,
                            query=query.query,
                            effective_query_keys=search_query_keys_v1(query.query),
                            source="LOCAL_INDEX",
                            observed_at=observed,
                            status="SUCCEEDED",
                            http_status=response.status_code,
                            request_url=request_url,
                            duration_ms=Decimal(time.perf_counter_ns() - started) / 1_000_000,
                            evidence=_evidence(path, root, "matched"),
                            response_bytes=len(body),
                            raw_numbers=tuple(item.purchase_number for item in result.matched),
                            items=tuple(
                                BenchmarkItem(
                                    purchase_number=item.purchase_number,
                                    title=item.title,
                                    source_sha256=item.xml_sha256,
                                    application_status=item.application_status,
                                )
                                for item in result.matched
                            ),
                            indexed_current_notices=result.inspected_current_notices,
                            evaluated_candidate_notices=result.evaluated_candidate_notices,
                            matched_count=result.matched_count,
                            search_elapsed_ms=result.search_elapsed_ms,
                            source_watermark_age_seconds=source_age_seconds(
                                result.latest_source_publication, observed
                            ),
                            ingestion_watermark_age_seconds=source_age_seconds(
                                result.latest_ingested_at, observed
                            ),
                        )
                    )
                except (httpx.HTTPError, ValueError) as error:
                    code = (
                        error.response.status_code
                        if isinstance(error, httpx.HTTPStatusError)
                        else None
                    )
                    save(
                        BenchmarkObservation(
                            **{key: meta[key] for key in ("company_id", "run_id")},
                            query_id=query.id,
                            query=query.query,
                            effective_query_keys=search_query_keys_v1(query.query),
                            source="LOCAL_INDEX",
                            observed_at=datetime.now(UTC),
                            status="RATE_LIMITED" if code == 429 else "FAILED",
                            duration_ms=Decimal(time.perf_counter_ns() - started) / 1_000_000,
                            http_status=code,
                            request_url=request_url,
                            error_code=_safe_error(error),
                            evidence=_evidence(path, root, "response") if path.exists() else None,
                            response_bytes=path.stat().st_size if path.exists() else 0,
                        )
                    )
                    if code in {401, 403, 429} or isinstance(error, httpx.TimeoutException):
                        report(root)
                        return
    if public_enabled:
        blocked = False
        for query in suite.queries:
            prior_ids: set[str] = set()
            for page in query.public_pages:
                path = root / f"{query.id}-public-{page}.html"

                def save_raw(content: bytes, target: Path = path) -> None:
                    target.write_bytes(content)

                wait_started = time.perf_counter_ns()
                for _attempt in range(6):
                    started = time.perf_counter_ns()
                    public = search_public_eis(query.query, page_number=page, raw_observer=save_raw)
                    if public.status != "COOLDOWN":
                        break
                    delay = (
                        max(1.0, (public.retry_at - datetime.now(UTC)).total_seconds())
                        if public.retry_at
                        else 60.0
                    )
                    remaining = min(delay + 0.2, 61.0)
                    print(
                        json.dumps(
                            {
                                "query_id": query.id,
                                "status": "COOLDOWN",
                                "wait_seconds": round(remaining, 1),
                            }
                        ),
                        flush=True,
                    )
                    while remaining > 0:
                        step = min(15.0, remaining)
                        time.sleep(step)
                        remaining -= step
                status: Literal["SUCCEEDED", "FAILED", "RATE_LIMITED", "BLOCKED", "COOLDOWN"] = (
                    "SUCCEEDED"
                    if public.status == "COMPLETED"
                    else "RATE_LIMITED"
                    if public.status == "RATE_LIMITED"
                    else "BLOCKED"
                    if public.status == "BLOCKED"
                    else "COOLDOWN"
                    if public.status == "COOLDOWN"
                    else "FAILED"
                )
                duration = Decimal(time.perf_counter_ns() - started) / 1_000_000
                save(
                    BenchmarkObservation(
                        **{key: meta[key] for key in ("company_id", "run_id")},
                        query_id=query.id,
                        query=query.query,
                        source="EIS_PUBLIC",
                        observed_at=public.observed_at,
                        status=status,
                        error_code=public.reason,
                        request_url=public.search_url,
                        duration_ms=duration,
                        wait_ms=max(Decimal(0), Decimal(started - wait_started) / 1_000_000),
                        evidence=_evidence(path, root, "search-result-cards")
                        if path.exists()
                        else None,
                        response_bytes=path.stat().st_size if path.exists() else 0,
                        raw_numbers=public.purchase_numbers or (),
                        scanned_count=public.scanned_count,
                        unparsed_count=public.unparsed_count,
                        unidentified_count=public.unidentified_count,
                        page_number=page,
                        items=tuple(
                            BenchmarkItem(
                                purchase_number=item.purchase_number,
                                title=item.subject,
                                source_sha256=item.source_sha256,
                                application_status=item.application_status,
                            )
                            for item in public.leads
                        ),
                    )
                )
                ids = set(public.purchase_numbers or ())
                if (
                    public.status != "COMPLETED"
                    or public.unidentified_count != 0
                    or (page > 1 and not ids - prior_ids)
                ):
                    blocked = public.status in {"BLOCKED", "RATE_LIMITED"}
                    break
                prior_ids |= ids
            if blocked:
                break
    report(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite", type=Path, default=Path("scripts/benchmarks/eis-query-suite.v1.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("/var/lib/eis-browser/research/search-benchmark")
    )
    parser.add_argument("--api-url", default="http://api:8000")
    parser.add_argument("--token-file", type=Path, default=Path("/run/benchmark.env"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--report-only", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--membership-only", type=Path)
    args = parser.parse_args()
    if args.membership_only:
        collect_membership(args.membership_only)
    elif args.report_only:
        report(args.report_only, args.labels)
    else:
        run(args.suite, args.output, args.api_url, args.token_file, args.repeats, args.public)
