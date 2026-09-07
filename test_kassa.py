import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from telegram import Update
from telegram.ext import Application, ApplicationBuilder
from telegram.request import BaseRequest

import kassa


class FakeTelegramRequest(BaseRequest):
    """Telegramga haqiqiy xabar yubormasdan bot oqimini tekshirish."""

    def __init__(self):
        self.messages = []
        self.sent = []

    @property
    def read_timeout(self):
        return 5

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        action = url.rsplit("/", 1)[-1]
        if action == "getMe":
            result = {
                "id": 123456, "is_bot": True,
                "first_name": "Test", "username": "test_kassa_bot",
            }
        elif action == "sendMessage":
            params = request_data.parameters
            assert len(params["text"].encode("utf-16-le")) // 2 <= 4096
            self.sent.append(params)
            self.messages.append(params["text"])
            result = {
                "message_id": len(self.messages), "date": 1,
                "chat": {"id": params["chat_id"], "type": "private"},
                "text": params["text"],
            }
        else:
            raise AssertionError(f"Unexpected Telegram method: {action}")
        return 200, json.dumps({"ok": True, "result": result}).encode()


class BotTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db_path = Path(temp.name) / "kassa.db"
        self.path_patch = patch.object(kassa, "DB_PATH", self.db_path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        for name, value in (("CASHIER_ID", 1001), ("REPORT_CHAT_ID", 1002)):
            setting_patch = patch.object(kassa, name, value)
            setting_patch.start()
            self.addCleanup(setting_patch.stop)
        self.request = FakeTelegramRequest()
        builder = (
            ApplicationBuilder()
            .request(self.request)
            .get_updates_request(FakeTelegramRequest())
        )

        def capture_app(app, **kwargs):
            self.app = app
            self.assertFalse(kwargs["drop_pending_updates"])

        with (
            patch.object(kassa, "BOT_TOKEN", "123456:TEST"),
            patch.object(kassa, "ApplicationBuilder", return_value=builder),
            patch.object(Application, "run_polling", capture_app),
        ):
            kassa.main()

        await self.app.initialize()
        self.addAsyncCleanup(self.app.shutdown)
        self.errors = []

        async def record_error(update, context):
            self.errors.append(context.error)

        self.app.add_error_handler(record_error)
        kassa.add_transaction("income", "UZS", 500000, "Sinov")
        kassa.add_transaction("income", "USD", 20000, "Sinov dollar")
        kassa.add_transaction("expense", "UZS", -100000, "Sinov xarajat")
        kassa.add_exchange(10000, 1200000)
        self.original_rows = self.rows(self.db_path)
        self.update_id = 0

    def rows(self, path):
        with closing(sqlite3.connect(path)) as conn:
            return conn.execute("SELECT * FROM transactions ORDER BY id").fetchall()

    def backups(self):
        return list(self.db_path.parent.glob("backups/*.db"))

    async def send(self, text, actor_id=None, chat_id=None):
        actor_id = kassa.CASHIER_ID if actor_id is None else actor_id
        chat_id = actor_id if chat_id is None else chat_id
        self.update_id += 1
        message = {
            "message_id": self.update_id, "date": 1,
            "chat": {"id": chat_id, "type": "private" if chat_id == actor_id else "group"},
            "from": {"id": actor_id, "is_bot": False, "first_name": "Test"},
            "text": text,
        }
        if text.startswith("/"):
            message["entities"] = [
                {"type": "bot_command", "offset": 0, "length": len(text)}
            ]
        update = Update.de_json(
            {"update_id": self.update_id, "message": message}, self.app.bot
        )
        await self.app.process_update(update)
        self.assertEqual(self.errors, [])


class ResetTests(BotTestCase):
    async def test_confirm_resets_both_balances_and_backs_up_all_rows(self):
        kassa.add_transaction("income", "UZS", 500000, account="card")
        kassa.add_card_expense(100000, "Ali")
        self.original_rows = self.rows(self.db_path)
        await self.send("/reset")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(kassa.get_balance("UZS"), 0)
        self.assertEqual(kassa.get_balance("USD"), 0)
        self.assertEqual(kassa.get_balance("UZS", "card"), 0)
        self.assertEqual(kassa.get_history(), [])
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.rows(backups[0]), self.original_rows)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.assertIn("Kassa nolga tushirildi", self.request.messages[-1])

    async def test_cancel_preserves_data_and_exits_reset(self):
        await self.send("/reset")
        await self.send("⬅️ Bekor qilish")
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])

    async def test_cancel_command_preserves_data(self):
        await self.send("/reset")
        await self.send("/cancel")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])

    async def test_unconfirmed_text_does_not_reset_or_record_expense(self):
        await self.send(kassa.RESET_CONFIRM_TEXT)
        await self.send("/reset")
        await self.send("benzin 150000")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])
        self.assertIn("tasdiqlash tugmasini", self.request.messages[-1])

    async def test_other_user_cannot_reset_or_confirm_cashier_request(self):
        await self.send("/reset", actor_id=999)
        self.assertIn("faqat kassir", self.request.messages[-1])
        await self.send("/reset")
        await self.send(kassa.RESET_CONFIRM_TEXT, actor_id=999)
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])

    async def test_reset_interrupts_income_and_new_income_works_afterwards(self):
        await self.send("💰 Pul oldim")
        await self.send("🇺🇸 Dollar")
        await self.send("/reset")
        await self.send(kassa.RESET_CONFIRM_TEXT)
        await self.send("💰 Pul oldim")
        await self.send("🇺🇿 So'm")
        await self.send("5000")
        self.assertEqual(kassa.get_balance("UZS"), 5000)
        self.assertEqual(kassa.get_balance("USD"), 0)
        self.assertEqual(len(kassa.get_history()), 1)

    async def test_backup_failure_preserves_data(self):
        (self.db_path.parent / "backups").write_text("Not a directory")
        await self.send("/reset")
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertIn("Ma'lumotlar saqlandi", self.request.messages[-1])

    async def test_delete_failure_rolls_back_and_keeps_backup(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("""
                CREATE TRIGGER fail_reset BEFORE DELETE ON transactions
                BEGIN SELECT RAISE(ABORT, 'Simulated delete failure'); END
            """)
        await self.send("/reset")
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.rows(self.backups()[0]), self.original_rows)
        self.assertIn("Ma'lumotlar saqlandi", self.request.messages[-1])


