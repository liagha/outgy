import asyncio
import logging

from telegram.ext import Application

from . import format
from .saapa import SaapaAuthError, SaapaClient, SaapaError
from .store import Store

logger = logging.getLogger(__name__)

STAGGER_SECONDS = 5.0


async def poll_once(app: Application) -> None:
    settings = app.bot_data["settings"]
    store: Store = app.bot_data["store"]
    saapa: SaapaClient = app.bot_data["saapa"]
    bot = app.bot

    for chat_id in store.user_ids():
        bill_id = await asyncio.to_thread(store.get_bill, chat_id)
        token = await asyncio.to_thread(store.get_token, chat_id)
        if not bill_id or not token:
            continue
        try:
            outages = await saapa.planned_blackouts(
                bill_id, settings.announce_days, token=token
            )
        except SaapaAuthError:
            logger.info("chat %s token expired", chat_id)
            try:
                await bot.send_message(chat_id, "🔑 ورود شما به «برق من» منقضی شده است. لطفاً دوباره /login کنید.")
            except Exception:
                pass
            await asyncio.sleep(STAGGER_SECONDS)
            continue
        except SaapaError as exc:
            logger.warning("poll failed for chat %s: %s", chat_id, exc)
            await asyncio.sleep(STAGGER_SECONDS)
            continue
        known = await asyncio.to_thread(store.announced_keys, chat_id)
        fresh = [o for o in outages if o.key not in known]
        if fresh:
            logger.info("chat %s: %d new outage(s)", chat_id, len(fresh))
            try:
                await bot.send_message(chat_id, format.html(fresh), parse_mode="HTML")
            except Exception as exc:
                logger.warning("send failed for chat %s: %s", chat_id, exc)
                await asyncio.sleep(STAGGER_SECONDS)
                continue
        await asyncio.to_thread(store.mark_announced, chat_id, [o.key for o in outages])
        await asyncio.sleep(STAGGER_SECONDS)


async def run_poller(app: Application) -> None:
    settings = app.bot_data["settings"]
    logger.info(
        "poller started (interval=%ss, users=%d)",
        settings.poll_interval,
        len(app.bot_data["store"].user_ids()),
    )
    while True:
        try:
            await poll_once(app)
        except Exception:
            logger.exception("poll cycle crashed")
        await asyncio.sleep(settings.poll_interval)
