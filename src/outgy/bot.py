import asyncio
import logging
from enum import IntEnum, auto

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from . import format
from .outage import Outage
from .saapa import (
    BILL_ID_RE,
    MOBILE_RE,
    OTP_CODE_RE,
    SaapaAuthError,
    SaapaClient,
    SaapaError,
    SaapaRejected,
    bill_label,
    extract_bill_id,
    match_providers,
    normalize_mobile,
    normalize_name,
    provider_code,
    provider_name,
)
from .store import Store
from .text import digits_only

logger = logging.getLogger(__name__)


class State(IntEnum):
    PHONE = auto()
    CODE = auto()
    PROVINCE = auto()
    SERIAL = auto()


WELCOME = (
    "👋 سلام!\n"
    "من ربات اطلاع‌رسانی خاموشی برق هستم و از طریق سامانه «برق من» برنامه‌ی خاموشی‌های "
    "اشتراک شما را دنبال می‌کنم.\n\n"
    "۱️⃣ با /login وارد حساب «برق من» شوید (فقط شماره موبایل + کد پیامکی)\n"
    "۲️⃣ قبض خود را انتخاب کنید — حتی اگر <b>شناسه قبض ندارید</b>!\n"
    "شناسه را دستی بفرستید یا با /meter فقط با شماره بدنه کنتور پیدایش کنید.\n\n"
    "/status — وضعیت اشتراک و خاموشی‌های پیش‌رو\n"
    "/stop — لغو اشتراک"
)

NEED_LOGIN = "اول باید وارد حساب «برق من» شوید: /login"

LOGIN_ASK_PHONE = (
    "📱 شماره موبایلِ حساب «برق من» خود را بفرستید.\n"
    "(همان شماره‌ای که در اپلیکیشن برق من با آن وارد می‌شوید)\n\n"
    "/cancel — انصراف"
)

LOGIN_BAD_PHONE = "❌ شماره معتبر نیست. مثال: 09123456789"

OTP_SENT = "📨 کد پیامک‌شده به شماره‌اتان را بفرستید:\n\n/cancel — انصراف"

LOGIN_BAD_CODE = "❌ کد معتبر نیست، دوباره بفرستید:"

LOGIN_DONE = "✅ وارد شدید!"

LOGIN_BILLS_ASK = (
    "{done}\nکدام قبض مال شماست؟ (اگر قبضی در فهرست نیست، شناسه قبض را دستی بفرستید "
    "یا با /meter از روی کنتور پیدایش کنید)"
)

LOGIN_NOBILLS = (
    "{done}\nحالا شناسه قبض برق را بفرستید.\n"
    "شناسه قبض ندارید؟ با /meter می‌توانم فقط با <b>شماره بدنه کنتور</b> و استانتان پیدایش کنم."
)

METER_ASK_PROVINCE = (
    "🔎 نام <b>استان</b> محل انشعاب را بفرستید (مثلاً: تهران، اصفهان):\n\n/cancel — انصراف"
)

METER_PROVINCE_NOT_FOUND = "استانی با این نام پیدا نشد. لطفاً دقیق‌تر بفرستید:"

METER_PICK_PROVINCE = "چند مورد پیدا شد؛ استان را انتخاب کنید:"

METER_ASK_SERIAL = (
    "🔢 حالا <b>شماره بدنه کنتور</b> را بفرستید.\n"
    "(روی پلاک کنتور برق منزل نوشته شده)\n\n/cancel — انصراف"
)

METER_NO_RESULT = (
    "❌ با این شماره بدنه در این استان اشتراکی پیدا نشد.\n"
    "شماره را دوباره بررسی کنید یا /meter را با استان درست تکرار کنید."
)

PICKED_BILL = (
    "✅ شناسه قبض <code>{bill}</code> ثبت شد.\nاز این به بعد خاموشی‌های جدید را همین‌جا اعلام می‌کنم."
)

LOGIN_FAILED = "⚠️ ورود ناموفق بود: {reason}\nدوباره تلاش کنید: /login"

LOGGED_OUT = "از حساب خارج شدید."

NOT_A_BILL = "لطفاً فقط <b>شناسه قبض</b> برق (عدد روی قبض) را بفرستید."

INVALID_BILL = "❌ این شناسه قبض در سامانه «برق من» پیدا نشد. لطفاً دوباره بررسی کنید."

SERVICE_DOWN = "⚠️ سرویس «برق من» در دسترس نیست، چند لحظه بعد دوباره امتحان کنید."

TOKEN_EXPIRED = "🔑 ورود شما به «برق من» منقضی شده است. لطفاً دوباره /login کنید."

REGISTERED = (
    "✅ شناسه قبض <code>{bill}</code> ثبت شد.\n"
    "از این به بعد خاموشی‌های جدید را همین‌جا اعلام می‌کنم."
)

UNREGISTERED = "اشتراکی برای شما ثبت نشده بود."

STOPPED = "اشتراک و حساب شما پاک شد. برای شروع مجدد /login و سپس ارسال شناسه قبض."


