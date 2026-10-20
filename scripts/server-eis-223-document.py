"""Operator one-file223 command; exact source refs only, secret-safe stdout."""

import argparse
import json
import os

from sqlalchemy import create_engine

from procurement.sources.eis_223_documents import Notice223DocumentRef
from procurement.storage.eis_223_documents import collect_document223
from procurement.storage.repository import PostgresStorage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--number", required=True)
    parser.add_argument("--version", required=True, type=int)
    parser.add_argument("--xml-sha256", required=True)
    parser.add_argument("--uid", required=True)
    args = parser.parse_args()
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        ref = Notice223DocumentRef(
            purchase_number=args.number,
            version_number=args.version,
            notice_xml_sha256=args.xml_sha256,
        )
        result = collect_document223(
            PostgresStorage(engine),
            "local-eis-supplier",
            ref,
            args.uid,
            actor_id="223-document-operator",
        )
        print(
            json.dumps(
                {
                    "notice": ref.model_dump(),
                    "download_status": result.download_status,
                    "eligibility": "UNKNOWN",
                    "documents": [
                        {
                            "uid": d.reference.content_uid,
                            "filename": d.reference.filename,
                            "received": d.received,
                            "sha256": d.analysis.sha256 if d.analysis else None,
                            "bytes": d.analysis.byte_count if d.analysis else None,
                            "extraction_status": d.analysis.status if d.analysis else "UNKNOWN",
                            "blocks": d.analysis.blocks_total if d.analysis else 0,
                            "conditions": len(d.analysis.snippets) if d.analysis else 0,
                        }
                        for d in result.documents
                    ],
                }
            )
        )
    except Exception:
        print('{"reason":"DOCUMENT_223_UNAVAILABLE","eligibility":"UNKNOWN"}')
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
