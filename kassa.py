import os
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.error import TelegramError
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

# Xarajatlar boradigan odamning Telegram ID raqami
REPORT_CHAT_ID = int(os.environ.get("REPORT_CHAT_ID", "0"))

DB_PATH = Path(__file__).with_name("kassa.db")

TZ = ZoneInfo("Asia/Tashkent")


# =========================================================
# HOLATLAR
# =========================================================

CHOOSE_CURRENCY, INCOME_AMOUNT, EXCHANGE_USD, EXCHANGE_UZS = range(4)
RESET_CONFIRM = 4


# =========================================================
# TUGMALAR
# =========================================================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["💰 Pul oldim", "💵 $ maydalash"],
    ],
    resize_keyboard=True
)

CURRENCY_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🇺🇿 So'm", "🇺🇸 Dollar"],
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
                actor_id INTEGER
            )
        """)


def now_text():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def add_transaction(kind, currency, amount, note="", actor_id=None):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute(
            """
            INSERT INTO transactions
            (created_at, kind, currency, amount, note, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                now_text(),
                kind,
                currency,
                amount,
                note,
                actor_id
            )
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


def get_balance(currency):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE currency = ?
            """,
            (currency,)
        ).fetchone()

        return row[0]


def get_history(limit=10):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute(
            """
            SELECT created_at, kind, currency, amount, note
            FROM transactions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()


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

    if value <= 0:
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

    value = Decimal(cleaned)

    if value <= 0:
        raise ValueError

    cents = int(value * 100)

    return cents


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
        return

    await update.message.reply_text(
        "💼 Kassa bot\n\n"
        "Kerakli amalni tanlang:\n\n"
        "/hisob — qoldiq\n"
        "/tarix — oxirgi operatsiyalar\n"
        "/reset — qoldiq va tarixni nolga tushirish",
        reply_markup=MAIN_KEYBOARD
    )


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Sizning Telegram ID'ingiz:\n"
        f"{update.effective_user.id}"
    )


# =========================================================
# PUL OLDIM
# =========================================================

async def income_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    await update.message.reply_text(
        "Qaysi valyutada pul oldingiz?",
        reply_markup=CURRENCY_KEYBOARD
    )

    return CHOOSE_CURRENCY


