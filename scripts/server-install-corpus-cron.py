"""Add queue schedules while retaining the operator's existing crontab."""

import subprocess


def main() -> None:
    previous = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if previous.returncode not in {0, 1}:
        raise RuntimeError("CRONTAB_READ_FAILED")
    lines = previous.stdout.splitlines()
    schedules = {
        "# vibe-seller-corpus-run": (
            "*/15 * * * * umask 077; /home/syurai/vibe-seller/scripts/server-eis-corpus.sh "
            "run --max-windows 60 --max-database-gib 100 --min-free-gib 40 "
            "--base-scope-sha256 4cb88bd14e0ce383e8b809066c747820c5be76354924e60a4528675d734f81c9 "
            ">> /home/syurai/vibe-seller-state/eis-corpus.log 2>&1 # vibe-seller-corpus-run"
        ),
        "# vibe-seller-corpus-plan": (
            "10 4 * * * umask 077; /home/syurai/vibe-seller/scripts/server-eis-corpus-daily.sh "
            ">> /home/syurai/vibe-seller-state/eis-corpus.log 2>&1 # vibe-seller-corpus-plan"
        ),
    }
    for marker, line in schedules.items():
        lines = [existing for existing in lines if not existing.endswith(marker)]
        lines.append(line)
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    print("CORPUS_CRON_INSTALLED")


if __name__ == "__main__":
    main()
