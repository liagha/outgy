import argparse
import asyncio
import logging
from pathlib import Path

import httpx

from . import format
from .config import Settings
from .saapa import (
    BILL_ID_RE,
    MOBILE_RE,
    SaapaClient,
    SaapaError,
    SaapaRejected,
    bill_label,
    extract_bill_id,
    match_providers,
    normalize_mobile,
    provider_code,
    provider_name,
)
from .text import digits_only

logger = logging.getLogger(__name__)


def _parse_args() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser(
        prog="outgy",
        description="Telegram bot tracking power outages via Bargh-e Man (برق من)",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="start the Telegram bot daemon")
    sub.add_parser(
        "login",
        help="OTP login with your bargheman account; stores SAAPA_TOKEN in .env",
    )
    sub.add_parser("bills", help="list bills linked to your bargheman account")

    p_find = sub.add_parser(
        "find", help="find your bill ID by province + meter body number"
    )
    p_find.add_argument("province", help="e.g. تهران")
    p_find.add_argument("serial", help="meter body number printed on the meter plaque")

    p_check = sub.add_parser("check", help="show upcoming outages for a bill ID and exit")
    p_check.add_argument("bill_id")
    p_check.add_argument("--days", type=int, default=7)

    return parser, parser.parse_args()


def _save_token_to_env(token: str) -> Path:
    path = Path(".env")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out = []
    replaced = False
    for line in lines:
        if line.strip().startswith("SAAPA_TOKEN="):
            out.append(f"SAAPA_TOKEN={token}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(f"SAAPA_TOKEN={token}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def _print_bills(bills: list[dict]) -> None:
    found = False
    for item in bills:
        bill_id = extract_bill_id(item)
        label = bill_label(item)
        if not bill_id:
            continue
        found = True
        suffix = f"  {label}" if label else ""
        print(f"  {bill_id}  {suffix}")
    if not found:
        print("  (no bills with a recognizable bill ID)")
        print("  try: uv run outgy find <PROVINCE> <METER_SERIAL>")


async def _cli_login(settings: Settings) -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        saapa = SaapaClient(http, settings.saapa_base_url)
        while True:
            mobile = normalize_mobile(input("mobile (09xxxxxxxxx): "))
            if MOBILE_RE.match(mobile):
                break
            print("invalid mobile number, try again")
        await saapa.send_otp(mobile)
        print(f"sms code sent to {mobile}")
        token = None
        for _ in range(3):
            code = digits_only(input("code: "))
            try:
                token = await saapa.verify_otp(mobile, code)
                break
            except SaapaRejected:
                print("wrong or expired code, try again:")
        if not token:
            raise SystemExit("login failed after 3 attempts")
        try:
            bills = await saapa.get_bills(token=token)
        except SaapaError as exc:
            logger.warning("get_bills failed: %s", exc)
            bills = []
    path = _save_token_to_env(token)
    print(f"logged in; SAAPA_TOKEN saved to {path}")
    if bills:
        print("bills linked to your account:")
        _print_bills(bills)


async def _cli_bills(settings: Settings) -> None:
    if not settings.saapa_token:
        raise SystemExit("not logged in — run: uv run outgy login")
    async with httpx.AsyncClient(timeout=30) as http:
        saapa = SaapaClient(http, settings.saapa_base_url)
        try:
            bills = await saapa.get_bills(token=settings.saapa_token)
        except SaapaError as exc:
            raise SystemExit(f"failed: {exc}")
    _print_bills(bills)


async def _cli_find(settings: Settings, province: str, serial: str) -> None:
    if not settings.saapa_token:
        raise SystemExit("not logged in — run: uv run outgy login")
    serial = digits_only(serial)
    if not 3 <= len(serial) <= 20:
        raise SystemExit("meter body number must be 3-20 digits")
    async with httpx.AsyncClient(timeout=30) as http:
        saapa = SaapaClient(http, settings.saapa_base_url)
        try:
            providers = await saapa.providers()
            matches = match_providers(providers, province)
            if not matches:
                raise SystemExit(f"no distribution company matches '{province}'")
            if len(matches) == 1:
                chosen = matches[0]
            else:
                for i, p in enumerate(matches[:10], 1):
                    print(f"  {i}. {provider_name(p)} ({provider_code(p)})")
                idx = input("which one? [1]: ").strip() or "1"
                chosen = matches[int(idx) - 1]
            co_code = provider_code(chosen)
            print(f"searching {provider_name(chosen)} (co_code={co_code}) for meter {serial}...")
            results = await saapa.search_branch(
                search_type=2,
                co_code=co_code,
                serial_number=serial,
                token=settings.saapa_token,
            )
        except SaapaError as exc:
            raise SystemExit(f"failed: {exc}")
    if not results:
        raise SystemExit(
            "nothing found for this meter number in that province — check the "
            "serial on the meter plaque and that the province matches the meter's location"
        )
    print("found subscriptions:")
    _print_bills(results)
    print("now: uv run outgy check <BILL_ID>")


async def _cli_check(settings: Settings, bill_id: str, days: int) -> None:
    if not settings.saapa_token:
        raise SystemExit("SAAPA_TOKEN is missing — run: uv run outgy login")
    async with httpx.AsyncClient(timeout=30) as http:
        saapa = SaapaClient(http, settings.saapa_base_url)
        try:
            outages = await saapa.planned_blackouts(bill_id, days, token=settings.saapa_token)
        except SaapaRejected as exc:
            raise SystemExit(f"bargh-e man rejected this bill ID: {exc}")
        except SaapaError as exc:
            raise SystemExit(f"saapa request failed: {exc}")
    print(format.plain(outages))


async def _post_init(app) -> None:
    settings: Settings = app.bot_data["settings"]
    http = httpx.AsyncClient(timeout=30)
    app.bot_data["http"] = http
    app.bot_data["saapa"] = SaapaClient(http, settings.saapa_base_url)
    app.bot_data["poller"] = app.create_task(run_poller(app))


async def _post_shutdown(app) -> None:
    task = app.bot_data.pop("poller", None)
    if task:
        task.cancel()
    http = app.bot_data.pop("http", None)
    if http:
        await http.aclose()


def _run_bot(settings: Settings) -> None:
    from telegram.ext import Application

    from .bot import register_handlers
    from .store import Store

    store = Store(settings.db_path)
    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data["settings"] = settings
    app.bot_data["store"] = store
    register_handlers(app)
    logger.info(
        "outgy starting (db=%s, poll_interval=%ss)", settings.db_path, settings.poll_interval
    )
    app.run_polling(allowed_updates=["message"])


def main() -> None:
    parser, args = _parse_args()
    command = args.command or "run"

    if command == "run":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        settings = Settings.load()
        _run_bot(settings)
        return

    logging.basicConfig(level=logging.WARNING)
    settings = Settings.load(bot_token_required=False)
    if command == "login":
        asyncio.run(_cli_login(settings))
    elif command == "bills":
        asyncio.run(_cli_bills(settings))
    elif command == "find":
        asyncio.run(_cli_find(settings, args.province, args.serial))
    elif command == "check":
        bill_id = digits_only(args.bill_id.strip())
        if not BILL_ID_RE.match(bill_id):
            raise SystemExit("bill ID must be 8-18 digits")
        asyncio.run(_cli_check(settings, bill_id, args.days))
