"""Synthetic containers and converter output; no live procurement fixtures."""

import os
import struct
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pytest

from procurement.documents.bundle import extract_document_bundle
from procurement.documents.extraction import (
    DocumentInput,
    DocumentRejected,
    ExtractionLimits,
    extract_document,
)


def doc_bytes(*, flags: int = 0, version: int = 0xC1, macro: bool = False) -> bytes:
    """Minimal CFB with synthetic FIB, not a renderable Word document."""
    free, end = 0xFFFFFFFF, 0xFFFFFFFE
    header = bytearray(512)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHH", header, 24, 0x3E, 3, 0xFFFE, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, 1, 1, 0, 4096, end, 0, end, 0)
    struct.pack_into("<109I", header, 76, 0, *([free] * 108))
    fat = [0xFFFFFFFD, end, *range(3, 10), end, *range(11, 18), end]
    fat.extend([free] * (128 - len(fat)))

    def entry(name: str, kind: int, start: int, size: int, child: int = free) -> bytes:
        data = bytearray(128)
        encoded = (name + "\0").encode("utf-16le")
        data[: len(encoded)] = encoded
        struct.pack_into("<HBBIII", data, 64, len(encoded), kind, 1, free, free, child)
        struct.pack_into("<IQ", data, 116, start, size)
        return bytes(data)

    root = entry("Root Entry", 5, end, 0, 1)
    word = bytearray(entry("WordDocument", 2, 2, 4096))
    struct.pack_into("<I", word, 72, 2)  # right sibling
    table_name = "1Table" if flags & 0x200 else "0Table"
    table = bytearray(entry(table_name, 2, 10, 4096))
    if macro:
        struct.pack_into("<I", table, 72, 3)
    directory = (
        root + word + table + entry("Macros", 1, end, 0)
        if macro
        else (root + word + table + bytes(128))
    )
    fib = bytearray(4096)
    struct.pack_into("<HH", fib, 0, 0xA5EC, version)
    struct.pack_into("<H", fib, 10, flags)
    return bytes(header) + struct.pack("<128I", *fat) + directory + fib + bytes(4096)


def source(content: bytes, *, filename: str = "spec.doc") -> DocumentInput:
    return DocumentInput(
        document_id="synthetic-doc",
        filename=filename,
        declared_media_type="application/msword",
        content=content,
    )


def test_doc_text_has_reproducible_output_locator_and_layout_unknown(monkeypatch) -> None:
    from procurement.documents import legacy_doc

    monkeypatch.setattr(legacy_doc, "_run_antiword", lambda *_: "\nБумага А4\n\n80 г/м2\n")
    result = extract_document(source(doc_bytes(flags=0x200)))
    assert result.status == "UNKNOWN" and "LAYOUT_NOT_VERIFIED" in result.reasons
    assert [(block.text, block.provenance.locator) for block in result.blocks] == [
        ("Бумага А4", "antiword-0.37-16 utf8 w0 :: line 2"),
        ("80 г/м2", "antiword-0.37-16 utf8 w0 :: line 4"),
    ]
    assert all(block.provenance.extractor.is_lossy for block in result.blocks)


@pytest.mark.parametrize(
    "flags,version,macro,code",
    [
        (0x100, 0xC1, False, "ENCRYPTED_DOCUMENT"),
        (0, 0x65, False, "UNSUPPORTED_DOC_VERSION"),
        (0, 0xC1, True, "MACRO_ENABLED_FORMAT"),
    ],
)
def test_doc_preflight_never_calls_converter(monkeypatch, flags, version, macro, code) -> None:
    from procurement.documents import legacy_doc

    def forbidden(*_):
        pytest.fail("unsafe DOC reached converter")

    monkeypatch.setattr(legacy_doc, "_run_antiword", forbidden)
    with pytest.raises(DocumentRejected, match=code):
        extract_document(source(doc_bytes(flags=flags, version=version, macro=macro)))


