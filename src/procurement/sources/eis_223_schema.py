"""Offline full-XSD evidence, separate from metadata extraction and eligibility."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from lxml import etree as E  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.sources.eis_223_archive import Eis223NoticeSnapshot, parse_notice223_xml

# S149 official packages; S155 fingerprints of their complete extracted local trees.
SCHEMAS = {
    "16.2": (
        "b7fc0e8ab81fde9e05e43fc8a83d675f7c49514c4548294cafc7d50cc0b74ae0",
        "712e818f74bf3d38a03a3516533d0d4bf1df343f5a6e2056ae38a35f9ee7975b",
        "44cb86105da216b5f53071d5a1f652d09d83f877d611379d693c99a669a32520",
    ),
    "16.3": (
        "664facfa081008adb11a6df4373d1abe488927492ab8d618b9bc0b48cd1249ef",
        "c5ad9bec7a1d1ba393f818e48a6f066db0428ce939cf9f4066acfc23ac0f7411",
        "2aa76beed7df0f8ea004bf67609da629c9f91ad9b887d50f04f1369af96baff0",
    ),
}
VALIDATOR = "lxml-" + ".".join(map(str, E.LXML_VERSION))


class SchemaDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    line: int = Field(ge=0)
    path: str = Field(max_length=300)
    type_name: str = Field(max_length=100)
    message: str = Field(max_length=300)


class Eis223SchemaCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    purchase_number: str = Field(pattern=r"^[0-9]{11}$")
    version_number: int = Field(ge=1)
    xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_release: Literal["16.2", "16.3"]
    package_sha256: str
    root_sha256: str
    tree_sha256: str
    validator_version: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    status: Literal["PASS", "FAIL"]
    diagnostics: tuple[SchemaDiagnostic, ...] = Field(max_length=4)
    checked_at: datetime

    @model_validator(mode="after")
    def _bound(self) -> Eis223SchemaCheck:
        if (self.package_sha256, self.root_sha256, self.tree_sha256) != SCHEMAS[
            self.schema_release
        ]:
            raise ValueError("SCHEMA_POLICY_MISMATCH")
        if (self.status == "FAIL") != bool(self.diagnostics):
            raise ValueError("SCHEMA_DIAGNOSTICS_MISMATCH")
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("NOW_TIMEZONE_MISSING")
        return self


@dataclass(frozen=True)
class SchemaTree:
    release: Literal["16.2", "16.3"]
    compiled: Any


def load_schema_tree(root: Path, release: Literal["16.2", "16.3"]) -> SchemaTree:
    """Accept only the pinned complete official local tree; never fetch schemaLocation."""
    if release not in SCHEMAS or root.is_symlink():
        raise ValueError("SCHEMA_TREE_REJECTED")
    root = root.resolve()
    files = sorted(root.rglob("*.xsd"))
    if not 1 <= len(files) <= 512 or sum(p.stat().st_size for p in files) > 32 * 1024**2:
        raise ValueError("SCHEMA_TREE_REJECTED")
    parser = E.XMLParser(resolve_entities=False, no_network=True)
    manifest = []
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("SCHEMA_TREE_REJECTED")
        raw = path.read_bytes()
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("SCHEMA_TREE_REJECTED")
        tree = E.fromstring(raw, parser)
        for entry in tree.iter():
            location = entry.get("schemaLocation")
            if location:
                parts = urlsplit(location)
                target = (path.parent / location).resolve()
                if (
                    parts.scheme
                    or parts.netloc
                    or parts.query
                    or parts.fragment
                    or not target.is_relative_to(root)
                    or target not in files
                ):
                    raise ValueError("SCHEMA_TREE_REJECTED")
        manifest.append(
            {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    expected = SCHEMAS[release]
    if (
        digest != expected[2]
        or hashlib.sha256((root / "purchase.xsd").read_bytes()).hexdigest() != expected[1]
    ):
        raise ValueError("SCHEMA_POLICY_MISMATCH")
    return SchemaTree(release, E.XMLSchema(E.parse(str(root / "purchase.xsd"), parser)))


def validate_notice223_schema(
    notice: Eis223NoticeSnapshot, raw: bytes, tree: SchemaTree, *, now: datetime
) -> Eis223SchemaCheck:
    """A full source schema FAIL never becomes a supplier hard gate or corrected XML."""
    parsed = parse_notice223_xml(
        raw, source_member=notice.source_member, document_type=notice.document_type
    )
    if (parsed.purchase_number, parsed.version_number, parsed.xml_sha256) != (
        notice.purchase_number,
        notice.version_number,
        notice.xml_sha256,
    ):
        raise ValueError("SCHEMA_XML_IDENTITY_MISMATCH")
    valid = tree.compiled.validate(
        E.fromstring(raw, E.XMLParser(resolve_entities=False, no_network=True))
    )
    diagnostics = (
        ()
        if valid
        else tuple(
            SchemaDiagnostic(
                line=max(0, error.line),
                path=(error.path or "")[:300],
                type_name=error.type_name[:100],
                message=error.message[:300],
            )
            for error in list(tree.compiled.error_log)[:4]
        )
    )
    package, root, digest = SCHEMAS[tree.release]
    return Eis223SchemaCheck(
        purchase_number=notice.purchase_number,
        version_number=notice.version_number,
        xml_sha256=notice.xml_sha256,
        schema_release=tree.release,
        package_sha256=package,
        root_sha256=root,
        tree_sha256=digest,
        validator_version=VALIDATOR,
        status="PASS" if valid else "FAIL",
        diagnostics=diagnostics,
        checked_at=now,
    )


def schema_quality(checks: tuple[Eis223SchemaCheck, ...]) -> Literal["PASS", "FAIL", "UNKNOWN"]:
    if any(check.status == "FAIL" for check in checks):
        return "FAIL"
    return "PASS" if {check.schema_release for check in checks} == set(SCHEMAS) else "UNKNOWN"
