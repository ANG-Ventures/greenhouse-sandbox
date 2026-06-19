import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "cron_humanizer.py"
SPEC = importlib.util.spec_from_file_location("cron_humanizer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
cron_humanizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cron_humanizer)

humanize_cron = cron_humanizer.humanize_cron


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("* * * * *", "Every minute every day"),
        ("*/15 * * * *", "Every 15 minutes every day"),
        ("30 9 * * MON", "At 9:30 AM on Mon"),
        ("0 0 1 jan *", "At 12:00 AM on day 1 of the month in January"),
        ("45 23 * * 5", "At 11:45 PM on Friday"),
    ],
)
def test_humanize_common_cron_shapes(expression, expected):
    assert humanize_cron(expression) == expected


def test_rejects_non_five_field_cron_expression():
    with pytest.raises(ValueError, match="exactly 5 fields"):
        humanize_cron("0 12 * *")


def test_rejects_unsupported_ranges_for_now():
    with pytest.raises(ValueError, match="unsupported cron field"):
        humanize_cron("0 9-17 * * *")
