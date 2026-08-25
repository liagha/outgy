from itertools import groupby

import jdatetime

from .dates import iso, today
from .outage import Outage
from .text import persian_digits

_EMPTY_PLAIN = "No planned outages for this subscription in the coming days."
_TITLE_PLAIN = "Planned outages"
_EMPTY_HTML = "در روزهای آینده خاموشی برنامه‌ریزی‌شده‌ای برای این اشتراک ثبت نشده است ✅"
_TITLE_HTML = "🔌 <b>خاموشی‌های برنامه‌ریزی‌شده</b>"

_RELATIVE_PLAIN = {0: "today", 1: "tomorrow"}
_RELATIVE_HTML = {0: "امروز", 1: "فردا"}

_WEEKDAYS = {
    1: "دوشنبه",
    2: "سه‌شنبه",
    3: "چهارشنبه",
    4: "پنجشنبه",
    5: "جمعه",
    6: "شنبه",
    7: "یکشنبه",
}


def plain(outages: list[Outage]) -> str:
    if not outages:
        return _EMPTY_PLAIN
    blocks = [_TITLE_PLAIN]
    for date, group in _grouped(outages):
        lines = [_plain_day(date)]
        for outage in group:
            lines.append(f"  {outage.start:%H:%M}-{outage.stop:%H:%M}")
            if outage.address:
                lines.append(f"  {outage.address}")
            if outage.number:
                lines.append(f"  code {outage.number}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def html(outages: list[Outage]) -> str:
    if not outages:
        return _EMPTY_HTML
    blocks = [_TITLE_HTML]
    for date, group in _grouped(outages):
        lines = [f"🗓 <b>{_html_day(date)}</b>"]
        for outage in group:
            start = persian_digits(f"{outage.start:%H:%M}")
            stop = persian_digits(f"{outage.stop:%H:%M}")
            lines.append(f"⏰ از {start} تا {stop}")
            if outage.address:
                lines.append(f"📍 {outage.address}")
            if outage.number:
                lines.append(f"🔢 کد خاموشی: {persian_digits(outage.number)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _grouped(outages: list[Outage]):
    return groupby(outages, key=lambda outage: outage.date)


def _offset(date: jdatetime.date) -> int:
    return date.togregorian().toordinal() - today().togregorian().toordinal()


def _plain_day(date: jdatetime.date) -> str:
    stamp = date.togregorian().strftime("%a %d %b %Y")
    relative = _RELATIVE_PLAIN.get(_offset(date))
    return f"{stamp} ({relative})" if relative else stamp


def _html_day(date: jdatetime.date) -> str:
    weekday = _WEEKDAYS[date.togregorian().isoweekday()]
    relative = _RELATIVE_HTML.get(_offset(date))
    return f"{weekday} {relative}" if relative else f"{weekday} {persian_digits(iso(date))}"