def test_doc_magic_limits_and_text_limits(monkeypatch) -> None:
    from procurement.documents import legacy_doc

    with pytest.raises(DocumentRejected, match="MAGIC_MISMATCH"):
        extract_document(source(b"{\\rtf1 not binary Word}"))
    with pytest.raises(DocumentRejected, match="INPUT_TOO_LARGE"):
        extract_document(source(doc_bytes()), limits=ExtractionLimits(max_input_bytes=100))
    monkeypatch.setattr(legacy_doc, "_run_antiword", lambda *_: "a\nb\nc")
    with pytest.raises(DocumentRejected, match="SOURCE_UNIT_LIMIT"):
        extract_document(source(doc_bytes()), limits=ExtractionLimits(max_source_units=2))
    with pytest.raises(DocumentRejected, match="EXTRACTED_TEXT_LIMIT"):
        extract_document(source(doc_bytes()), limits=ExtractionLimits(max_extracted_characters=2))


def test_doc_zip_keeps_member_and_no_fabricated_page(monkeypatch) -> None:
    from procurement.documents import legacy_doc

    monkeypatch.setattr(legacy_doc, "_run_antiword", lambda *_: "Срок поставки 10 дней")
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("docs/spec.doc", doc_bytes())
    bundle = extract_document_bundle(
        DocumentInput(
            document_id="bundle",
            filename="docs.zip",
            declared_media_type="application/zip",
            content=output.getvalue(),
        )
    )
    assert bundle.members[0].extraction.status == "UNKNOWN"
    assert bundle.members[0].extraction.blocks[0].provenance.locator == (
        'archive member "docs/spec.doc" :: antiword-0.37-16 utf8 w0 :: line 1'
    )


def test_missing_converter_is_unknown_after_preflight(monkeypatch) -> None:
    from procurement.documents import legacy_doc

    monkeypatch.setattr(legacy_doc, "_BINARY", "/no-such-converter")
    result = extract_document(source(doc_bytes()))
    assert result.status == "UNKNOWN" and not result.blocks
    assert result.reasons == ("CONVERTER_UNAVAILABLE",)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux resource/seccomp contract")
def test_linux_launcher_denies_network_fork_and_inherited_secrets(monkeypatch) -> None:
    from procurement.documents.legacy_doc import _LAUNCHER

    program = """
import os, socket, resource
assert 'DOC_TEST_SECRET' not in os.environ
assert os.geteuid() != 0
for operation in (socket.socket, os.fork):
    try: operation()
    except PermissionError: pass
    else: raise AssertionError('forbidden system call succeeded')
assert resource.getrlimit(resource.RLIMIT_AS)[0] == 256 * 1024 * 1024
print('guarded')
"""
    monkeypatch.setenv("DOC_TEST_SECRET", "synthetic-private-value")
    env = {"LANG": "C.UTF-8"}
    assert "DOC_TEST_SECRET" not in env
    result = subprocess.run(
        [sys.executable, "-I", "-c", _LAUNCHER, "4096", sys.executable, "-I", "-c", program],
        capture_output=True,
        timeout=4,
        env=env,
        check=False,
        cwd="/tmp",
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"guarded\n"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux subprocess/output limits")
@pytest.mark.parametrize(
    "program,code,cap",
    [
        ("import time; time.sleep(5)", "CONVERTER_RESOURCE_LIMIT", 100),
        ("import os; os.write(1,b'x'*1000)", "CONVERTER_RESOURCE_LIMIT", 10),
        ("import sys; sys.stderr.write('partial output warning')", "PARSE_FAILED", 100),
        ("import os; os.write(1,b'\\xff')", "PARSE_FAILED", 100),
    ],
)
def test_real_subprocess_never_returns_partial_or_timed_out_output(
    monkeypatch,
    program,
    code,
    cap,
) -> None:
    from procurement.documents import legacy_doc

    # Synthetic executable exercises the production launcher, not Word semantics.
    # pytest parents may be private to root: use a separate world-traversable dir.
    # Honour the isolated runner's executable scratch; /tmp may be noexec.
    with TemporaryDirectory() as folder:
        os.chmod(folder, 0o755)
        executable = Path(folder) / "converter"
        executable.write_text(f"#!{sys.executable}\n{program}\n", encoding="utf-8")
        executable.chmod(0o755)
        monkeypatch.setattr(legacy_doc, "_BINARY", str(executable))
        monkeypatch.setattr(legacy_doc, "_TIMEOUT_SECONDS", 1)
        with pytest.raises(DocumentRejected, match=code):
            legacy_doc._run_antiword(b"synthetic", ExtractionLimits(max_extracted_characters=cap))
