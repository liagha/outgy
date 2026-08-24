import jdatetime

from .saapa import Outage, today_jalali

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

_WEEKDAYS = {
    1: "دوشنبه",
    2: "سه‌شنبه",
    3: "چهارشنبه",
    4: "پنجشنبه",
    5: "جمعه",
    6: "شنبه",
    7: "یکشنبه",
}


def fa(text: str) -> str:
    return text.translate(_PERSIAN_DIGITS)


def _describe_date(date_str: str) -> str:
    y, m, d = (int(p) for p in date_str.split("/"))
    jdate = jdatetime.date(y, m, d)
    gregorian = jdate.togregorian()
    weekday = _WEEKDAYS[gregorian.isoweekday()]
    today = today_jalali()
    if (jdate.year, jdate.month, jdate.day) == (today.year, today.month, today.day):
        label = "امروز"
    elif gregorian.toordinal() == today.togregorian().toordinal() + 1:
        label = "فردا"
    else:
        label = fa(date_str)
    return f"{weekday} {label}"


def format_outages(outages: list[Outage], html: bool = True) -> str:
    if not outages:
        return "در روزهای آینده خاموشی برنامه‌ریزی‌شده‌ای برای این اشتراک ثبت نشده است ✅"
    title = "خاموشی‌های برنامه‌ریزی‌شده"
    lines = [f"🔌 <b>{title}</b>" if html else f"🔌 {title}", ""]
    seen_dates: set[str] = set()
    for outage in outages:
        if outage.date not in seen_dates and seen_dates:
            lines.append("")
        seen_dates.add(outage.date)
        span = f"از {fa(outage.start_time)} تا {fa(outage.stop_time)}"
        date_line = f"🗓 {_describe_date(outage.date)} ({span})"
        lines.append(f"🗓 <b>{_describe_date(outage.date)}</b> ({span})" if html else date_line)
        if outage.address:
            lines.append(f"📍 {outage.address}")
        lines.append(f"🔢 کد خاموشی: {fa(outage.number)}")
        lines.append("")
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)
