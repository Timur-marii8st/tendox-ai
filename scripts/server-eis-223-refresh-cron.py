"""Install one bounded regional refresh schedule without replacing unrelated jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess

SCRIPT = "/home/syurai/vibe-seller/scripts/server-eis-223-refresh.sh"
COMMAND = SCRIPT + " >> /home/syurai/vibe-seller-state/eis-223-refresh.log 2>&1"
ENTRY = "5,15,25,35,45,55 * * * * " + COMMAND


def updated_crontab(current: str) -> str:
    retained = []
    for line in current.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and SCRIPT in stripped:
            pieces = stripped.split(maxsplit=5)
            if len(pieces) != 6 or pieces[5] != COMMAND:
                raise ValueError("REGIONAL_CRON_COMMAND_REVIEW_REQUIRED")
            continue
        retained.append(line)
    return "\n".join([*retained, ENTRY]) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    old = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if old.returncode not in (0, 1):
        raise RuntimeError("CRONTAB_READ_FAILED")
    if old.returncode == 1 and "no crontab" not in old.stderr.lower():
        raise RuntimeError("CRONTAB_READ_FAILED")
    updated = updated_crontab(old.stdout)
    if args.apply and updated != old.stdout:
        subprocess.run(["crontab", "-"], input=updated, text=True, capture_output=True, check=True)
    print(
        json.dumps(
            {
                "applied": args.apply,
                "changed": updated != old.stdout,
                "entry": ENTRY,
                "sha256": hashlib.sha256(updated.encode()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
