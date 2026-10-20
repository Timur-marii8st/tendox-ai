"""Локальный read-only browser preview; company_id задаёт оператор ОС."""

import argparse
import asyncio
import sys

from procurement.sources.browser_catalog import (
    BrowserOptions,
    BrowserSite,
    BrowserStatus,
    preview_browser_catalog,
)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--site", choices=[site.value for site in BrowserSite], required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--headed", action="store_true", help="показать окно браузера")
    parser.add_argument("--channel", choices=["chromium", "chrome", "msedge"], default="chromium")
    parser.add_argument("--no-motion", action="store_true", help="отключить курсор и прокрутку")
    args = parser.parse_args()
    try:
        result = asyncio.run(
            preview_browser_catalog(
                company_id=args.company_id,
                site=BrowserSite(args.site),
                query=args.query,
                options=BrowserOptions(
                    headed=args.headed, channel=args.channel, natural_motion=not args.no_motion
                ),
            )
        )
    except ValueError:
        parser.error("Некорректный company-id или запрос (1–5 слов, до 80 символов)")
    print(result.model_dump_json(indent=2))
    return 0 if result.status == BrowserStatus.COMPLETED else 2


if __name__ == "__main__":
    raise SystemExit(main())
