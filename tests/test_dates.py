import re

from outgy import dates


def test_window_spans_requested_days():
    start, end = dates.window(3)
    assert re.match(r"^\d{4}/\d{2}/\d{2}$", start)
    first = dates.parse_date(start).togregorian().toordinal()
    last = dates.parse_date(end).togregorian().toordinal()
    assert last - first == 3


def test_parse_date_accepts_persian_digits():
    day = dates.parse_date("۱۴۰۵/۶/۳")
    assert (day.year, day.month, day.day) == (1405, 6, 3)


def test_parse_date_rejects_invalid():
    assert dates.parse_date("2026-08-25") is None
    assert dates.parse_date("1405/13/01") is None
    assert dates.parse_date("") is None


def test_parse_time_accepts_single_digit_minute():
    clock = dates.parse_time("16:0")
    assert (clock.hour, clock.minute) == (16, 0)


def test_parse_time_rejects_out_of_range():
    assert dates.parse_time("25:00") is None
    assert dates.parse_time("12:60") is None


def test_parse_time_rejects_garbage():
    assert dates.parse_time("4pm") is None
    assert dates.parse_time("") is None
