import asyncio
import os
import re
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.error import RetryAfter, TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# =========================================================
# SOZLAMALAR
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Kassirning Telegram ID raqami
CASHIER_ID = int(os.environ.get("CASHIER_ID", "0"))

# Kirim va xarajat xabarlari boradigan odamning Telegram ID raqami
REPORT_CHAT_ID = int(os.environ.get("REPORT_CHAT_ID", "0"))

DB_PATH = Path(__file__).with_name("kassa.db")

TZ = ZoneInfo("Asia/Tashkent")


# =========================================================
# HOLATLAR
# =========================================================

CHOOSE_CURRENCY, INCOME_AMOUNT, EXCHANGE_USD, EXCHANGE_UZS = range(4)
RESET_CONFIRM = 4
CARD_EXPENSE = 5
STATISTICS_PERIOD = 6

CARD_BUTTON = "💳 Karta"
CARD_EXPENSE_BUTTON = "💳 Kartadan"
STATISTICS_BUTTON = "📊 Statistika"
BACK_BUTTON = "⬅️ Asosiy menyu"
STATISTICS_PERIODS = {
    "📅 Bugun": ("today", "Bugun"),
    "🗓 Shu oy": ("month", "Shu oy"),
    "📋 Barcha vaqt": ("all", "Barcha vaqt"),
}


# =========================================================
# TUGMALAR
# =========================================================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["💰 Pul oldim", "💵 $ maydalash"],
        [CARD_EXPENSE_BUTTON, STATISTICS_BUTTON],
    ],
    resize_keyboard=True
)

CURRENCY_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🇺🇿 So'm", "🇺🇸 Dollar"],
        [CARD_BUTTON],
        ["⬅️ Bekor qilish"],
    ],
    resize_keyboard=True
)

CANCEL_KEYBOARD = ReplyKeyboardMarkup(
    [["⬅️ Bekor qilish"]],
    resize_keyboard=True
)

RESET_CONFIRM_TEXT = "✅ Ha, nolga tushirish"
RESET_KEYBOARD = ReplyKeyboardMarkup(
    [[RESET_CONFIRM_TEXT], ["⬅️ Bekor qilish"]],
    resize_keyboard=True
)

STATISTICS_KEYBOARD = ReplyKeyboardMarkup(
    [["📅 Bugun", "🗓 Shu oy"], ["📋 Barcha vaqt"], [BACK_BUTTON]],
    resize_keyboard=True
)


# =========================================================
# DATABASE
# =========================================================

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                currency TEXT NOT NULL,
                amount INTEGER NOT NULL,
                note TEXT,
                actor_id INTEGER,
                account TEXT NOT NULL DEFAULT 'cash'
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
        if "account" not in columns:
            # Eski operatsiyalar va qoldiqlar naqd hisobda saqlanadi.
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN account TEXT NOT NULL DEFAULT 'cash'"
            )


def now_text():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def add_transaction(kind, currency, amount, note="", actor_id=None, account="cash"):
    if account not in ("cash", "card") or (account == "card" and currency != "UZS"):
        raise ValueError("Noto'g'ri hisob yoki valyuta")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute(
            """
            INSERT INTO transactions
            (created_at, kind, currency, amount, note, actor_id, account)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_text(),
                kind,
                currency,
                amount,
                note,
                actor_id,
                account
            )
        )


class InsufficientCardFunds(Exception):
    def __init__(self, balance):
        self.balance = balance
        super().__init__("Kartadagi mablag' yetarli emas")


def add_card_expense(amount, note, actor_id=None):
    if amount <= 0:
        raise ValueError("Summa musbat bo'lishi kerak")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        balance = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
            "WHERE currency = 'UZS' AND account = 'card'"
        ).fetchone()[0]
        if amount > balance:
            raise InsufficientCardFunds(balance)
        conn.execute(
            "INSERT INTO transactions "
            "(created_at, kind, currency, amount, note, actor_id, account) "
            "VALUES (?, 'expense', 'UZS', ?, ?, ?, 'card')",
            (now_text(), -amount, note, actor_id)
        )


def add_exchange(usd_cents, uzs_amount, actor_id=None):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute(
            """
            INSERT INTO transactions
            (created_at, kind, currency, amount, note, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                now_text(),
                "exchange_out",
                "USD",
                -usd_cents,
                "Dollar maydalandi",
                actor_id
            )
        )

        conn.execute(
            """
            INSERT INTO transactions
            (created_at, kind, currency, amount, note, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                now_text(),
                "exchange_in",
                "UZS",
                uzs_amount,
                "Dollar maydalashdan olindi",
                actor_id
            )
        )


def get_balance(currency, account="cash"):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE currency = ? AND account = ?
            """,
            (currency, account)
        ).fetchone()

        return row[0]