def _mask(bill_id: str) -> str:
    if len(bill_id) <= 7:
        return bill_id
    return bill_id[:4] + "*" * (len(bill_id) - 7) + bill_id[-3:]


def _bill_buttons(bills: list[dict]) -> list[list[InlineKeyboardButton]]:
    buttons = []
    seen: set[str] = set()
    for item in bills:
        bill_id = extract_bill_id(item)
        if not bill_id or bill_id in seen:
            continue
        seen.add(bill_id)
        label = bill_label(item) or _mask(bill_id)
        buttons.append([InlineKeyboardButton(label[:48], callback_data=f"bill:{bill_id}")])
    return buttons


def _province_buttons(providers: list[dict]) -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(
                provider_name(p)[:48] or "?",
                callback_data=f"mprov:{provider_code(p)}:{provider_name(p)[:24]}",
            )
        ]
        for p in providers[:10]
    ]


def _deps(context: ContextTypes.DEFAULT_TYPE) -> tuple[Store, SaapaClient, int]:
    data = context.application.bot_data
    return data["store"], data["saapa"], data["settings"].announce_days


async def _lookup(
    saapa: SaapaClient, token: str, bill_id: str, announce_days: int
) -> list[Outage]:
    return await saapa.planned_blackouts(bill_id, max(announce_days, 7), token=token)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(WELCOME)


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> State:
    await update.message.reply_html(LOGIN_ASK_PHONE)
    return State.PHONE


async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> State | int:
    store, saapa, _ = _deps(context)
    mobile = normalize_mobile(update.message.text or "")
    if not MOBILE_RE.match(mobile):
        await update.message.reply_text(LOGIN_BAD_PHONE)
        return State.PHONE
    try:
        await saapa.send_otp(mobile)
    except SaapaError as exc:
        logger.warning("otp send failed for chat %s: %s", update.effective_chat.id, exc)
        await update.message.reply_text(LOGIN_FAILED.format(reason="سرویس در دسترس نیست"))
        return ConversationHandler.END
    context.user_data["mobile"] = mobile
    await update.message.reply_text(OTP_SENT)
    return State.CODE


