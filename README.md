# Kassa bot

Telegram orqali so'm va dollardagi kirim, xarajat va dollar maydalashni hisobga olish boti.
Ma'lumotlar mahalliy `kassa.db` faylida saqlanadi.

## Ishga tushirish

Python 3.10 yoki yangiroq versiya kerak.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

`.env` faylida sozlamalarni kiriting:

- `BOT_TOKEN` — BotFather bergan bot tokeni.
- `CASHIER_ID` — kassirning Telegram ID raqami.
- `REPORT_CHAT_ID` — xarajat hisobotini oladigan odamning Telegram ID raqami.

```sh
sh run.sh
```

Bot ishlashi uchun ushbu jarayon ishlab turishi kerak. To'xtatish: `Ctrl+C`.
Hisobotni oladigan odam ham botga `/start` yuborishi kerak.
ID raqamini bilish uchun botga `/id` yuboring. Kassir ID raqami `0` bo'lsa, kassa amallari yopiq bo'ladi;
`.env` faylini yangilagach, botni qayta ishga tushiring.

Token, bazalar, zaxira nusxalari va loglar Git'ga qo'shilmaydi.

## Foydalanish

- `/start` — asosiy menyu.
- `💰 Pul oldim` — so'm yoki dollar kirimini kiritish.
- `💵 $ maydalash` — dollarni so'mga almashtirish.
- `benzin 150000` — xarajat yozish.
- `/hisob` — ikkala valyutadagi qoldiq.
- `/tarix` — oxirgi 10 ta operatsiya.
- `/reset` — tasdiqlashdan keyin qoldiqlar va tarixni tozalash. Avval `backups/` papkasiga baza zaxirasi olinadi.
- `/cancel` — joriy amalni bekor qilish.
- `/id` — Telegram ID raqami.

## Tekshirish

```sh
.venv/bin/python -m unittest -v test_kassa.py
```

Testlar vaqtinchalik bazadan foydalanadi; Telegramga haqiqiy xabar yubormaydi.
