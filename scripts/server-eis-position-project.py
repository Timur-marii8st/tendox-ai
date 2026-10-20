"""Bounded explicit server projection of retained XML44; no credentials in output."""

import argparse
import json
import os

from sqlalchemy import create_engine

from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_position_projection import project_notice_positions
from procurement.storage.repository import PostgresStorage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--purchase-number", required=True)
    parser.add_argument("--version-number", required=True, type=int)
    parser.add_argument("--notice-xml-sha256", required=True)
    args = parser.parse_args()
    ref = NoticeDocumentRef(
        purchase_number=args.purchase_number,
        version_number=args.version_number,
        notice_xml_sha256=args.notice_xml_sha256,
    )
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        added = project_notice_positions(
            PostgresStorage(engine), args.company_id, ref, actor_id="server-position-projection"
        )
        print(json.dumps({"created": added, "source": ref.model_dump()}))
    except (ValueError, LookupError):
        print(json.dumps({"status": "ATTENTION_REQUIRED"}))
        raise SystemExit(1) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
