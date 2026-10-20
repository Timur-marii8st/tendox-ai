"""Diagnose one failed official window without logging attachment identifiers or XML."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
from datetime import date

from sqlalchemy import create_engine

from procurement.sources import eis_feed_archive as archive
from procurement.sources.eis_feed_sync import EisDateSelection, sync_eis_window_via_browser
from procurement.storage.repository import PostgresStorage


def main() -> None:
    original = archive._attachments
    problems: Counter[str] = Counter()

    def diagnosed(notice):  # type: ignore[no-untyped-def]
        try:
            return original(notice)
        except archive.EisFeedArchiveError as error:
            if str(error) != "ATTACHMENT_REFERENCE_INVALID":
                raise
            block = archive._optional_child(notice, "attachmentsInfo")
            seen: set[str] = set()
            for item in block if block is not None else ():
                if archive._name(item) != "attachmentInfo":
                    continue
                try:
                    uid = archive._value(item, "publishedContentId")
                    filename = archive._value(item, "fileName")
                    url = archive._value(item, "url")
                    size = archive._value(item, "fileSize")
                except archive.EisFeedArchiveError:
                    problems["MISSING_FIELD"] += 1
                    continue
                if not archive._FILE_UID.fullmatch(uid):
                    problems["UID_FORMAT"] += 1
                if uid in seen:
                    problems["DUPLICATE_UID"] += 1
                if not size.isdecimal() or int(size) < 0:
                    problems["SIZE_FORMAT"] += 1
                if len(filename) > 255:
                    problems["FILENAME_LENGTH"] += 1
                if re.search(r"[/\\]", filename):
                    problems["FILENAME_SEPARATOR"] += 1
                if "\x00" in filename:
                    problems["FILENAME_NUL"] += 1
                if not archive._official_url(url, uid):
                    problems["URL_SHAPE_OR_UID_MISMATCH"] += 1
                seen.add(uid)
            raise

    archive._attachments = diagnosed  # type: ignore[assignment]
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        result = asyncio.run(
            sync_eis_window_via_browser(
                PostgresStorage(engine),
                os.environ.get("EIS_COMPANY_ID", "local-eis-supplier"),
                "attachment-diagnostic",
                EisDateSelection("16", date(2026, 9, 28), 3),
                os.environ["EIS_GETDOCS_IP_TOKEN"],
            )
        )
        print(json.dumps({"status": result.status, "problem_counts": dict(problems)}))
    except (archive.EisFeedArchiveError, ValueError) as error:
        print(json.dumps({"status": type(error).__name__, "problem_counts": dict(problems)}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
