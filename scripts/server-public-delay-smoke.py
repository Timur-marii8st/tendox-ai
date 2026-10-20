"""Verify shared source cooldown without making a network request."""

import argparse
from datetime import UTC, datetime

from procurement.sources.eis_public import _host_lease


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("write", "read"))
    args = parser.parse_args()
    with _host_lease() as retry_at:
        if args.mode == "read":
            assert retry_at is not None and retry_at > datetime.now(UTC)
    print("PUBLIC_COOLDOWN_" + args.mode.upper() + "_OK")


if __name__ == "__main__":
    main()