class CardAndStatisticsTests(BotTestCase):
    async def card_income(self, amount):
        await self.send("💰 Pul oldim")
        await self.send(kassa.CARD_BUTTON)
        await self.send(str(amount))

    async def test_card_income_preserves_cash_and_dollars(self):
        before = (kassa.get_balance("UZS"), kassa.get_balance("USD"))
        await self.card_income(500000)
        self.assertEqual(kassa.get_balance("UZS", "card"), 500000)
        self.assertEqual((kassa.get_balance("UZS"), kassa.get_balance("USD")), before)
        self.assertIn("Karta qoldiq: 500 000", self.request.messages[-1])
        await self.send("💰 Pul oldim")
        await self.send("🇺🇿 So'm")
        await self.send("100000")
        self.assertEqual(kassa.get_balance("UZS"), before[0] + 100000)
        self.assertEqual(kassa.get_balance("UZS", "card"), 500000)

    async def test_account_selection_is_independent_between_chats(self):
        cash_before = kassa.get_balance("UZS")
        await self.send("💰 Pul oldim")
        await self.send(kassa.CARD_BUTTON)
        await self.send("💰 Pul oldim", chat_id=-500)
        await self.send("🇺🇿 So'm", chat_id=-500)
        await self.send("500000")
        await self.send("100000", chat_id=-500)
        self.assertEqual(kassa.get_balance("UZS", "card"), 500000)
        self.assertEqual(kassa.get_balance("UZS"), cash_before + 100000)
        self.assertEqual(kassa.get_balance("USD"), 10000)

    async def test_simultaneous_card_expenses_cannot_overdraw(self):
        kassa.add_transaction("income", "UZS", 100000, account="card")

        def spend(name):
            try:
                kassa.add_card_expense(80000, name)
                return True
            except kassa.InsufficientCardFunds:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(spend, ["Ali", "Vali"]))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(kassa.get_balance("UZS", "card"), 20000)

    async def test_card_expense_and_report_use_only_card_then_return_to_cash(self):
        await self.card_income(500000)
        cash_before = kassa.get_balance("UZS")
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("Ali 200000")
        self.assertEqual(kassa.get_balance("UZS", "card"), 300000)
        self.assertEqual(kassa.get_balance("UZS"), cash_before)
        self.assertEqual(kassa.get_balance("USD"), 10000)
        report = self.request.sent[-1]
        self.assertEqual(report["chat_id"], kassa.REPORT_CHAT_ID)
        self.assertIn("Manba: 💳 Karta", report["text"])
        self.assertIn("Karta qoldiq: 300 000", report["text"])
        await self.send("benzin 150000")
        self.assertEqual(kassa.get_balance("UZS"), cash_before - 150000)
        self.assertEqual(kassa.get_balance("UZS", "card"), 300000)
        self.assertIn("Manba: 💰 Naqd so'm", self.request.messages[-1])

    async def test_cash_cannot_cover_missing_card_funds(self):
        await self.send("/kartadan")
        await self.send("Ali 200000")
        self.assertIn("yetarli emas", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), self.original_rows)

    async def test_insufficient_card_funds_allow_retry_with_exact_balance(self):
        await self.card_income(100000)
        before = self.rows(self.db_path)
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("Ali 200000")
        self.assertEqual(self.rows(self.db_path), before)
        await self.send("Ali 100000")
        self.assertEqual(kassa.get_balance("UZS", "card"), 0)
        self.assertEqual(len(self.rows(self.db_path)), len(before) + 1)

    async def test_invalid_card_expenses_and_cancellation_preserve_money(self):
        await self.card_income(100000)
        before = self.rows(self.db_path)
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        for value in ("Ali", "Ali 0", "Ali -100", "Ali " + "9" * 30):
            await self.send(value)
            self.assertEqual(self.rows(self.db_path), before)
        await self.send("⬅️ Bekor qilish")
        self.assertEqual(self.rows(self.db_path), before)
        await self.send("💰 Pul oldim")
        await self.send(kassa.CARD_BUTTON)
        await self.send("0")
        await self.send("/cancel")
        self.assertEqual(self.rows(self.db_path), before)

    async def test_navigation_cancels_pending_card_expense(self):
        await self.card_income(500000)
        cash_before = kassa.get_balance("UZS")
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("/start")
        await self.send("benzin 50000")
        self.assertEqual(kassa.get_balance("UZS"), cash_before - 50000)
        self.assertEqual(kassa.get_balance("UZS", "card"), 500000)
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send(kassa.STATISTICS_BUTTON)
        before = self.rows(self.db_path)
        await self.send("Ali 200000")
        self.assertEqual(self.rows(self.db_path), before)
        await self.send(kassa.BACK_BUTTON)
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("Ali 200000")
        self.assertEqual(kassa.get_balance("UZS", "card"), 300000)

    async def test_balance_history_and_menus_include_card(self):
        await self.card_income(500000)
        await self.send("/hisob")
        self.assertIn("Karta: 500 000", self.request.messages[-1])
        self.assertIn("Naqd so'm: 1 600 000", self.request.messages[-1])
        await self.send("/tarix")
        self.assertIn("💳 Karta", self.request.messages[-1])
        self.assertIn("💵 Naqd", self.request.messages[-1])
        await self.send("/start")
        markup = str(self.request.sent[-1]["reply_markup"])
        self.assertIn(kassa.CARD_EXPENSE_BUTTON, markup)
        self.assertIn(kassa.STATISTICS_BUTTON, markup)

    async def test_card_and_statistics_are_cashier_only(self):
        for text in (kassa.CARD_EXPENSE_BUTTON, "/kartadan", kassa.STATISTICS_BUTTON, "/statistika"):
            await self.send(text, actor_id=999)
            self.assertIn("faqat kassir", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), self.original_rows)

    async def test_statistics_exclude_exchange_and_combine_same_expense_names(self):
        kassa.add_transaction("income", "UZS", 1000000, account="card")
        kassa.add_card_expense(400000, " BENZIN ")
        kassa.add_transaction("expense", "UZS", -150000, "benzin")
        kassa.add_transaction("expense", "USD", -5000, "Usta")
        totals, top = kassa.get_statistics()
        self.assertEqual(totals[("cash", "UZS")], {"income": 500000, "expense": 250000})
        self.assertEqual(totals[("card", "UZS")], {"income": 1000000, "expense": 400000})
        self.assertEqual(totals[("cash", "USD")], {"income": 20000, "expense": 5000})
        self.assertEqual(top["UZS"][0], ("benzin", 550000, 2))
        self.assertEqual(top["USD"], [("usta", 5000, 1)])
        await self.send("/statistika")
        text = self.request.messages[-1]
        self.assertIn("Jami so'm: 1 500 000", text)
        self.assertIn("Jami so'm: 650 000", text)
        self.assertIn("So'm: 2 150 000", text)
        self.assertIn("Dollar: $250", text)
        self.assertIn("1. benzin: 550 000 so'm (2 ta)", text)

    async def test_statistics_menu_periods_and_empty_report(self):
        kassa.reset_database()
        await self.send(kassa.STATISTICS_BUTTON)
        self.assertIn("Bu davrda xarajat yo'q", self.request.messages[-1])
        for button, (_, label) in kassa.STATISTICS_PERIODS.items():
            await self.send(button)
            self.assertIn(f"STATISTIKA — {label}", self.request.messages[-1])
        await self.send(kassa.BACK_BUTTON)
        self.assertIn("Kassa bot", self.request.messages[-1])

    async def test_statistics_top_five_are_sorted_and_fit_telegram_limit(self):
        kassa.reset_database()
        for index in range(8):
            name = ("🚗" * 400) + str(index)
            kassa.add_transaction("expense", "UZS", -(index + 1) * 100, name)
        _, top = kassa.get_statistics()
        self.assertEqual([row[1] for row in top["UZS"]], [800, 700, 600, 500, 400])
        await self.send("/stats")
        self.assertIn("...", self.request.messages[-1])

    async def test_statistics_date_boundaries_use_tashkent_time(self):
        kassa.reset_database()
        dates = [
            ("2026-08-31 23:59:59", 1), ("2026-09-01 00:00:00", 10),
            ("2026-09-06 23:59:59", 100), ("2026-09-07 00:00:00", 1000),
            ("2026-09-07 23:59:59", 10000), ("2026-09-08 00:00:00", 100000),
            ("2026-10-01 00:00:00", 1000000),
        ]
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executemany(
                "INSERT INTO transactions (created_at, kind, currency, amount, note, account) "
                "VALUES (?, 'income', 'UZS', ?, 'Sinov', 'card')", dates
            )
            conn.executemany(
                "INSERT INTO transactions (created_at, kind, currency, amount, note) "
                "VALUES (?, 'expense', 'UZS', -?, 'Sinov')", dates
            )
        now = datetime(2026, 9, 6, 20, tzinfo=timezone.utc)
        for period, expected in (("today", 11000), ("month", 111110), ("all", 1111111)):
            totals, top = kassa.get_statistics(period, now=now)
            self.assertEqual(totals[("card", "UZS")]["income"], expected)
            self.assertEqual(totals[("cash", "UZS")]["expense"], expected)
            self.assertEqual(top["UZS"][0][1], expected)