async def choose_currency(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    text = update.message.text

    if text == "🇺🇿 So'm":
        context.user_data["income_currency"] = "UZS"

        await update.message.reply_text(
            "💰 Necha so'm oldingiz?\n\n"
            "Masalan:\n"
            "5000000",
            reply_markup=CANCEL_KEYBOARD
        )

        return INCOME_AMOUNT

    elif text == "🇺🇸 Dollar":
        context.user_data["income_currency"] = "USD"

        await update.message.reply_text(
            "💵 Necha dollar oldingiz?\n\n"
            "Masalan:\n"
            "500",
            reply_markup=CANCEL_KEYBOARD
        )

        return INCOME_AMOUNT


async def income_amount(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    currency = context.user_data.get("income_currency")

    try:

        if currency == "UZS":

            amount = parse_uzs(update.message.text)

            add_transaction(
                "income",
                "UZS",
                amount,
                "Pul olindi",
                update.effective_user.id
            )

            balance = get_balance("UZS")

            await update.message.reply_text(
                "✅ Pul qabul qilindi\n\n"
                f"➕ {format_uzs(amount)} so'm\n"
                f"💰 So'm qoldiq: "
                f"{format_uzs(balance)} so'm",
                reply_markup=MAIN_KEYBOARD
            )

        else:

            amount = parse_usd(update.message.text)

            add_transaction(
                "income",
                "USD",
                amount,
                "Dollar olindi",
                update.effective_user.id
            )

            balance = get_balance("USD")

            await update.message.reply_text(
                "✅ Dollar qabul qilindi\n\n"
                f"➕ {format_usd(amount)}\n"
                f"💵 Dollar qoldiq: "
                f"{format_usd(balance)}",
                reply_markup=MAIN_KEYBOARD
            )

        context.user_data.clear()

        return ConversationHandler.END

    except (ValueError, InvalidOperation):

        await update.message.reply_text(
            "❌ Summani to'g'ri kiriting.\n\n"
            "Masalan: 500000"
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

        context.user_data["exchange_usd"] = amount

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

        usd_amount = context.user_data["exchange_usd"]

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

        context.user_data.clear()

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

async def expense(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return

    text = update.message.text.strip()

    # Menyu tugmalarini xarajat deb qabul qilmaslik
    if text in [
        "💰 Pul oldim",
        "💵 $ maydalash",
        "⬅️ Bekor qilish",
        "🇺🇿 So'm",
        "🇺🇸 Dollar"
    ]:
        return

    try:
        # Masalan:
        # abet 200000
        # benzin 150000
        # usta uchun 500000

        parts = text.rsplit(maxsplit=1)

        if len(parts) != 2:
            raise ValueError

        name = parts[0].strip()
        amount = parse_uzs(parts[1])

        if not name:
            raise ValueError

    except (ValueError, InvalidOperation):

        await update.message.reply_text(
            "❌ Xarajatni quyidagicha yozing:\n\n"
            "abet 200000\n"
            "benzin 150000\n"
            "usta 500000"
        )

        return

    # Xarajatni bazaga yozamiz
    add_transaction(
        "expense",
        "UZS",
        -amount,
        name,
        update.effective_user.id
    )

    uzs_balance = get_balance("UZS")
    usd_balance = get_balance("USD")

    await update.message.reply_text(
        "🔴 Xarajat yozildi\n\n"
        f"📝 {name}\n"
        f"➖ {format_uzs(amount)} so'm\n\n"
        f"🇺🇿 Qoldiq: "
        f"{format_uzs(uzs_balance)} so'm",
        reply_markup=MAIN_KEYBOARD
    )

    # =====================================================
    # BOSHQA ODAMGA XABAR
    # =====================================================

    cashier_name = update.effective_user.full_name

    report_text = (
        "🔴 YANGI XARAJAT\n\n"
        f"📝 Xarajat: {name}\n"
        f"💰 Summa: {format_uzs(amount)} so'm\n\n"
        f"🇺🇿 So'm qoldiq: "
        f"{format_uzs(uzs_balance)} so'm\n"
        f"💵 Dollar qoldiq: "
        f"{format_usd(usd_balance)}\n\n"
        f"👤 Kassir: {cashier_name}\n"
        f"🕐 {now_text()}"
    )

    try:
        await context.bot.send_message(
            chat_id=REPORT_CHAT_ID,
            text=report_text
        )

    except TelegramError as e:
        await update.message.reply_text(
            "⚠️ Xarajat saqlandi, lekin "
            "hisobot boshqa odamga yuborilmadi.\n\n"
            "U odam botga /start bosganini tekshiring."
        )

        print("Telegram xato:", e)


# =========================================================
# HISOB
# =========================================================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return

    uzs = get_balance("UZS")
    usd = get_balance("USD")

    await update.message.reply_text(
        "💼 KASSA HOLATI\n\n"
        f"🇺🇿 So'm: {format_uzs(uzs)} so'm\n"
        f"💵 Dollar: {format_usd(usd)}",
        reply_markup=MAIN_KEYBOARD
    )


# =========================================================
# TARIX
# =========================================================

async def history(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return

    rows = get_history(10)

    if not rows:
        await update.message.reply_text(
            "Hozircha operatsiyalar yo'q."
        )
        return

    lines = ["📋 OXIRGI 10 TA OPERATSIYA\n"]

    for created_at, kind, currency, amount, note in rows:

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
            f"{sign}{amount_text}\n"
            f"{created_at}\n"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# NOLGA TUSHIRISH
# =========================================================

async def reset_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "⚠️ Kassani nolga tushirish\n\n"
        "So'm va dollar qoldiqlari 0 bo'ladi. "
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

    context.user_data.clear()
    await update.message.reply_text(
        "✅ Kassa nolga tushirildi.\n\n"
        "🇺🇿 So'm: 0 so'm\n"
        "💵 Dollar: $0\n"
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
    context.user_data.clear()

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
            CommandHandler("reset", reset_start),
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
                        r"^(🇺🇿 So'm|🇺🇸 Dollar)$"
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
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("hisob", balance))
    app.add_handler(CommandHandler("tarix", history))

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
