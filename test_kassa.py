import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
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
            self.messages.append(params["text"])
            result = {
                "message_id": len(self.messages), "date": 1,
                "chat": {"id": params["chat_id"], "type": "private"},
                "text": params["text"],
            }
        else:
            raise AssertionError(f"Unexpected Telegram method: {action}")
        return 200, json.dumps({"ok": True, "result": result}).encode()


class ResetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db_path = Path(temp.name) / "kassa.db"
        self.path_patch = patch.object(kassa, "DB_PATH", self.db_path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
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

    async def send(self, text, actor_id=None):
        actor_id = kassa.CASHIER_ID if actor_id is None else actor_id
        self.update_id += 1
        message = {
            "message_id": self.update_id, "date": 1,
            "chat": {"id": actor_id, "type": "private"},
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

    async def test_confirm_resets_both_balances_and_backs_up_all_rows(self):
        await self.send("/reset")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(kassa.get_balance("UZS"), 0)
        self.assertEqual(kassa.get_balance("USD"), 0)
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


if __name__ == "__main__":
    unittest.main()