class MigrationTests(unittest.TestCase):
    def test_legacy_database_keeps_rows_balances_and_supports_card(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy.db"
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute("""
                    CREATE TABLE transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                        kind TEXT NOT NULL, currency TEXT NOT NULL, amount INTEGER NOT NULL,
                        note TEXT, actor_id INTEGER
                    )
                """)
                conn.executemany(
                    "INSERT INTO transactions (created_at, kind, currency, amount, note, actor_id) "
                    "VALUES ('2026-09-01 12:00:00', ?, ?, ?, 'Eski', 1001)",
                    [("income", "UZS", 500000), ("expense", "UZS", -100000), ("income", "USD", 20000)]
                )
                original = conn.execute("SELECT * FROM transactions ORDER BY id").fetchall()
            with patch.object(kassa, "DB_PATH", db_path):
                kassa.init_db()
                kassa.init_db()
                with closing(sqlite3.connect(db_path)) as conn:
                    migrated = conn.execute("SELECT * FROM transactions ORDER BY id").fetchall()
                self.assertEqual(migrated, [row + ("cash",) for row in original])
                self.assertEqual(kassa.get_balance("UZS"), 400000)
                self.assertEqual(kassa.get_balance("USD"), 20000)
                self.assertEqual(kassa.get_balance("UZS", "card"), 0)
                kassa.add_transaction("income", "UZS", 300000, account="card")
                kassa.add_card_expense(50000, "Ali")
                kassa.add_exchange(10000, 1200000)
                self.assertEqual(kassa.get_balance("UZS", "card"), 250000)
                self.assertEqual(kassa.get_balance("UZS"), 1600000)
                totals, _ = kassa.get_statistics()
                self.assertEqual(totals[("cash", "UZS")]["income"], 500000)
                self.assertEqual(totals[("card", "UZS")]["expense"], 50000)


if __name__ == "__main__":
    unittest.main()
