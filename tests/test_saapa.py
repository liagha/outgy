import json

import httpx
import pytest

from outgy import saapa
from outgy.dates import window
from outgy.outage import Outage

from conftest import load, make_client, respond, run

TOKEN = "test-token"
BILL = "111122223333"


def test_planned_blackouts_parses_recorded_fixture():
    client = make_client({saapa.PLANNED_BLACKOUTS_PATH: "planned_blackouts.json"})
    outages = run(client.planned_blackouts(BILL, 7, token=TOKEN))
    assert len(outages) == 1
    outage = outages[0]
    assert isinstance(outage, Outage)
    assert outage.number == "400001111111"
    assert (outage.start.hour, outage.stop.hour) == (16, 18)
    assert outage.address == "خیابان نمونه، پلاک ۱"


def test_planned_blackouts_drops_malformed_and_sorts():
    client = make_client({saapa.PLANNED_BLACKOUTS_PATH: "planned_blackouts_mixed.json"})
    outages = run(client.planned_blackouts(BILL, 7, token=TOKEN))
    assert len(outages) == 2
    assert [o.date.day for o in outages] == [3, 4]
    assert outages[1].number == "400002222222"


def test_planned_blackouts_sends_expected_payload():
    seen = {}

    def route(request: httpx.Request) -> httpx.Response:
        seen["payload"] = request.read()
        seen["auth"] = request.headers.get("Authorization")
        return respond("planned_blackouts.json")

    client = make_client({saapa.PLANNED_BLACKOUTS_PATH: route})
    run(client.planned_blackouts(BILL, 7, token=TOKEN))
    from_date, to_date = window(7)
    assert json.loads(seen["payload"]) == {
        "bill_id": BILL,
        "from_date": from_date,
        "to_date": to_date,
    }
    assert seen["auth"] == f"Bearer {TOKEN}"


def test_retries_on_rate_limit(monkeypatch):
    async def nosleep(_delay):
        pass

    monkeypatch.setattr(saapa.asyncio, "sleep", nosleep)
    calls = {"n": 0}

    def route(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] == 1 else respond("planned_blackouts.json")

    client = make_client({saapa.PLANNED_BLACKOUTS_PATH: route})
    outages = run(client.planned_blackouts(BILL, 7, token=TOKEN))
    assert calls["n"] == 2
    assert len(outages) == 1


def test_expired_token_raises_auth_error():
    client = make_client({saapa.PLANNED_BLACKOUTS_PATH: 401})
    with pytest.raises(saapa.SaapaAuthError):
        run(client.planned_blackouts(BILL, 7, token=TOKEN))


def test_api_level_rejection_raises():
    def route(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 400, "message": "bad bill", "error": []})

    client = make_client({saapa.PLANNED_BLACKOUTS_PATH: route})
    with pytest.raises(saapa.SaapaRejected):
        run(client.planned_blackouts("1", 7, token=TOKEN))


def test_account_extracts_bills_and_mobile():
    client = make_client({saapa.GET_BILLS_PATH: "get_bills.json"})
    bills, mobile = run(client.account(token=TOKEN))
    assert len(bills) == 2
    assert mobile == "09120000000"
    assert saapa.extract_bill_id(bills[0]) == "111122223333"


def test_search_branch_normalizes_serial():
    seen = {}

    def route(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.read()))
        return respond("search_branch.json")

    client = make_client({saapa.SEARCH_BRANCH_PATH: route})
    results = run(
        client.search_branch(search_type=2, co_code=42, serial_number="۱۲۳۴۵۶۷۸", token=TOKEN)
    )
    assert seen["serial_number"] == "12345678"
    assert seen["search_type"] == 2
    assert saapa.extract_bill_id(results[0]) == "111122223333"
    assert results[1]["subscription_id"] == ""


def test_providers_fixture_loads_real_list():
    client = make_client({saapa.PROVIDERS_PATH: "providers.json"})
    providers = run(client.providers())
    assert len(providers) > 20
    assert saapa.match_providers(providers, "تهران")


def test_normalize_mobile_variants():
    assert saapa.normalize_mobile("+98 912 345 6789") == "09123456789"
    assert saapa.normalize_mobile("۰۰۹۸۹۱۲۳۴۵۶۷۸۹") == "09123456789"
    assert saapa.normalize_mobile("9123456789") == "09123456789"
