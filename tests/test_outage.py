from outgy.outage import Outage

ROW = {
    "reg_date": "1405/06/03",
    "registrar": "setad",
    "outage_date": "۱۴۰۵/۶/۳",
    "outage_start_time": "۲۲:۰۰",
    "outage_stop_time": "23:55",
    "address": " خیابان نمونه ",
    "outage_number": 400001111111,
}


def test_from_api_normalizes_digits_and_types():
    outage = Outage.from_api(ROW, "111122223333")
    assert outage.bill_id == "111122223333"
    assert (outage.date.year, outage.date.month, outage.date.day) == (1405, 6, 3)
    assert (outage.start.hour, outage.start.minute) == (22, 0)
    assert (outage.stop.hour, outage.stop.minute) == (23, 55)
    assert outage.address == "خیابان نمونه"
    assert outage.number == "400001111111"


def test_key_is_script_independent():
    latin = {**ROW, "outage_date": "1405/6/3", "outage_start_time": "22:00"}
    persian = dict(ROW)
    assert Outage.from_api(latin, "b").key == Outage.from_api(persian, "b").key


def test_key_is_stable():
    key = Outage.from_api(ROW, "b").key
    assert key == "1405/06/03|22:00|23:55|400001111111"


def test_from_api_rejects_malformed_rows():
    broken = [
        {**ROW, "outage_date": "yesterday"},
        {**ROW, "outage_start_time": "25:00"},
        {**ROW, "outage_stop_time": ""},
        {},
    ]
    for row in broken:
        assert Outage.from_api(row, "b") is None


def test_outages_sort_chronologically():
    first = Outage.from_api(ROW, "b")
    second = Outage(
        bill_id="b",
        date=first.date,
        start=first.stop,
        stop=first.stop,
    )
    assert sorted([second, first]) == [first, second]
