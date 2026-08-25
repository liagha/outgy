from dataclasses import dataclass
from datetime import time
from itertools import groupby

import jdatetime

from . import dates, text


@dataclass(frozen=True, order=True)
class Outage:
    bill_id: str
    date: jdatetime.date
    start: time
    stop: time
    address: str = ""
    number: str = ""

    @property
    def key(self) -> str:
        return "|".join((dates.iso(self.date), f"{self.start:%H:%M}", f"{self.stop:%H:%M}", self.number))

    @classmethod
    def from_api(cls, item: dict, bill_id: str) -> "Outage | None":
        date = dates.parse_date(text.latin_digits(str(item.get("outage_date") or "")))
        start = dates.parse_time(text.latin_digits(str(item.get("outage_start_time") or "")))
        stop = dates.parse_time(text.latin_digits(str(item.get("outage_stop_time") or "")))
        if not (date and start and stop):
            return None
        return cls(
            bill_id=bill_id,
            date=date,
            start=start,
            stop=stop,
            address=str(item.get("address") or "").strip(),
            number=text.latin_digits(str(item.get("outage_number") or "")).strip(),
        )


def by_day(outages: list["Outage"]) -> dict[jdatetime.date, list["Outage"]]:
    return {day: list(items) for day, items in groupby(outages, key=lambda outage: outage.date)}
