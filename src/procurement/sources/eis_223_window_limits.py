"""Shared bounded limits for a complete 223-FZ notice source window."""

from procurement.sources.eis_223_archive import (
    MAX_ARCHIVE_BYTES,
)
from procurement.sources.eis_223_archive import (
    MAX_EXPANDED_BYTES as MAX_ARCHIVE_EXPANDED_BYTES,
)
from procurement.sources.eis_223_archive import (
    MAX_MEMBERS as MAX_ARCHIVE_MEMBERS,
)
from procurement.sources.eis_223_archive import (
    MAX_NOTICE_XML_BYTES as MAX_XML_BYTES,
)

MAX_NOTICE_ARCHIVES = 8
MAX_NOTICE_COMPRESSED_BYTES = 40 * 1024 * 1024
MAX_NOTICE_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_NOTICE_MEMBERS = 800

__all__ = (
    "MAX_ARCHIVE_BYTES",
    "MAX_ARCHIVE_EXPANDED_BYTES",
    "MAX_ARCHIVE_MEMBERS",
    "MAX_NOTICE_ARCHIVES",
    "MAX_NOTICE_COMPRESSED_BYTES",
    "MAX_NOTICE_EXPANDED_BYTES",
    "MAX_NOTICE_MEMBERS",
    "MAX_XML_BYTES",
)
