"""Bounded Word 97–2003 text derivative; output lines are not source pages."""

from __future__ import annotations

import os
import struct
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile

from procurement.documents.extraction import (
    DocumentInput,
    DocumentRejected,
    DocumentRejectionCode,
    ExtractionLimits,
    ExtractionReason,
    ExtractionResult,
    ExtractionStatus,
    _blocks_from_units,
    _result_or_unknown,
)
from procurement.domain.provenance import Extractor

_BINARY = "/usr/bin/antiword"
_TIMEOUT_SECONDS = 8
_LOCATOR_PREFIX = "antiword-0.37-16 utf8 w0 :: line"

# Child-side setup avoids preexec_fn in a threaded API. No inherited secrets,
# network sockets, process spawning, root privileges or unbounded output.
_LAUNCHER = """
import ctypes, ctypes.util, os, resource, sys
cap = int(sys.argv[1])
resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
resource.setrlimit(resource.RLIMIT_CPU, (4, 5))
resource.setrlimit(resource.RLIMIT_FSIZE, (cap,) * 2)
resource.setrlimit(resource.RLIMIT_NOFILE, (32,) * 2)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
lib = ctypes.CDLL(ctypes.util.find_library('seccomp') or 'libseccomp.so.2')
lib.seccomp_init.argtypes = [ctypes.c_uint32]
lib.seccomp_init.restype = ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
lib.seccomp_load.argtypes = [ctypes.c_void_p]
lib.seccomp_release.argtypes = [ctypes.c_void_p]
ctx = lib.seccomp_init(0x7fff0000)
if not ctx: raise RuntimeError('seccomp init')
for name in ('socket', 'socketpair', 'connect', 'bind', 'listen', 'accept', 'accept4',
             'sendto', 'sendmsg', 'sendmmsg', 'recvfrom', 'recvmsg', 'recvmmsg',
             'fork', 'vfork', 'clone', 'clone3', 'ptrace', 'mount', 'unshare', 'setns'):
    num = lib.seccomp_syscall_resolve_name(name.encode('ascii'))
    if num >= 0 and lib.seccomp_rule_add(ctx, 0x00050001, num, 0) != 0:
        raise RuntimeError('seccomp rule')
if os.geteuid() == 0:
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
libc = ctypes.CDLL(None)
if libc.prctl(38, 1, 0, 0, 0) != 0: raise RuntimeError('no new privileges')
if lib.seccomp_load(ctx) != 0: raise RuntimeError('seccomp load')
lib.seccomp_release(ctx)
os.execv(sys.argv[2], sys.argv[2:])
"""


def _inspect_word(content: bytes, limits: ExtractionLimits) -> None:
    import olefile  # type: ignore[import-untyped]

    with olefile.OleFileIO(BytesIO(content), raise_defects=olefile.DEFECT_INCORRECT) as ole:
        names = ole.listdir(streams=True, storages=True)
        if len(names) > limits.max_zip_members:
            raise DocumentRejected(DocumentRejectionCode.ZIP_MEMBER_LIMIT)
        parts = {part.casefold() for name in names for part in name}
        if any("vba" in part or part == "macros" for part in parts):
            raise DocumentRejected(DocumentRejectionCode.MACRO_ENABLED_FORMAT)
        streams = ole.listdir()
        if sum(ole.get_size(name) for name in streams) > limits.max_zip_expanded_bytes:
            raise DocumentRejected(DocumentRejectionCode.ZIP_EXPANSION_LIMIT)
        words = [name for name in streams if len(name) == 1 and name[0] == "WordDocument"]
        if len(words) != 1 or ole.get_size(words[0]) < 32:
            raise DocumentRejected(DocumentRejectionCode.MALFORMED_CONTAINER)
        if ole.get_size(words[0]) > limits.max_input_bytes:
            raise DocumentRejected(DocumentRejectionCode.INPUT_TOO_LARGE)
        fib = ole.openstream(words[0]).read(32)
        ident, version = struct.unpack_from("<HH", fib)
        if ident != 0xA5EC:
            raise DocumentRejected(DocumentRejectionCode.MALFORMED_CONTAINER)
        flags = struct.unpack_from("<H", fib, 10)[0]
        if flags & 0x100:
            raise DocumentRejected(DocumentRejectionCode.ENCRYPTED_DOCUMENT)
        if version not in {0xC1, 0xD9, 0x101, 0x10C, 0x112}:
            raise DocumentRejected(DocumentRejectionCode.UNSUPPORTED_DOC_VERSION)
        table = "1Table" if flags & 0x200 else "0Table"
        if [table] not in streams or ole.get_size(table) == 0 or ole.parsing_issues:
            raise DocumentRejected(DocumentRejectionCode.MALFORMED_CONTAINER)


