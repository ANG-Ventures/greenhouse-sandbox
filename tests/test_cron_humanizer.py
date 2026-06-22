import pytest

from tools.cron_humanizer import humanize, parse, CronParseError


def test_every_minute():
    assert humanize("* * * * *") == "every minute"


def test_step_minutes():
    expected = "at minute(s) 0, 15, 30, 45 of hour(s) " + ", ".join(str(h) for h in range(24))
    assert humanize("*/15 * * * *") == expected


def test_fixed_clock_time():
    assert humanize("30 2 * * *") == "at 02:30"


def test_weekday_range():
    out = humanize("0 9 * * 1-5")
    assert out.startswith("at 09:00")
    assert out.endswith("on Monday, Tuesday, Wednesday, Thursday and Friday")


def test_day_of_month_and_month():
    out = humanize("0 0 1 12 *")
    assert out == "at 00:00 on day-of-month 1 in December"


def test_sunday_seven_normalizes():
    # 7 and 0 both mean Sunday
    assert humanize("0 0 * * 7").endswith("on Sunday")
    assert humanize("0 0 * * 0").endswith("on Sunday")


def test_month_list_names():
    out = humanize("0 0 * 1,6,12 *")
    assert out.endswith("in January, June and December")


def test_parse_returns_five_fields():
    fields = parse("*/15 * * * *")
    assert len(fields) == 5
    assert fields[0].values() == [0, 15, 30, 45]


@pytest.mark.parametrize("bad", [
    "* * * *",            # too few fields
    "* * * * * *",        # too many fields
    "60 * * * *",         # minute out of range
    "* 24 * * *",         # hour out of range
    "* * * 13 *",         # month out of range
    "*/0 * * * *",        # zero step
    "5-1 * * * *",        # inverted range
    "abc * * * *",        # non-numeric
])
def test_invalid_expressions_raise(bad):
    with pytest.raises(CronParseError):
        humanize(bad)
