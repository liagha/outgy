# outgy

Telegram bot + CLI that tracks **planned power outages** in Iran via the **برق من** (Bargh-e Man) service and alerts you on Telegram before each cut.

Persian-language alerts with Jalali dates: day, time span, address, outage code. You subscribe once; outgy polls in the background and only messages you when something *new* appears.

## Features

- `/login` — OTP login with your bargheman account (mobile + SMS code), no tokens to hunt down
- Bill discovery without paperwork:
  - bills already linked to your account are listed automatically → tap yours
  - `/meter` — find your subscription by province + **meter body number** (شماره بدنه کنتور)
  - or just paste a bill ID (شناسه قبض) directly
- Encrypted storage (Fernet) of tokens & bill IDs; dedup so you never get repeat alerts
- Full CLI mirror of every flow (`login`, `bills`, `find`, `check`)
- Tehran-timezone-aware Jalali date windows

## Setup

```bash
uv sync
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN from @BotFather
uv run outgy run
```

| Variable | Default | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — | required, from [@BotFather](https://t.me/BotFather) |
| `SAAPA_API_BASE` | `https://uiapi.saapa.ir` | API base (see geo-block note below) |
| `POLL_INTERVAL` | `900` | seconds between poll cycles |
| `ANNOUNCE_DAYS` | `3` | days ahead to watch |
| `OUTGY_DB` | `outgy.json` | state file |

> `uiapi.saapa.ir` is reachable **only from inside Iran**. Host the bot on an Iranian VPS or set `SAAPA_API_BASE` to a proxy inside Iran. Requests with an `Origin` header are rejected by their edge — outgy deliberately sends none.

### Finding your bill ID

The برق من API identifies subscriptions by bill ID / meter serial / parcel code / subscription ID — nothing else works (no address or postal-code lookup exists). If you don't know your bill ID:

1. `/login` first; if any bills are linked to your phone number they appear as buttons
2. `/meter` + the serial printed on your electricity meter's plaque
3. Call **121**, give your address, ask for شناسه قبض
4. Ask the landlord / check any old payment receipt

Ownership is never checked — anyone with a valid token can track any bill ID.

## CLI

```bash
uv run outgy login                        # interactive OTP; stores SAAPA_TOKEN in .env
uv run outgy bills                        # list bills linked to your account
uv run outgy find تهران بزرگ 12345678     # province + meter body number
uv run outgy check 1234567890123 --days 7 # upcoming outages for one bill
```

## How it works

```
Telegram users ──▶ bot.py (/start, /login, /meter, /status, /stop, bill ID)
                     │                        ▲ alerts via bot.send_message
                     ▼                        │
                  store.py ── Fernet-encrypted users, tokens, dedup state (outgy.json)
                     │
                     ▼
poller.py ── every POLL_INTERVAL: for each subscriber ──▶ saapa.py ──▶ uiapi.saapa.ir
```

Discovered برق من endpoints (reverse-engineered from the official app; may change without notice):

| Endpoint | Purpose |
| --- | --- |
| `POST /api/otp/sendCode` · `verifyCode` | mobile OTP login |
| `GET /api/ebills/GetBills` | bills + profile of logged-in account |
| `GET /api/providers/list` · `cities?code=` | distribution companies / cities |
| `POST /api/ebills/SearchBranchData` | find subscription by meter serial (`search_type=2`) |
| `POST /api/branch/search` | subscriptions registered to a mobile |
| `POST /api/ebills/PlannedBlackoutsReport` | scheduled outages per bill ID |

Known limits: tokens expire (users get a re-login prompt), OTP rate limits apply, unplanned-outage data (`BlackoutsReport`) isn't integrated yet, and postal-code lookup simply doesn't exist upstream.

## Layout

- `src/outgy/text.py` — Persian/Arabic ↔ Latin digit conversion
- `src/outgy/dates.py` — Tehran-time Jalali calendar helpers (today, windows, parsing)
- `src/outgy/outage.py` — typed outage record parsed from برق من rows
- `src/outgy/saapa.py` — برق من API client (auth, discovery, outages)
- `src/outgy/store.py` — encrypted subscription store + announced-outage dedup
- `src/outgy/bot.py` — Telegram handlers & conversations
- `src/outgy/poller.py` — polling/alerting daemon loop
- `src/outgy/format.py` — English CLI + Persian HTML renderers
- `src/outgy/config.py`, `src/outgy/__main__.py` — settings & CLI entrypoint

## License

MIT
