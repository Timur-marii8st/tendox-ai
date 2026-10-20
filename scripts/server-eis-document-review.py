"""One exact source0 DOCX review; source credentials are unused and never printed."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from procurement.storage.eis_document_review import (
    ReviewDocumentRequest,
    prepare_review_document,
    read_review_document_page,
)
from procurement.storage.repository import PostgresStorage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "read"))
    parser.add_argument("request_json")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--character-offset", type=int, default=0)
    args = parser.parse_args()
    if len(args.request_json.encode()) > 4096:
        print(json.dumps({"status": "BLOCKED", "reason": "REVIEW_INPUT_LIMIT"}))
        return 2
    if args.action == "prepare" and (
        args.offset != 0 or args.limit != 25 or args.character_offset != 0
    ):
        print(json.dumps({"status": "BLOCKED", "reason": "REVIEW_PREPARE_PAGE_INVALID"}))
        return 2
    engine = None
    try:
        request = ReviewDocumentRequest.model_validate_json(args.request_json)
        for key in ("EIS_GETDOCS_IP_TOKEN", "EIS_PILOT_TOKEN"):
            os.environ.pop(key, None)
        engine = create_engine(os.environ["DATABASE_URL"])
        storage = PostgresStorage(engine)
        if args.action == "prepare":
            result = prepare_review_document(
                storage, "local-eis-supplier", request, actor_id="server-document-review"
            )
        else:
            result = read_review_document_page(
                storage,
                "local-eis-supplier",
                request,
                offset=args.offset,
                limit=args.limit,
                character_offset=args.character_offset,
            )
        payload = result.model_dump_json()
        if len(payload.encode()) > 256 * 1024:
            raise ValueError("REVIEW_PAGE_RESPONSE_LIMIT")
        print(payload)
        return 0
    except ValidationError:
        reason = "REVIEW_INPUT_INVALID"
    except (ValueError, LookupError) as error:
        reason = (
            str(error) if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", str(error)) else "REVIEW_INVALID"
        )
    except SQLAlchemyError:
        reason = "REVIEW_STORAGE_ERROR"
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps({"status": "BLOCKED", "reason": reason, "source_requests": 0}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
