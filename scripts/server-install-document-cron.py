"""Schedule bounded document intake while retaining all unrelated cron entries."""

import subprocess


def main() -> None:
    previous = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if previous.returncode not in {0, 1}:
        raise RuntimeError("CRONTAB_READ_FAILED")
    marker = "# vibe-seller-document-run"
    lines = [line for line in previous.stdout.splitlines() if not line.endswith(marker)]
    lines.append(
        "* * * * * umask 077; /home/syurai/vibe-seller/scripts/server-eis-documents.sh "
        ">> /home/syurai/vibe-seller-state/eis-documents.log 2>&1 " + marker
    )
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    print("DOCUMENT_CRON_INSTALLED")


if __name__ == "__main__":
    main()
