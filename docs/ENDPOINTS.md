# برق من API endpoints (Bargh-e Man via Saapa)

Reverse-engineered from the official برق من app by watching its traffic to `https://uiapi.saapa.ir`.
Nothing here is official or documented upstream — endpoints, payloads, and field names can change without notice.

## Access requirements

- **Geo-fence**: `uiapi.saapa.ir` resolves and serves **only from inside Iran**. Host on an Iranian VPS or proxy through one.
- **No browser headers**: requests carrying an `Origin` header are rejected at their edge. Send none.
- **Auth**: every `/api/ebills/*` call needs `Authorization: Bearer <Token>` obtained through the OTP flow. Tokens expire silently (you get HTTP 401 once they do).
- **Rate limits**: aggressive polling gets throttled; expect HTTP 429.

## Response envelope

Every JSON body shares this shape:

```json
{
  "TimeStamp": 1756100000,
  "status": 200,
  "SessionKey": "...",
  "message": "",
  "data": {},
  "error": []
}
```

| Field | Meaning |
| --- | --- |
| `status` | application-level code; `200` = success |
| `data` | payload (object, list, or `null` depending on endpoint) |
| `error` | list of `{ "ErrorMsg": "..." }` on failures |

Transport-level signals: HTTP `401` = token expired/invalid, HTTP `429` = rate limited, HTTP 5xx = their side.

All dates are **Jalali** (`YYYY/MM/DD`, zero-padded), times are `HH:MM`. Digits may arrive as Persian (`۱۴۰۵/۰۶/۰۳`) or Latin (`1405/06/03`) — normalize both.

## OTP login

### 1. Send code

```
POST /api/otp/sendCode
{"mobile": "09123456789"}
```

Sends an SMS OTP. No auth required.

### 2. Verify code

```
POST /api/otp/verifyCode
{"mobile": "09123456789", "code": "123456", "request_source": 5, "device_token": ""}
```

Response: `data.Token` is the bearer token used everywhere else.

## Bills & discovery

### Bills linked to an account

```
GET /api/ebills/GetBills          (Bearer required)
```

`data` is an object whose values include bill lists plus `user_data` (profile with `mobile_number`). Bill entries carry identifiers such as `bill_identifier` and labels like `address`.

### Distribution companies (provinces)

```
GET /api/providers/list
```

`data` is a list of `{ "code": ..., "name": ... }` per distribution company (برق منطقه‌ای/توزیع).

### Cities of a distribution company

```
GET /api/providers/cities?code=<co_code>
```

### Find subscription by meter body number

```
POST /api/ebills/SearchBranchData
{
  "search_type": 2,
  "co_code": 111,
  "city_code": null,
  "phase": null,
  "file_serial_number": null,
  "subscription_id": null,
  "serial_number": "12345678"
}
```

`search_type=2` means meter-body-number search. Returns subscription rows containing bill IDs usable with the blackout report.

### Find subscriptions by mobile number

```
POST /api/branch/search
```

Subscriptions registered under a mobile. (Discovered from app traffic; not exercised by outgy.)

## Planned blackouts

```
POST /api/ebills/PlannedBlackoutsReport          (Bearer required)
{
  "bill_id": "6867380204326",
  "from_date": "1405/06/03",
  "to_date": "1405/06/10"
}
```

`data` is a list:

```json
[
  {
    "reg_date": "1405/06/03",
    "registrar": "setad",
    "reason_outage": "مديريت انرژي",
    "outage_date": "1405/06/03",
    "outage_time": "16:00",
    "outage_start_time": "16:00",
    "outage_stop_time": "18:00",
    "is_planned": true,
    "address": "حسن آباد سه راه اوج",
    "outage_address": "حسن آباد سه راه اوج",
    "city": 2,
    "outage_number": 405992407179,
    "tracking_code": 40599101756164
  }
]
```

Notes:

- `outage_number` may arrive as int or string; treat identifiers as strings after digit-normalizing.
- An empty `data` list can mean genuinely no scheduled outages **or** a transient gap on their side — re-check before trusting it.
- Unplanned/historical outages live under a different report (`BlackoutsReport`); not covered here yet.

## Quick curl session

```bash
BASE=https://uiapi.saapa.ir   # from inside Iran

curl -s $BASE/api/otp/sendCode -H 'Content-Type: application/json' \
  -d '{"mobile":"09123456789"}'

curl -s $BASE/api/otp/verifyCode -H 'Content-Type: application/json' \
  -d '{"mobile":"09123456789","code":"123456","request_source":5,"device_token":""}'
# -> data.Token

TOKEN=...

curl -s $BASE/api/ebills/GetBills -H "Authorization: Bearer $TOKEN"

curl -s $BASE/api/ebills/PlannedBlackoutsReport \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"bill_id":"6867380204326","from_date":"1405/06/03","to_date":"1405/06/10"}'
```