async def login_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> State | int:
    store, saapa, _ = _deps(context)
    chat_id = update.effective_chat.id
    code = digits_only(update.message.text or "")
    if not OTP_CODE_RE.match(code):
        await update.message.reply_text(LOGIN_BAD_CODE)
        return State.CODE
    mobile = context.user_data.get("mobile")
    if not mobile:
        await update.message.reply_text(NEED_LOGIN)
        return ConversationHandler.END
    try:
        token = await saapa.verify_otp(mobile, code)
    except SaapaRejected as exc:
        logger.info("otp verify rejected for chat %s: %s", chat_id, exc)
        await update.message.reply_text("❌ کد اشتباه یا منقضی شده، دوباره بفرستید:")
        return State.CODE
    except SaapaError as exc:
        logger.warning("otp verify failed for chat %s: %s", chat_id, exc)
        await update.message.reply_text(LOGIN_FAILED.format(reason="سرویس در دسترس نیست"))
        return ConversationHandler.END
    await asyncio.to_thread(store.set_token, chat_id, token)
    context.user_data.pop("mobile", None)
    try:
        bills = await saapa.get_bills(token=token)
    except SaapaError as exc:
        logger.info("get_bills failed for chat %s: %s", chat_id, exc)
        bills = []
    buttons = _bill_buttons(bills)
    if buttons:
        await update.message.reply_html(
            LOGIN_BILLS_ASK.format(done=LOGIN_DONE),
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    else:
        await update.message.reply_html(LOGIN_NOBILLS.format(done=LOGIN_DONE))
    return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("mobile", None)
    await update.message.reply_text("انصراف داده شد.")
    return ConversationHandler.END


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store, _, _ = _deps(context)
    await asyncio.to_thread(store.clear_token, update.effective_chat.id)
    await update.message.reply_text(LOGGED_OUT)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store, _, _ = _deps(context)
    chat_id = update.effective_chat.id
    if await asyncio.to_thread(store.remove_user, chat_id):
        await update.message.reply_text(STOPPED)
    else:
        await update.message.reply_text(UNREGISTERED)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store, saapa, announce_days = _deps(context)
    chat_id = update.effective_chat.id
    token = await asyncio.to_thread(store.get_token, chat_id)
    bill_id = await asyncio.to_thread(store.get_bill, chat_id)
    if not token or not bill_id:
        await update.message.reply_html(WELCOME)
        return
    try:
        outages = await _lookup(saapa, token, bill_id, announce_days)
    except SaapaAuthError:
        await update.message.reply_text(TOKEN_EXPIRED)
        return
    except SaapaError as exc:
        logger.warning("status lookup failed for chat %s: %s", chat_id, exc)
        await update.message.reply_text(SERVICE_DOWN)
        return
    header = f"🔎 اشتراک شما: <code>{_mask(bill_id)}</code>\n\n"
    await update.message.reply_html(header + format.html(outages))


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store, saapa, announce_days = _deps(context)
    chat_id = update.effective_chat.id
    bill_id = digits_only(update.message.text or "")
    if not BILL_ID_RE.match(bill_id):
        await update.message.reply_html(NOT_A_BILL)
        return
    token = await asyncio.to_thread(store.get_token, chat_id)
    if not token:
        await update.message.reply_html(NEED_LOGIN)
        return
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        outages = await _lookup(saapa, token, bill_id, announce_days)
    except SaapaRejected:
        await update.message.reply_html(INVALID_BILL)
        return
    except SaapaAuthError:
        await update.message.reply_text(TOKEN_EXPIRED)
        return
    except SaapaError as exc:
        logger.warning("verification failed for chat %s: %s", chat_id, exc)
        await update.message.reply_text(SERVICE_DOWN)
        return
    await asyncio.to_thread(store.set_bill, chat_id, bill_id)
    await update.message.reply_html(
        REGISTERED.format(bill=_mask(bill_id)) + "\n\n" + format.html(outages)
    )


async def on_bill_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    bill_id = query.data.removeprefix("bill:")
    if not BILL_ID_RE.match(bill_id):
        await query.answer("شناسه نامعتبر است", show_alert=True)
        return
    await query.answer()
    store: Store = context.application.bot_data["store"]
    await asyncio.to_thread(store.set_bill, update.effective_chat.id, bill_id)
    await query.edit_message_text(PICKED_BILL.format(bill=_mask(bill_id)))


async def meter_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> State | int:
    store, _, _ = _deps(context)
    token = await asyncio.to_thread(store.get_token, update.effective_chat.id)
    if not token:
        await update.message.reply_html(NEED_LOGIN)
        return ConversationHandler.END
    await update.message.reply_html(METER_ASK_PROVINCE)
    return State.PROVINCE


async def meter_province_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> State | int:
    store, saapa, _ = _deps(context)
    needle = (update.message.text or "").strip()
    providers = context.user_data.get("providers")
    if providers is None:
        try:
            providers = await saapa.providers()
        except SaapaError as exc:
            logger.warning("providers failed: %s", exc)
            await update.message.reply_text(SERVICE_DOWN)
            return ConversationHandler.END
        context.user_data["providers"] = providers
    matches = match_providers(providers, needle) if needle else []
    if not matches:
        await update.message.reply_text(METER_PROVINCE_NOT_FOUND)
        return State.PROVINCE
    if len(matches) == 1:
        chosen = matches[0]
        context.user_data["co_code"] = provider_code(chosen)
        await update.message.reply_html(
            f"استان: <b>{provider_name(chosen)}</b>\n\n{METER_ASK_SERIAL}"
        )
        return State.SERIAL
    await update.message.reply_text(
        METER_PICK_PROVINCE,
        reply_markup=InlineKeyboardMarkup(_province_buttons(matches)),
    )
    return State.PROVINCE


async def meter_province_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> State:
    query = update.callback_query
    await query.answer()
    code, _, label = query.data.removeprefix("mprov:").partition(":")
    context.user_data["co_code"] = code
    await query.edit_message_text(f"استان: {label}")
    await query.message.reply_html(METER_ASK_SERIAL)
    return State.SERIAL


async def meter_serial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> State | int:
    store, saapa, _ = _deps(context)
    chat_id = update.effective_chat.id
    serial = digits_only(update.message.text or "")
    if not 3 <= len(serial) <= 20:
        await update.message.reply_text("❌ شماره بدنه فقط عدد است، دوباره بفرستید:")
        return State.SERIAL
    token = await asyncio.to_thread(store.get_token, chat_id)
    co_code = context.user_data.get("co_code")
    if not token or not co_code:
        await update.message.reply_html(NEED_LOGIN)
        return ConversationHandler.END
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        results = await saapa.search_branch(
            search_type=2,
            co_code=co_code,
            serial_number=serial,
            token=token,
        )
    except SaapaAuthError:
        await update.message.reply_text(TOKEN_EXPIRED)
        return ConversationHandler.END
    except SaapaError as exc:
        logger.warning("search_branch failed for chat %s: %s", chat_id, exc)
        await update.message.reply_text(SERVICE_DOWN)
        return ConversationHandler.END
    finally:
        context.user_data.pop("co_code", None)
    buttons = _bill_buttons(results)
    if not buttons:
        await update.message.reply_text(METER_NO_RESULT)
        return ConversationHandler.END
    await update.message.reply_text(
        "این‌ها را پیدا کردم؛ قبض خودتان را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ConversationHandler.END


def register_handlers(app: Application) -> None:
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            State.PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_phone)],
            State.CODE: [
                CommandHandler("cancel", login_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_code),
            ],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
    )
    meter_conv = ConversationHandler(
        entry_points=[CommandHandler("meter", meter_start)],
        states={
            State.PROVINCE: [
                CallbackQueryHandler(meter_province_pick, pattern=r"^mprov:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, meter_province_text),
            ],
            State.SERIAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, meter_serial)],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(login_conv)
    app.add_handler(meter_conv)
    app.add_handler(CallbackQueryHandler(on_bill_pick, pattern=r"^bill:"))
    app.add_handler(CommandHandler("logout", cmd_logout))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
