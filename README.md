# outgy

Track your power outages with **Bargh-e Man** — **برق من**.

A Telegram bot + CLI that watches برق من for planned cuts at your place and messages you before they happen. Persian alerts with Jalali dates; subscribe once, get told only when something new shows up.

## Setup

```bash
uv sync
cp .env.example .env   # fill TELEGRAM_BOT_TOKEN from @BotFather
uv run outgy run
```

| Variable | Default | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — | required, from [@BotFather](https://t.me/BotFather) |
| `SAAPA_API_BASE` | `https://uiapi.saapa.ir` | API base (must be reachable from Iran) |
| `POLL_INTERVAL` | `900` | seconds between poll cycles |
| `ANNOUNCE_DAYS` | `3` | days ahead to watch |
| `OUTGY_DB` | `outgy.json` | state file |

In the bot: `/login` with your mobile + SMS code, pick your bill (or find it with `/meter` using the number on your meter), done.

## CLI

```bash
uv run outgy login                        # OTP login; stores SAAPA_TOKEN in .env
uv run outgy bills                        # list bills linked to your account
uv run outgy find تهران بزرگ 12345678     # province + meter body number
uv run outgy check 111122223333 --days 7  # upcoming outages for one bill
```

## API

The برق من endpoints are reverse-engineered from the official app and can change anytime — see [docs/ENDPOINTS.md](docs/ENDPOINTS.md). Requests only work from inside Iran. Unplanned-outage data isn't covered yet.

## Layout

- `src/outgy/text.py` — Persian/Arabic ↔ Latin digit conversion
- `src/outgy/dates.py` — Tehran-time Jalali calendar helpers
- `src/outgy/outage.py` — typed outage record parsed from API rows
- `src/outgy/saapa.py` — برق من API client
- `src/outgy/store.py` — encrypted subscription store + dedup
- `src/outgy/bot.py` — Telegram handlers & conversations
- `src/outgy/poller.py` — polling/alerting loop
- `src/outgy/format.py` — English CLI + Persian HTML renderers
- `tests/` — pytest suite with recorded API fixtures

## License

MIT
