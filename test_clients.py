import sqlite3
from contextlib import closing
from unittest.mock import patch

import kassa
from test_kassa import BotTestCase


class ClientTests(BotTestCase):
    async def create_client(self, name, chat_id=None):
        await self.send(kassa.CLIENTS_BUTTON, chat_id=chat_id)
        await self.send(kassa.ADD_CLIENT_BUTTON, chat_id=chat_id)
        await self.send(name, chat_id=chat_id)
        return next(row for row in kassa.get_clients() if row[1] == name)

    async def open_client(self, client, chat_id=None):
        await self.send(kassa.CLIENTS_BUTTON, chat_id=chat_id)
        await self.send(f"👤 #{client[0]} — {client[1]}", chat_id=chat_id)

    async def income(self, button, amount, chat_id=None):
        await self.send(kassa.CLIENT_INCOME_BUTTON, chat_id=chat_id)
        await self.send(button, chat_id=chat_id)
        await self.send(amount, chat_id=chat_id)

    def reports(self):
        return [m["text"] for m in self.request.sent if m["chat_id"] == kassa.REPORT_CHAT_ID]

    async def test_clients_start_empty_and_old_named_income_is_never_assigned(self):
        await self.send("💰 Pul oldim")
        await self.send("🇺🇿 So'm")
        await self.send("Alidan 500000")
        original = self.rows(self.db_path)
        balances = (kassa.get_balance("UZS"), kassa.get_balance("USD"))
        await self.send(kassa.CLIENTS_BUTTON)
        self.assertIn("Hozircha mijoz yo'q", self.request.messages[-1])
        self.assertEqual(kassa.get_clients(), [])
        client = await self.create_client("Ali")
        self.assertEqual(kassa.get_statement(client[0])[0], [])
        self.assertEqual(self.rows(self.db_path), original)
        self.assertEqual((kassa.get_balance("UZS"), kassa.get_balance("USD")), balances)
        self.assertTrue(all(row[-1] is None for row in original))
        self.assertIn("Olingan: 0 so'm", self.request.messages[-1])
        self.assertIn("Mijoz qoldig'i: $0", self.request.messages[-1])
        kassa.init_db()
        self.assertEqual(kassa.get_clients(), [client])
        self.assertEqual(self.rows(self.db_path), original)

    async def test_each_client_keeps_income_and_expenses_and_updates_global_money_once(self):
        ali = await self.create_client("Ali")
        await self.income("🇺🇿 So'm", "500000")
        await self.income("🇺🇸 Dollar", "300")
        await self.income(kassa.CARD_BUTTON, "200000")
        await self.send("Material 150000")
        await self.send("Furnituraga 12.50$")
        await self.send(kassa.CLIENT_CARD_BUTTON)
        await self.send("Usta 50000")
        rows, totals = kassa.get_statement(ali[0])
        self.assertEqual(len(rows), 6)
        self.assertEqual(totals, {
            "UZS": {"income": 700000, "expense": 200000},
            "USD": {"income": 30000, "expense": 1250},
        })
        vali = await self.create_client("Vali")
        await self.income("🇺🇿 So'm", "100000")
        await self.send("Material 250000")
        self.assertEqual(kassa.get_statement(vali[0])[1]["UZS"], {"income": 100000, "expense": 250000})
        self.assertEqual(kassa.get_statement(ali[0]), (rows, totals))
        self.assertEqual(kassa.get_balance("UZS"), 1800000)
        self.assertEqual(kassa.get_balance("USD"), 38750)
        self.assertEqual(kassa.get_balance("UZS", "card"), 150000)
        self.assertEqual(len(self.rows(self.db_path)), len(self.original_rows) + 8)
        self.assertEqual(len(self.reports()), 8)
        self.assertTrue(all("Mijoz: Ali" in report for report in self.reports()[:6]))
        self.assertTrue(all("Mijoz: Vali" in report for report in self.reports()[6:]))
        self.assertTrue(all("qoldiq" not in report.lower() for report in self.reports()))
        await self.send(kassa.CLIENT_REPORT_BUTTON)
        self.assertIn("Mijoz qoldig'i: -150 000 so'm", self.request.messages[-1])
        self.assertNotIn("Furnituraga", self.request.messages[-1])
        self.assertEqual(len(self.reports()), 8)

    async def test_other_expenses_and_main_menu_do_not_keep_customer_selection(self):
        client = await self.create_client("Ali")
        await self.income("🇺🇿 So'm", "500000")
        await self.send("Mijoz materiali 100000")
        before_client = kassa.get_statement(client[0])
        await self.send(kassa.CLIENT_INCOME_BUTTON)
        await self.send("🇺🇿 So'm")
        await self.send(kassa.OTHER_BUTTON)
        await self.send("Ijara 200000")
        await self.send("Choy 5$")
        kassa.add_transaction("income", "UZS", 100000, account="card")
        await self.send(kassa.OTHER_CARD_BUTTON)
        await self.send("Transport 50000")
        self.assertEqual(kassa.get_statement(client[0]), before_client)
        self.assertTrue(all(row[-1] is None for row in self.rows(self.db_path)[-4:]))
        await self.send(kassa.OTHER_REPORT_BUTTON)
        text = self.request.messages[-1]
        self.assertIn("Ijara", text)
        self.assertIn("Transport", text)
        self.assertIn("Sinov xarajat", text)
        self.assertNotIn("Mijoz materiali", text)
        self.assertNotIn("Kirim", text)
        self.assertIn("So'm: 350 000 so'm", text)
        self.assertIn("Dollar: $5", text)
        await self.open_client(client)
        await self.send(kassa.BACK_BUTTON)
        await self.send("Chiroq 50000")
        self.assertIsNone(self.rows(self.db_path)[-1][-1])
        self.assertEqual(kassa.get_statement(client[0]), before_client)

    async def test_card_expense_checks_global_card_funds_but_client_may_be_negative(self):
        client = await self.create_client("Ali")
        before = self.rows(self.db_path)
        await self.send(kassa.CLIENT_CARD_BUTTON)
        await self.send("Usta 100000")
        self.assertIn("yetarli emas", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), before)
        await self.send("Usta 1$")
        self.assertEqual(self.rows(self.db_path), before)
        kassa.add_transaction("income", "UZS", 100000, account="card")
        await self.send("Usta 100000")
        self.assertEqual(kassa.get_balance("UZS", "card"), 0)
        self.assertEqual(kassa.get_statement(client[0])[1]["UZS"], {"income": 0, "expense": 100000})
        self.assertEqual(self.request.sent[-2]["reply_markup"], kassa.CLIENT_KEYBOARD.to_dict())
        await self.send("Mayda xarajat 10000")
        self.assertEqual(self.rows(self.db_path)[-1][-1], client[0])

    async def test_cancel_returns_to_selected_client_without_recording_pending_input(self):
        client = await self.create_client("Ali")
        for action in (kassa.CLIENT_INCOME_BUTTON, kassa.CLIENT_CARD_BUTTON):
            await self.send(action)
            await self.send("/cancel")
            self.assertEqual(self.rows(self.db_path), self.original_rows)
            self.assertIn("MIJOZ: Ali", self.request.messages[-1])
        await self.send(kassa.CLIENT_CASH_BUTTON)
        await self.send("Mix 5000")
        self.assertEqual(self.rows(self.db_path)[-1][-1], client[0])
        await self.send("💰 Pul oldim")
        await self.send("🇺🇿 So'm")
        await self.send("Validan 100000")
        self.assertIsNone(self.rows(self.db_path)[-1][-1])

    async def test_customer_switch_and_chat_selection_are_independent(self):
        ali = await self.create_client("Ali")
        vali = await self.create_client("Vali")
        await self.open_client(ali)
        await self.open_client(vali, chat_id=-500)
        await self.income("🇺🇿 So'm", "100000")
        await self.income("🇺🇸 Dollar", "20", chat_id=-500)
        await self.send("Mix 20000")
        await self.send("Furnitura 5$", chat_id=-500)
        self.assertEqual(kassa.get_statement(ali[0])[1], {
            "UZS": {"income": 100000, "expense": 20000}, "USD": {"income": 0, "expense": 0},
        })
        self.assertEqual(kassa.get_statement(vali[0])[1], {
            "UZS": {"income": 0, "expense": 0}, "USD": {"income": 2000, "expense": 500},
        })
        await self.send(kassa.CLIENT_INCOME_BUTTON)
        await self.send("🇺🇸 Dollar")
        await self.open_client(vali)
        await self.send("Mix 5000")
        self.assertEqual(kassa.get_statement(vali[0])[0][-1][1:4], ("expense", "UZS", -5000))

    async def test_bad_inputs_and_missing_client_do_not_write_or_report(self):
        client = await self.create_client("Ali")
        await self.send(kassa.CLIENT_INCOME_BUTTON)
        await self.send("Furnitura 300$")
        self.assertIn("Hisobni tugmadan tanlang", self.request.messages[-1])
        await self.send("🇺🇸 Dollar")
        for text in ("0", "-5", "NaN", "0.001", "92233720368547758.08"):
            await self.send(text)
            self.assertEqual(self.rows(self.db_path), self.original_rows)
        await self.send("/cancel")
        for text in ("Furnitura", "Furnitura 0", "Furnitura -10", "Furnitura 0.001$"):
            await self.send(text)
            self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.reports(), [])
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DELETE FROM clients WHERE id = ?", (client[0],))
        await self.send("Furnitura 100000")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertIn("Hozircha mijoz yo'q", self.request.messages[-1])

    async def test_names_are_manual_normalized_unique_and_clients_are_paginated(self):
        await self.send(kassa.CLIENTS_BUTTON)
        await self.send(kassa.ADD_CLIENT_BUTTON)
        for name in ("   ", "👤", "A" * 81):
            await self.send(name)
            self.assertIn("❌", self.request.messages[-1])
            self.assertEqual(kassa.get_clients(), [])
        await self.send("  Ali   aka ")
        client = kassa.get_clients()[0]
        await self.send(kassa.CLIENTS_BUTTON)
        await self.send(kassa.ADD_CLIENT_BUTTON)
        await self.send("ALI AKA")
        self.assertEqual(kassa.get_clients(), [client])
        for index in range(13):
            kassa.add_client(f"Mijoz {index:02}")
        await self.send(kassa.CLIENTS_BUTTON)
        self.assertIn(kassa.NEXT_CLIENTS_BUTTON, str(self.request.sent[-1]["reply_markup"]))
        await self.send(kassa.NEXT_CLIENTS_BUTTON)
        markup = self.request.sent[-1]["reply_markup"]
        self.assertIn("Mijoz 12", str(markup))
        label = next(row[0]["text"] for row in markup["keyboard"]
                     if row[0]["text"].startswith("👤 #") and "Mijoz 12" in row[0]["text"])
        await self.send(label)
        self.assertIn("MIJOZ: Mijoz 12", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), self.original_rows)

    async def test_stale_or_forged_selection_never_becomes_an_expense(self):
        client = await self.create_client("Ali 500000")
        await self.send(kassa.BACK_BUTTON)
        await self.send(f"👤 #{client[0]} — {client[1]}")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        await self.send(kassa.CLIENTS_BUTTON)
        await self.send("👤 #999 — Fake 500000")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertIn("tugmadan tanlang", self.request.messages[-1])

    async def test_other_users_cannot_read_create_or_write_clients(self):
        client = await self.create_client("Ali")
        for command in (kassa.CLIENTS_BUTTON, "/mijozlar", kassa.OTHER_BUTTON, "/boshqa"):
            await self.send(command, actor_id=999)
            self.assertIn("faqat kassir", self.request.messages[-1])
        for text in (kassa.CLIENT_REPORT_BUTTON, kassa.CLIENT_INCOME_BUTTON, "Material 100000"):
            await self.open_client(client, chat_id=-500)
            await self.send(text, actor_id=999, chat_id=-500)
            self.assertIn("faqat kassir", self.request.messages[-1])
        await self.send(kassa.CLIENTS_BUTTON, chat_id=-500)
        await self.send(kassa.ADD_CLIENT_BUTTON, chat_id=-500)
        await self.send("Begona", actor_id=999, chat_id=-500)
        self.assertEqual(kassa.get_clients(), [client])
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.reports(), [])

    async def test_statement_shows_every_transaction_and_does_not_notify_recipient(self):
        client = await self.create_client("Ali")
        names = [f"Material {index}: " + "🔧" * 180 for index in range(25)]
        kassa.add_transaction("income", "UZS", 500000, "Boshlang'ich kirim", client_id=client[0])
        for name in names:
            kassa.add_transaction("expense", "UZS", -1000, name, client_id=client[0])
        start = len(self.request.messages)
        await self.send(kassa.CLIENT_REPORT_BUTTON)
        chunks = self.request.messages[start:]
        self.assertGreater(len(chunks), 2)
        text = "".join(chunks)
        self.assertIn("Boshlang'ich kirim", text)
        for name in names:
            self.assertEqual(text.count(name), 1)
        self.assertIn("Ishlatilgan: 25 000 so'm", chunks[-1])
        self.assertIn("Mijoz qoldig'i: 475 000 so'm", chunks[-1])
        self.assertNotIn("Sinov xarajat", text)
        self.assertTrue(all(len(chunk.encode("utf-16-le")) // 2 <= 4000 for chunk in chunks))
        self.assertEqual(self.reports(), [])

    async def test_global_history_statistics_include_client_name_and_expense_once(self):
        client = await self.create_client("Ali")
        await self.income("🇺🇿 So'm", "500000")
        await self.send("Material 150000")
        await self.send("/tarix")
        self.assertIn("Mijoz: Ali", self.request.messages[-1])
        self.assertIn("Sinov xarajat", self.request.messages[-1])
        await self.send("/stats")
        await self.send("📋 Barcha vaqt")
        self.assertIn("Mijoz: Ali", self.request.messages[-1])
        self.assertIn("So'm: 250 000 so'm", self.request.messages[-1])
        self.assertEqual(len(kassa.get_statistics()[0]), 2)
        self.assertEqual(kassa.get_statement(client[0])[1]["UZS"]["expense"], 150000)

    async def test_failed_report_keeps_client_transaction_and_menu_for_next_entry(self):
        client = await self.create_client("Ali")
        self.request.fail_chat_ids.add(kassa.REPORT_CHAT_ID)
        await self.income("🇺🇿 So'm", "500000")
        self.assertIn("Kirim saqlandi", self.request.messages[-1])
        self.assertEqual(self.request.sent[-1]["reply_markup"], kassa.CLIENT_KEYBOARD.to_dict())
        await self.send("Material 100000")
        self.assertIn("Xarajat saqlandi", self.request.messages[-1])
        self.assertEqual(len(kassa.get_statement(client[0])[0]), 2)
        self.assertEqual(kassa.get_balance("UZS"), 2000000)
        self.assertEqual(len(self.rows(self.db_path)), len(self.original_rows) + 2)

    async def test_database_failure_and_invalid_foreign_key_do_not_change_ledger(self):
        client = await self.create_client("Ali")
        await self.send(kassa.CLIENT_INCOME_BUTTON)
        await self.send("🇺🇿 So'm")
        with patch.object(kassa, "add_transaction", side_effect=sqlite3.OperationalError("locked")):
            await self.send("500000")
        self.assertIn("Kirim saqlanmadi", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.reports(), [])
        await self.send("100000")
        before = self.rows(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            kassa.add_transaction("income", "UZS", 500000, client_id=999)
        kassa.add_transaction("income", "UZS", 100000, account="card")
        card_before = self.rows(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            kassa.add_card_expense(100000, "Usta", client_id=999)
        self.assertEqual(self.rows(self.db_path), card_before)
        self.assertEqual(kassa.get_balance("UZS", "card"), 100000)
        self.assertEqual(len(kassa.get_statement(client[0])[0]), 1)
        self.assertEqual(len(before), len(self.original_rows) + 1)

    async def test_reset_backs_up_clients_and_clears_their_transactions_but_keeps_names(self):
        client = await self.create_client("Ali")
        await self.income("🇺🇿 So'm", "500000")
        await self.send("Material 100000")
        before = self.rows(self.db_path)
        await self.send("/reset")
        self.assertIn("Mijozlarning kirim va xarajatlari ham tozalanadi", self.request.messages[-1])
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(kassa.get_clients(), [client])
        self.assertEqual(kassa.get_statement(client[0])[0], [])
        self.assertEqual(self.rows(self.backups()[0]), before)
        with closing(sqlite3.connect(self.backups()[0])) as conn:
            self.assertEqual(conn.execute("SELECT id, name FROM clients").fetchall(), [client])
        await self.open_client(client)
        self.assertIn("Olingan: 0 so'm", self.request.messages[-1])


class ClientMigrationTests(BotTestCase):
    async def test_previous_card_schema_keeps_every_old_field_without_creating_clients(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DROP TABLE transactions")
            conn.execute("DROP TABLE clients")
            conn.execute("""
                CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    kind TEXT NOT NULL, currency TEXT NOT NULL, amount INTEGER NOT NULL,
                    note TEXT, actor_id INTEGER, account TEXT NOT NULL DEFAULT 'cash'
                )
            """)
            conn.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                (7, "2026-09-09 10:00:00", "income", "UZS", 500000, "Kimdan: Ali", 1001, "cash"),
                (8, "2026-09-09 11:00:00", "expense", "UZS", -100000, "Ali", 1001, "cash"),
                (9, "2026-09-09 12:00:00", "income", "USD", 30000, "Dollar olindi", 1001, "cash"),
                (10, "2026-09-09 13:00:00", "income", "UZS", 200000, "Kartaga pul olindi", 1001, "card"),
            ])
        before = self.rows(self.db_path)
        kassa.init_db()
        kassa.init_db()
        self.assertEqual(self.rows(self.db_path), [row + (None,) for row in before])
        self.assertEqual(kassa.get_clients(), [])
        self.assertEqual(kassa.get_balance("UZS"), 400000)
        self.assertEqual(kassa.get_balance("USD"), 30000)
        self.assertEqual(kassa.get_balance("UZS", "card"), 200000)
        client = kassa.add_client("Ali")
        self.assertEqual(kassa.get_statement(client[0])[0], [])
        kassa.add_transaction("income", "UZS", 100000, client_id=client[0])
        self.assertGreater(self.rows(self.db_path)[-1][0], 10)
        self.assertEqual(self.rows(self.db_path)[:-1], [row + (None,) for row in before])
