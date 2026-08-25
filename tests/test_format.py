from datetime import time as clock

import jdatetime

from outgy import dates, format
from outgy.outage import Outage


def outage(day_offset: int, hour: int = 16) -> Outage:
    day = dates.today() + jdatetime.timedelta(days=day_offset)
    return Outage(
        bill_id="111122223333",
        date=day,
        start=clock(hour, 0),
        stop=clock(hour + 2, 0),
        address="خیابان نمونه",
        number="400001111111",
    )


def test_plain_empty_message():
    assert format.plain([]) == "No planned outages for this subscription in the coming days."


def test_html_empty_message():
    assert format.html([]) == format._EMPTY_HTML


def test_plain_marks_relative_days():
    text = format.plain([outage(0), outage(1)])
    assert "(today)" in text
    assert "(tomorrow)" in text


def test_plain_far_future_shows_only_stamp():
    text = format.plain([outage(5)])
    assert "(" not in text.splitlines()[2]


def test_plain_groups_by_day():
    same_day = [outage(0, 16), outage(0, 20)]
    text = format.plain(same_day)
    stamps = [line for line in text.splitlines() if line.startswith(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))]
    assert len(stamps) == 1
    assert "16:00-18:00" in text and "20:00-22:00" in text


def test_html_keeps_persian_presentation():
    text = format.html([outage(0)])
    assert "<b>" in text
    assert "کد خاموشی: ۴۰۰۰۰۱۱۱۱۱۱۱" in text
    assert "از ۱۶:۰۰ تا ۱۸:۰۰" in text
    assert "امروز" in text
