"""Version upgrades never relabel immutable three-engine evidence."""

import copy
import json
from pathlib import Path

import pytest

from procurement.sources.supplier_serp import HISTORICAL_EXPANDED_ENGINES, source_url
from procurement.storage.eis_supplier_serp import SavedSupplierSerp


def legacy():
    return json.loads(
        (Path(__file__).parent / "fixtures/eis-supplier-serp.json").read_text(encoding="utf-8")
    )


def current():
    payload = legacy()
    report = payload["report"]
    report["policy_version"] = "eis-position-supplier-serp-v2"
    old = {a["engine"]: a for a in report["batch"]["attempts"]}
    attempts = []
    for engine in HISTORICAL_EXPANDED_ENGINES:
        attempt = copy.deepcopy(old.get(engine.value, old["YANDEX"]))
        attempt["engine"] = engine.value
        attempt["source_url"] = source_url(engine, report["query"])
        attempts.append(attempt)
    report["batch"]["attempts"] = attempts
    report["attempted_source_requests"] = sum(a["browser_navigation_count"] for a in attempts)
    return payload


def test_legacy_and_current_replay_preserve_counts_and_policy():
    for payload, count in ((legacy(), 3), (current(), 6)):
        result = SavedSupplierSerp.model_validate(payload)
        assert len(result.report.batch.attempts) == count
        assert result.source_requests == 0
        assert result.model_dump(mode="json") == payload


@pytest.mark.parametrize("payload_factory", [legacy, current])
def test_policy_cannot_relabel_a_different_engine_set(payload_factory):
    payload = payload_factory()
    report = payload["report"]
    report["policy_version"] = (
        "eis-position-supplier-serp-v2"
        if report["policy_version"].endswith("v1")
        else "eis-position-supplier-serp-v1"
    )
    with pytest.raises(ValueError, match="POLICY_ENGINE_CONFLICT"):
        SavedSupplierSerp.model_validate(payload)


def test_legacy_bundle_cannot_use_expanded_current_limit():
    payload = legacy()
    payload["report"]["source_bundle_byte_count"] = 8388609
    with pytest.raises(ValueError, match="BUNDLE_LIMIT"):
        SavedSupplierSerp.model_validate(payload)