def get_history(limit=10):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute(
            """
            SELECT created_at, kind, currency, amount, note, account
            FROM transactions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()


def get_statistics(period="all", now=None):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    conditions = "kind = 'expense'"
    params = []
    if period in ("today", "month"):
        begin = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "today":
            end = begin + timedelta(days=1)
        else:
            begin = begin.replace(day=1)
            end = (begin + timedelta(days=32)).replace(day=1)
        conditions += " AND created_at >= ? AND created_at < ?"
        params = [begin.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")]
    elif period != "all":
        raise ValueError("Noto'g'ri davr")

    totals = {"UZS": 0, "USD": 0}
    balances = {
        ("cash", "UZS"): 0,
        ("cash", "USD"): 0,
        ("card", "UZS"): 0,
    }
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN")
        expenses = conn.execute(
            "SELECT created_at, note, currency, -amount, account FROM transactions "
            f"WHERE {conditions} ORDER BY created_at ASC, id ASC", params
        ).fetchall()
        for _, _, currency, amount, _ in expenses:
            totals[currency] += amount
        for account, currency, amount in conn.execute(
            "SELECT account, currency, SUM(amount) FROM transactions GROUP BY account, currency"
        ):
            balances[(account, currency)] = amount
    return expenses, totals, balances


# =========================================================
# BAZANI NOLGA TUSHIRISH
# =========================================================

def reset_database():
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    backup_path = backup_dir / f"kassa-{datetime.now(TZ):%Y%m%d-%H%M%S-%f}.db"
    backup_path.touch(mode=0o600, exist_ok=False)

    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        # Zaxira olish va tozalash davomida boshqa yozuvlarni bloklaymiz.
        conn.execute("BEGIN IMMEDIATE")
        with closing(sqlite3.connect(DB_PATH)) as source:
            with closing(sqlite3.connect(backup_path)) as backup:
                source.backup(backup)
        conn.execute("DELETE FROM transactions")

    return backup_path


# =========================================================
# FORMATLASH
# =========================================================

def format_uzs(amount):
    return f"{amount:,}".replace(",", " ")


def format_usd(cents):
    value = Decimal(cents) / Decimal(100)

    if value == value.to_integral():
        return f"${int(value):,}"

    return f"${value:,.2f}"


def parse_uzs(text):
    cleaned = (
        text.lower()
        .replace("so'm", "")
        .replace("soʻm", "")
        .replace("som", "")
        .replace("uzs", "")
        .replace(" ", "")
        .replace(",", "")
        .replace(".", "")
        .replace("_", "")
        .replace("'", "")
    )

    value = int(cleaned)

    if value <= 0 or value > 9223372036854775807:
        raise ValueError

    return value


def parse_usd(text):
    cleaned = (
        text.lower()
        .replace("usd", "")
        .replace("$", "")
        .replace(" ", "")
        .replace(",", ".")
    )

    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", cleaned):
        raise ValueError

    value = Decimal(cleaned)
    if value <= 0 or value > Decimal("92233720368547758.07"):
        raise ValueError

    return int(value * 100)


def parse_income_text(text, currency):
    text = " ".join(text.split())
    parse_amount = parse_usd if currency == "USD" else parse_uzs
    amount_pattern = r"\$?\s*[+-]?[0-9][0-9.,_' ]*(?:\s*(?:\$|usd|uzs|so'm|soʻm|som))?"
    if re.fullmatch(amount_pattern, text, flags=re.IGNORECASE):
        return "", parse_amount(text)

    match = re.fullmatch(rf"(.+?)\s+({amount_pattern})", text, flags=re.IGNORECASE)
    if match is None:
        raise ValueError
    name, amount_text = match.groups()
    if len(name) > 200 or not any(char.isalpha() for char in name):
        raise ValueError
    return name, parse_amount(amount_text)


# =========================================================
# HUQUQ TEKSHIRISH
# =========================================================

def is_cashier(update: Update):
    return (
        update.effective_user
        and update.effective_user.id == CASHIER_ID
    )


async def reject_if_not_cashier(update: Update):
    if not is_cashier(update):
        await update.message.reply_text(
            "⛔ Bu bot faqat kassir uchun."
        )
        return True

    return False


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Boshqa odam ham /start bosishi mumkin,
    # shunda bot unga keyinchalik xabar yubora oladi.

    if not is_cashier(update):
        await update.message.reply_text(
            f"Telegram ID: {update.effective_user.id}"
        )
        return ConversationHandler.END

    context.chat_data.clear()

    await update.message.reply_text(
        "💼 Kassa bot\n\n"
        "Kerakli amalni tanlang:\n\n"
        "/hisob — qoldiq\n"
        "/tarix — oxirgi operatsiyalar\n"
        "/statistika — xarajatlar va qoldiqlar\n"
        "/reset — qoldiq va tarixni nolga tushirish",
        reply_markup=MAIN_KEYBOARD
    )
    return ConversationHandler.END


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Sizning Telegram ID'ingiz:\n"
        f"{update.effective_user.id}"
    )


# =========================================================
# KIRIM VA XARAJAT XABARLARI
# =========================================================

async def send_transaction_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    kind,
    currency,
    amount,
    account="cash",
    note="",
):
    if kind not in ("income", "expense"):
        return

    title = "🟢 YANGI KIRIM" if kind == "income" else "🔴 YANGI XARAJAT"
    sign = "➕" if kind == "income" else "➖"
    account_label = "💳 Karta" if account == "card" else "💵 Naqd dollar" if currency == "USD" else "💰 Naqd so'm"
    amount_text = format_usd(amount) if currency == "USD" else f"{format_uzs(amount)} so'm"
    lines = [title, "", f"Hisob: {account_label}"]
    if note:
        lines.append(f"📝 {note}")
    lines.extend([f"{sign} {amount_text}", f"🕐 {now_text()}"])

    try:
        await context.bot.send_message(chat_id=REPORT_CHAT_ID, text="\n".join(lines))
    except TelegramError as exc:
        operation = "Kirim" if kind == "income" else "Xarajat"
        await update.message.reply_text(
            f"⚠️ {operation} saqlandi, lekin hisobot boshqa odamga yuborilmadi.\n\n"
            "U odam botga /start bosganini va REPORT_CHAT_ID to'g'riligini tekshiring.",
            reply_markup=MAIN_KEYBOARD
        )
        print("Hisobotni yuborishda xato:", type(exc).__name__)


# =========================================================
# PUL OLDIM
# =========================================================

async def income_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    context.chat_data.clear()
    await update.message.reply_text(
        "Pulni qaysi hisobga oldingiz?",
        reply_markup=CURRENCY_KEYBOARD
    )

    return CHOOSE_CURRENCY


async def choose_currency(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    text = update.message.text

    if text == "🇺🇿 So'm":
        context.chat_data["income_currency"] = "UZS"
        context.chat_data["income_account"] = "cash"

        await update.message.reply_text(
            "💰 Kimdan va necha so'm oldingiz?\n\n"
            "Masalan:\n"
            "Alidan 500000",
            reply_markup=CANCEL_KEYBOARD
        )

        return INCOME_AMOUNT

    elif text == "🇺🇸 Dollar":
        context.chat_data["income_currency"] = "USD"
        context.chat_data["income_account"] = "cash"

        await update.message.reply_text(
            "💵 Kimdan va necha dollar oldingiz?\n\n"
            "Masalan:\n"
            "Alidan 300",
            reply_markup=CANCEL_KEYBOARD
        )

        return INCOME_AMOUNT

    elif text == CARD_BUTTON:
        context.chat_data["income_currency"] = "UZS"
        context.chat_data["income_account"] = "card"
        await update.message.reply_text(
            "💳 Kartaga necha so'm tushdi?\n\nMasalan: 500000",
            reply_markup=CANCEL_KEYBOARD
        )
        return INCOME_AMOUNT


async def income_amount(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    currency = context.chat_data.get("income_currency")
    account = context.chat_data.get("income_account", "cash")

    try:
        if account == "card":
            name, amount = "", parse_uzs(update.message.text)
        else:
            name, amount = parse_income_text(update.message.text, currency)
        source_note = f"Kimdan: {name}" if name else ""
        source_line = f"👤 {source_note}\n" if source_note else ""

        if currency == "UZS":

            add_transaction(
                "income",
                "UZS",
                amount,
                source_note or ("Kartaga pul olindi" if account == "card" else "Pul olindi"),
                update.effective_user.id,
                account=account
            )

            balance = get_balance("UZS", account=account)
            label = "💳 Karta qoldiq" if account == "card" else "💰 Naqd so'm qoldiq"

            await update.message.reply_text(
                "✅ Pul qabul qilindi\n\n"
                f"{source_line}"
                f"➕ {format_uzs(amount)} so'm\n"
                f"{label}: "
                f"{format_uzs(balance)} so'm",
                reply_markup=MAIN_KEYBOARD
            )

        else:

            add_transaction(
                "income",
                "USD",
                amount,
                source_note or "Dollar olindi",
                update.effective_user.id
            )

            balance = get_balance("USD")

            await update.message.reply_text(
                "✅ Dollar qabul qilindi\n\n"
                f"{source_line}"
                f"➕ {format_usd(amount)}\n"
                f"💵 Dollar qoldiq: "
                f"{format_usd(balance)}",
                reply_markup=MAIN_KEYBOARD
            )

        context.chat_data.clear()
        await send_transaction_report(
            update, context, "income", currency, amount, account=account, note=source_note
        )
        return ConversationHandler.END

    except (ValueError, InvalidOperation):
        example = "Alidan 300" if currency == "USD" else "Alidan 500000"
        guidance = "Kimdan olganingizni va summani to'g'ri yozing."
        if account == "card":
            example = "500000"
            guidance = "Summani to'g'ri kiriting."
        await update.message.reply_text(
            f"❌ {guidance}\n\nMasalan: {example}",
            reply_markup=CANCEL_KEYBOARD
        )

        return INCOME_AMOUNT


# =========================================================
# DOLLAR MAYDALASH
# =========================================================

async def exchange_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    context.chat_data.clear()
    usd_balance = get_balance("USD")

    await update.message.reply_text(
        "💵 Necha dollar maydalayapsiz?\n\n"
        f"Hozirgi dollar qoldiq: "
        f"{format_usd(usd_balance)}\n\n"
        "Masalan: 100",
        reply_markup=CANCEL_KEYBOARD
    )

    return EXCHANGE_USD


async def exchange_usd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:

        amount = parse_usd(update.message.text)

        current_balance = get_balance("USD")

        if amount > current_balance:
            await update.message.reply_text(
                "❌ Dollar yetarli emas.\n\n"
                f"Qoldiq: {format_usd(current_balance)}"
            )

            return EXCHANGE_USD

        context.chat_data["exchange_usd"] = amount

        await update.message.reply_text(
            f"💵 Maydalanmoqda: "
            f"{format_usd(amount)}\n\n"
            "🇺🇿 Necha so'm oldingiz?\n\n"
            "Masalan:\n"
            "1230000"
        )

        return EXCHANGE_UZS

    except (ValueError, InvalidOperation):

        await update.message.reply_text(
            "❌ Dollar miqdorini to'g'ri kiriting.\n"
            "Masalan: 100"
        )

        return EXCHANGE_USD


async def exchange_uzs(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:

        uzs_amount = parse_uzs(update.message.text)

        usd_amount = context.chat_data["exchange_usd"]

        add_exchange(
            usd_amount,
            uzs_amount,
            update.effective_user.id
        )

        usd_balance = get_balance("USD")
        uzs_balance = get_balance("UZS")

        dollar_value = Decimal(usd_amount) / Decimal(100)

        rate = Decimal(uzs_amount) / dollar_value

        await update.message.reply_text(
            "✅ Dollar maydalandi\n\n"
            f"💵 -{format_usd(usd_amount)}\n"
            f"🇺🇿 +{format_uzs(uzs_amount)} so'm\n\n"
            f"📊 Kurs: "
            f"{format_uzs(int(rate))} so'm\n\n"
            "QOLDIQ:\n"
            f"🇺🇿 {format_uzs(uzs_balance)} so'm\n"
            f"💵 {format_usd(usd_balance)}",
            reply_markup=MAIN_KEYBOARD
        )

        context.chat_data.clear()

        return ConversationHandler.END

    except (ValueError, InvalidOperation):

        await update.message.reply_text(
            "❌ So'm miqdorini to'g'ri kiriting.\n\n"
            "Masalan: 1230000"
        )

        return EXCHANGE_UZS


# =========================================================
# XARAJAT
# =========================================================

def parse_expense_text(text):
    text = text.strip()
    currency = "USD" if text.endswith("$") else "UZS"
    if currency == "USD":
        text = text[:-1].rstrip()
    parts = text.rsplit(maxsplit=1)
    if len(parts) != 2:
        raise ValueError
    name = " ".join(parts[0].split())
    if not name or len(name) > 200:
        raise ValueError
    amount = parse_usd(parts[1]) if currency == "USD" else parse_uzs(parts[1])
    return name, amount, currency


async def card_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    context.chat_data.clear()
    await update.message.reply_text(
        "💳 Kartadan xarajat\n\n"
        f"Karta qoldiq: {format_uzs(get_balance('UZS', 'card'))} so'm\n\n"
        "O'tkazmani amalga oshirgach, kimga yoki nima uchun "
        "va qancha yuborganingizni yozing.\n\n"
        "Masalan: Ali 200000",
        reply_markup=CANCEL_KEYBOARD
    )
    return CARD_EXPENSE


async def card_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await record_expense(update, context, account="card")


async def expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() in {
        "💰 Pul oldim", "💵 $ maydalash", "⬅️ Bekor qilish",
        "🇺🇿 So'm", "🇺🇸 Dollar", CARD_BUTTON, CARD_EXPENSE_BUTTON,
        STATISTICS_BUTTON, BACK_BUTTON, RESET_CONFIRM_TEXT, *STATISTICS_PERIODS,
    }:
        return
    return await record_expense(update, context, account="cash")


async def record_expense(update: Update, context: ContextTypes.DEFAULT_TYPE, account):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    retry_state = CARD_EXPENSE if account == "card" else ConversationHandler.END
    try:
        name, amount, currency = parse_expense_text(update.message.text)
    except (ValueError, InvalidOperation):
        await update.message.reply_text(
            "❌ Kimga yoki nima uchun va summani yozing:\n\n"
            "Ali 200000\nbenzin 150000\nFurnituraga 300$\n\n"
            "Dollarda kasrdan keyin ko'pi bilan 2 ta raqam yozing.\n"
            "Izoh 200 belgidan oshmasin.",
            reply_markup=CANCEL_KEYBOARD if account == "card" else MAIN_KEYBOARD
        )
        return retry_state

    if account == "card" and currency == "USD":
        await update.message.reply_text(
            "💳 Karta hisobi so'mda yuritiladi.\n\n"
            "Dollar xarajati uchun /cancel yuboring, keyin asosiy menyuda "
            "Furnituraga 300$ deb yozing.",
            reply_markup=CANCEL_KEYBOARD
        )
        return CARD_EXPENSE

    try:
        if account == "card":
            add_card_expense(amount, name, update.effective_user.id)
        else:
            add_transaction("expense", currency, -amount, name, update.effective_user.id)
    except InsufficientCardFunds as exc:
        await update.message.reply_text(
            "❌ Kartadagi mablag' yetarli emas.\n"
            f"Karta qoldiq: {format_uzs(exc.balance)} so'm\n\n"
            "Summani tekshiring yoki amalni bekor qiling.",
            reply_markup=CANCEL_KEYBOARD
        )
        return CARD_EXPENSE
    except (sqlite3.Error, OSError) as exc:
        print("Xarajatni saqlashda xato:", exc)
        await update.message.reply_text(
            "❌ Xarajat saqlanmadi. Qayta urinib ko'ring.",
            reply_markup=CANCEL_KEYBOARD if account == "card" else MAIN_KEYBOARD
        )
        return retry_state

    context.chat_data.clear()
    account_label = "💳 Karta" if account == "card" else "💵 Naqd dollar" if currency == "USD" else "💰 Naqd so'm"
    account_balance = get_balance(currency, account)
    amount_text = format_usd(amount) if currency == "USD" else f"{format_uzs(amount)} so'm"
    balance_text = format_usd(account_balance) if currency == "USD" else f"{format_uzs(account_balance)} so'm"
    await update.message.reply_text(
        "🔴 Xarajat yozildi\n\n"
        f"📝 {name}\n"
        f"Manba: {account_label}\n"
        f"➖ {amount_text}\n\n"
        f"{account_label} qoldiq: {balance_text}",
        reply_markup=MAIN_KEYBOARD
    )

    await send_transaction_report(
        update, context, "expense", currency, amount, account=account, note=name
    )
    return ConversationHandler.END


# =========================================================
# HISOB
# =========================================================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    context.chat_data.clear()
    uzs = get_balance("UZS")
    usd = get_balance("USD")
    card = get_balance("UZS", "card")

    await update.message.reply_text(
        "💼 KASSA HOLATI\n\n"
        f"🇺🇿 Naqd so'm: {format_uzs(uzs)} so'm\n"
        f"💵 Dollar: {format_usd(usd)}\n"
        f"💳 Karta: {format_uzs(card)} so'm",
        reply_markup=MAIN_KEYBOARD
    )
    return ConversationHandler.END


# =========================================================
# STATISTIKA
# =========================================================

async def statistics_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    context.chat_data.clear()
    await update.message.reply_text("Davrni tanlang:", reply_markup=STATISTICS_KEYBOARD)
    return STATISTICS_PERIOD


async def statistics_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    selection = STATISTICS_PERIODS.get(update.message.text)
    if selection is None:
        await update.message.reply_text(
            "Statistika davrini tanlang yoki asosiy menyuga qayting.",
            reply_markup=STATISTICS_KEYBOARD
        )
        return STATISTICS_PERIOD
    return await show_statistics(update, *selection)


def split_statistics_text(text, limit=4000):
    while text:
        size = 0
        end = 0
        last_newline = 0
        for char in text:
            width = 2 if ord(char) > 0xFFFF else 1
            if size + width > limit:
                break
            size += width
            end += 1
            if char == "\n":
                last_newline = end
        else:
            yield text
            return
        cut = last_newline or end
        chunk = text[:cut].rstrip("\n")
        if chunk:
            yield chunk
        text = text[cut:]


async def show_statistics(update: Update, period, label):
    expenses, totals, balances = get_statistics(period)
    lines = [f"📊 STATISTIKA — {label}", ""]
    if not expenses:
        lines.append("Bu davrda xarajat yo'q.")
    for index, (created_at, note, currency, amount, account) in enumerate(expenses, 1):
        amount_text = format_usd(amount) if currency == "USD" else f"{format_uzs(amount)} so'm"
        source = "karta" if account == "card" else "naqd"
        lines.append(f"{index}. {note or 'Nomsiz'} — {amount_text} ({source})\n{created_at[:16]}")

    summary = (
        "JAMI XARAJAT\n"
        f"So'm: {format_uzs(totals['UZS'])} so'm\n"
        f"Dollar: {format_usd(totals['USD'])}\n\n"
        "HOZIRGI QOLDIQ\n"
        f"Naqd so'm: {format_uzs(balances[('cash', 'UZS')])} so'm\n"
        f"Karta: {format_uzs(balances[('card', 'UZS')])} so'm\n"
        f"Dollar: {format_usd(balances[('cash', 'USD')])}"
    )
    chunks = list(split_statistics_text("\n".join(lines)))
    combined = chunks[-1] + "\n\n" + summary
    if len(combined.encode("utf-16-le")) // 2 <= 4000:
        chunks[-1] = combined
    else:
        chunks.append(summary)

    for chunk in chunks:
        while True:
            try:
                await update.message.reply_text(chunk, reply_markup=STATISTICS_KEYBOARD)
                break
            except RetryAfter as exc:
                delay = exc.retry_after
                if isinstance(delay, timedelta):
                    delay = delay.total_seconds()
                await asyncio.sleep(delay + 0.1)
    return STATISTICS_PERIOD


# =========================================================
# TARIX
# =========================================================

async def history(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    context.chat_data.clear()
    rows = get_history(10)

    if not rows:
        await update.message.reply_text(
            "Hozircha operatsiyalar yo'q.",
            reply_markup=MAIN_KEYBOARD
        )
        return ConversationHandler.END

    lines = ["📋 OXIRGI 10 TA OPERATSIYA\n"]

    for created_at, kind, currency, amount, note, account in rows:

        if kind == "income":
            icon = "🟢"

        elif kind == "expense":
            icon = "🔴"

        elif kind.startswith("exchange"):
            icon = "🔄"

        else:
            icon = "•"

        if currency == "UZS":
            amount_text = (
                f"{format_uzs(abs(amount))} so'm"
            )
        else:
            amount_text = format_usd(abs(amount))

        sign = "+" if amount > 0 else "-"

        lines.append(
            f"{icon} {note}\n"
            f"{'💳 Karta' if account == 'card' else '💵 Naqd'}\n"
            f"{sign}{amount_text}\n"
            f"{created_at}\n"
        )

    await update.message.reply_text(
        "\n".join(lines), reply_markup=MAIN_KEYBOARD
    )
    return ConversationHandler.END


# =========================================================
# NOLGA TUSHIRISH
# =========================================================

async def reset_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    context.chat_data.clear()
    await update.message.reply_text(
        "⚠️ Kassani nolga tushirish\n\n"
        "Naqd so'm, dollar va karta qoldiqlari 0 bo'ladi. "
        "Barcha kirim, xarajat va dollar maydalash tarixi tozalanadi.\n\n"
        "Tozalashdan oldin zaxira nusxasi saqlanadi.\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=RESET_KEYBOARD
    )
    return RESET_CONFIRM


async def reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    if update.message.text != RESET_CONFIRM_TEXT:
        await update.message.reply_text(
            "Nolga tushirish uchun tasdiqlash tugmasini bosing "
            "yoki amalni bekor qiling.",
            reply_markup=RESET_KEYBOARD
        )
        return RESET_CONFIRM

    try:
        reset_database()
    except (sqlite3.Error, OSError) as exc:
        print("Kassani nolga tushirishda xato:", exc)
        await update.message.reply_text(
            "❌ Kassani nolga tushirib bo'lmadi. Ma'lumotlar saqlandi.\n"
            "Qayta urinib ko'ring yoki amalni bekor qiling.",
            reply_markup=RESET_KEYBOARD
        )
        return RESET_CONFIRM

    context.chat_data.clear()
    await update.message.reply_text(
        "✅ Kassa nolga tushirildi.\n\n"
        "🇺🇿 So'm: 0 so'm\n"
        "💵 Dollar: $0\n"
        "💳 Karta: 0 so'm\n"
        "📋 Operatsiyalar tarixi tozalandi.\n\n"
        "Zaxira nusxasi saqlandi. Endi yangidan boshlashingiz mumkin.",
        reply_markup=MAIN_KEYBOARD
    )
    return ConversationHandler.END


# =========================================================
# BEKOR QILISH
# =========================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.chat_data.clear()

    await update.message.reply_text(
        "❌ Amal bekor qilindi.",
        reply_markup=MAIN_KEYBOARD
    )

    return ConversationHandler.END


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN sozlanmagan. .env faylini to'ldirib, sh run.sh buyrug'ini bajaring."
        )

    init_db()

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(False)
        .build()
    )

    conversation = ConversationHandler(

        entry_points=[
            CommandHandler("start", start),
            CommandHandler("hisob", balance),
            CommandHandler("tarix", history),
            CommandHandler(["statistika", "stats"], statistics_start),
            CommandHandler("kartadan", card_expense_start),
            CommandHandler("reset", reset_start),
            MessageHandler(filters.Regex("^💳 Kartadan$"), card_expense_start),
            MessageHandler(filters.Regex("^📊 Statistika$"), statistics_start),
            MessageHandler(filters.Regex("^⬅️ Asosiy menyu$"), start),
            MessageHandler(
                filters.Regex("^💰 Pul oldim$"),
                income_start
            ),

            MessageHandler(
                filters.Regex(r"^💵 \$ maydalash$"),
                exchange_start
            ),
        ],

        states={

            CARD_EXPENSE: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, card_expense),
            ],

            STATISTICS_PERIOD: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, statistics_period),
            ],

            RESET_CONFIRM: [
                MessageHandler(
                    filters.Regex("^⬅️ Bekor qilish$"),
                    cancel
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    reset_confirm
                ),
            ],

            CHOOSE_CURRENCY: [
                MessageHandler(
                    filters.Regex("^⬅️ Bekor qilish$"),
                    cancel
                ),
                MessageHandler(
                    filters.Regex(
                        r"^(🇺🇿 So'm|🇺🇸 Dollar|💳 Karta)$"
                    ),
                    choose_currency
                ),
            ],

            INCOME_AMOUNT: [
                MessageHandler(
                    filters.Regex("^⬅️ Bekor qilish$"),
                    cancel
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    income_amount
                ),
            ],

            EXCHANGE_USD: [
                MessageHandler(
                    filters.Regex("^⬅️ Bekor qilish$"),
                    cancel
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    exchange_usd
                ),
            ],

            EXCHANGE_UZS: [
                MessageHandler(
                    filters.Regex("^⬅️ Bekor qilish$"),
                    cancel
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    exchange_uzs
                ),
            ],
        },

        fallbacks=[
            CommandHandler("reset", reset_start),
            CommandHandler("cancel", cancel)
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("id", get_id))

    app.add_handler(conversation)

    # Oddiy yozilgan xabarlar = xarajat
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            expense
        )
    )

    print("BOT ISHLADI...")

    app.run_polling(
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