def _run_antiword(content: bytes, limits: ExtractionLimits) -> str | None:
    if sys.platform != "linux" or not Path(_BINARY).is_file():
        return None
    cap = min(limits.max_extracted_characters * 4 + 1, 20 * 1024 * 1024 + 1)
    with (
        TemporaryDirectory(prefix="syurai-doc-") as home,
        TemporaryFile() as out,
        TemporaryFile() as err,
    ):
        os.chmod(home, 0o755)  # traversable after root -> nobody, contains no source files
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    _LAUNCHER,
                    str(cap),
                    _BINARY,
                    "-t",
                    "-m",
                    "UTF-8.txt",
                    "-w",
                    "0",
                    "-",
                ],
                input=content,
                stdout=out,
                stderr=err,
                cwd=home,
                env={"HOME": home, "ANTIWORDHOME": "/usr/share/antiword", "LANG": "C.UTF-8"},
                timeout=_TIMEOUT_SECONDS,
                check=False,
                close_fds=True,
            )
        except subprocess.TimeoutExpired as error:
            raise DocumentRejected(DocumentRejectionCode.CONVERTER_RESOURCE_LIMIT) from error
        except OSError as error:
            raise DocumentRejected(DocumentRejectionCode.PARSE_FAILED) from error
        out.seek(0)
        output = out.read(cap)
        err.seek(0)
        warnings = err.read(1)
        if len(output) >= cap or completed.returncode in {-9, -24, -25}:
            raise DocumentRejected(DocumentRejectionCode.CONVERTER_RESOURCE_LIMIT)
        if completed.returncode != 0 or warnings:
            raise DocumentRejected(DocumentRejectionCode.PARSE_FAILED)
        try:
            return output.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise DocumentRejected(DocumentRejectionCode.PARSE_FAILED) from error


def extract_legacy_doc(document: DocumentInput, limits: ExtractionLimits) -> ExtractionResult:
    """Read validated OLE Word text; layout/completeness remains UNKNOWN."""
    try:
        _inspect_word(document.content, limits)
    except DocumentRejected:
        raise
    except (OSError, ValueError, struct.error) as error:
        raise DocumentRejected(DocumentRejectionCode.MALFORMED_CONTAINER) from error
    text = _run_antiword(document.content, limits)
    if text is None:
        return ExtractionResult(
            status=ExtractionStatus.UNKNOWN,
            reasons=(ExtractionReason.CONVERTER_UNAVAILABLE,),
            source_units_total=0,
            source_units_extracted=0,
            characters_extracted=0,
        )
    lines = text.splitlines()
    if len(lines) > limits.max_source_units:
        raise DocumentRejected(DocumentRejectionCode.SOURCE_UNIT_LIMIT)
    blocks = _blocks_from_units(
        document.document_id,
        Extractor.LEGACY_DOC_TEXT,
        ((f"{_LOCATOR_PREFIX} {number}", line) for number, line in enumerate(lines, 1)),
        limits.max_extracted_characters,
    )
    return _result_or_unknown(blocks, len(lines), (ExtractionReason.LAYOUT_NOT_VERIFIED,))
