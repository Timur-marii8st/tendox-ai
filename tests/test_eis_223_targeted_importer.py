"""Cached-source proof failures must stop before database access; fixtures synthetic."""

import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from test_eis_223_archive import zip_bytes
from test_eis_223_index import URL
from test_eis_223_targeted_kesmbo import FAMILY, KEY, NUMBER, kesmbo_xml
from test_eis_feed import _IP_NS, _POLL, _REQ, _xml


@pytest.mark.parametrize(
    "case",
    [
        "accepted",
        "other_tenant",
        "xsd_false",
        "schema_changed",
        "record_changed",
        "hash_changed",
        "archive_missing",
    ],
)
def test_cached_targeted_intake_requires_complete_bound_proof_before_database(
    tmp_path, monkeypatch, case
):
    path = Path(__file__).parents[1] / "scripts/server-eis-223-import.py"
    spec = importlib.util.spec_from_file_location("targeted223_import_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "TARGETED_ROOT", tmp_path)
    root = tmp_path / "tenant-a" / FAMILY
    root.mkdir(parents=True)
    urls = [URL, URL.replace("A" * 32, "B" * 32)]
    assert urls[0] != urls[1]
    initial = _xml(
        "getDocsByReestrNumberResponse",
        "<dataInfo>"
        + "".join("<archiveUrl>" + url.replace("&", "&amp;") + "</archiveUrl>" for url in urls)
        + "</dataInfo>",
        namespace=_IP_NS,
    )
    prepared = _xml(
        "getPreparedPartResponse",
        f"<docRequestUid>{_REQ}</docRequestUid><dataInfo>"
        "<isPreparationCompleted>true</isPreparationCompleted>"
        + "".join(
            f"<preparedPartInfo><dsUid>{letter * 32}</dsUid>"
            f"<url>{url.replace('&', '&amp;')}</url></preparedPartInfo>"
            for letter, url in zip("AB", urls, strict=True)
        )
        + "</dataInfo>",
        ref=_POLL,
        namespace=_IP_NS,
    )
    selection = {
        "company_id": "tenant-a",
        "family": FAMILY,
        "purchase_number": NUMBER,
        "request_id": _REQ,
        "day": "2026-10-08",
        "offset": "+03:00",
    }
    proof = {
        "state": "XSD_VALIDATED",
        "company_id": "tenant-a",
        "family": FAMILY,
        "purchase_number": NUMBER,
        "request_id": _REQ,
        "response_sha256": hashlib.sha256(initial).hexdigest(),
        "prepared_sha256": hashlib.sha256(prepared).hexdigest(),
        "schemas": [
            {
                "version": "16.2",
                "purchase_xsd_sha256": (
                    "712e818f74bf3d38a03a3516533d0d4bf1df343f5a6e2056ae38a35f9ee7975b"
                ),
            },
            {
                "version": "16.3",
                "purchase_xsd_sha256": (
                    "c5ad9bec7a1d1ba393f818e48a6f066db0428ce939cf9f4066acfc23ac0f7411"
                ),
            },
        ],
        "archives": [],
    }
    for index in (1, 2):
        xml = kesmbo_xml().replace(
            b"<p:version>2</p:version>", f"<p:version>{index}</p:version>".encode()
        )
        assert xml.count(f"<p:version>{index}</p:version>".encode()) == 1
        member = f"synthetic-v{index}.xml"
        archive = zip_bytes([(member, xml)])
        if case != "archive_missing" or index != 2:
            (root / f"{_REQ}-{index}.zip").write_bytes(archive)
        proof["archives"].append(
            {
                "archive_sha256": hashlib.sha256(archive).hexdigest(),
                "records": [
                    {
                        "purchase_number": NUMBER,
                        "version_number": index,
                        "xml_sha256": hashlib.sha256(xml).hexdigest(),
                        "source_member": member,
                        "xsd_valid": True,
                    }
                ],
            }
        )
    if case == "other_tenant":
        selection["company_id"] = "tenant-b"
    elif case == "xsd_false":
        proof["archives"][0]["records"][0]["xsd_valid"] = False
    elif case == "schema_changed":
        proof["schemas"][0]["purchase_xsd_sha256"] = "0" * 64
    elif case == "record_changed":
        proof["archives"][0]["records"][0]["purchase_number"] = "32600000002"
    elif case == "hash_changed":
        proof["response_sha256"] = "0" * 64
    for suffix, raw in (
        ("initial.xml", initial),
        ("prepared-0.xml", prepared),
        ("selection.json", json.dumps(selection).encode()),
        ("proof.json", json.dumps(proof).encode()),
    ):
        (root / f"{_REQ}-{suffix}").write_bytes(raw)
    engine = MagicMock()
    create = MagicMock(return_value=engine)
    storage = object()
    monkeypatch.setenv("DATABASE_URL", "synthetic-no-network")
    monkeypatch.setattr(module, "create_engine", create)
    monkeypatch.setattr(module, "PostgresStorage", lambda actual: storage)

    def ingest(actual, company, window, *, actor_id):
        assert actual is storage and company == "tenant-a" and window.window_key == KEY
        assert actor_id == "223-targeted-operator" and len(window.archives) == 2
        return MagicMock(model_dump=lambda **kwargs: {"status": "IMPORTED"})

    admit = MagicMock(side_effect=ingest)
    monkeypatch.setattr(module, "ingest_notice223_window", admit)
    if case == "accepted":
        result = module.run_number("tenant-a", NUMBER, _REQ)
        assert result["source_calls"] == 0 and result["scheduled_daily_coverage"] == "UNKNOWN"
        admit.assert_called_once()
        engine.dispose.assert_called_once()
    else:
        expected = FileNotFoundError if case == "archive_missing" else ValueError
        reason = (
            None
            if case == "archive_missing"
            else (
                "CACHED_SELECTION_MISMATCH"
                if case == "other_tenant"
                else "SOURCE_XSD_PROOF_BINDING_INVALID"
            )
        )
        with pytest.raises(expected, match=reason):
            module.run_number("tenant-a", NUMBER, _REQ)
        create.assert_not_called()
        admit.assert_not_called()
