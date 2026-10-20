"""Schedule changes preserve every unrelated server job and cannot silently widen commands."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "regional_cron", Path(__file__).parents[1] / "scripts/server-eis-223-refresh-cron.py"
)
cron = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cron)


def test_schedule_replaces_duplicates_preserves_other_jobs_and_is_idempotent():
    other = "# operator note\nMAILTO=ops@example.test\n2 * * * * /opt/other-job.sh\n"
    old = other + "11,41 * * * * " + cron.COMMAND + "\n" + cron.ENTRY + "\n"
    result = cron.updated_crontab(old)
    assert result == other + cron.ENTRY + "\n"
    assert cron.updated_crontab(result) == result


def test_schedule_rejects_unrecognized_command_without_touching_it():
    with pytest.raises(ValueError, match="COMMAND_REVIEW_REQUIRED"):
        cron.updated_crontab("* * * * * " + cron.SCRIPT + " --unexpected-different-mode\n")
