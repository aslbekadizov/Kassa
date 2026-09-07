# Kassa bot

Telegram orqali naqd so'm, dollar va kartadagi pulni hisobga olish boti.
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
- `💰 Pul oldim` — naqd so'm, dollar yoki `💳 Karta` hisobiga kirim kiritish.
- `💵 $ maydalash` — dollarni so'mga almashtirish.
- `benzin 150000` — asosiy menyudan naqd so'm xarajatini yozish.
- `💳 Kartadan` yoki `/kartadan` — masalan, `Ali 200000` deb kartadan xarajat yozish.
- `📊 Statistika` yoki `/statistika` — bugun, shu oy yoki barcha vaqt bo'yicha hisobot.
- `/hisob` — naqd so'm, dollar va karta qoldiqlari.
- `/tarix` — oxirgi 10 ta operatsiya, naqd yoki karta belgisi bilan.
- `/reset` — tasdiqlashdan keyin uchala hisob qoldig'i va tarixni tozalash. Avval `backups/` papkasiga baza zaxirasi olinadi.
- `/cancel` — joriy amalni bekor qilish.
- `/id` — Telegram ID raqami.

## Karta hisobi

Karta hisobi so'mda yuritiladi. O'tkazmani bank ilovangizda bajarasiz, keyin botga yozasiz.

1. `💰 Pul oldim` → `💳 Karta` → `500000`: karta qoldig'iga 500 000 so'm qo'shiladi.
2. `💳 Kartadan` → `Ali 200000`: faqat karta qoldig'idan 200 000 so'm ayiriladi.
3. Karta qoldig'i 300 000 so'm bo'ladi; naqd so'm va dollar qoldiqlari o'zgarmaydi.

Kartadagi mablag' yetarli bo'lmasa, xarajat yozilmaydi. Har bir karta xarajati uchun
`💳 Kartadan` tugmasini bosing. Saqlangandan keyin bot asosiy menyuga qaytadi.
Xarajat hisobotida to'lov manbasi va uchala hisob qoldig'i ko'rsatiladi.

## Statistika

Hisobotda quyidagilar bor:

- Qancha pul olingani va qancha sarflangani: naqd so'm, karta va dollar alohida.
- So'm bo'yicha naqd va karta summalarining jami.
- Aylanma: kirim va xarajat yig'indisi; so'm va dollar alohida ko'rsatiladi.
- Eng ko'p xarajat qilingan 5 ta nom, jami summa va operatsiyalar soni.

Bir xil nomdagi naqd va karta xarajatlari so'm statistikasida birlashtiriladi.
Katta-kichik harf va ortiqcha bo'shliqlar farq qilmaydi: `Benzin` va `benzin` bitta nom.
Dollar maydalash ichki almashtirish bo'lgani uchun kirim, xarajat va aylanmaga qayta qo'shilmaydi.
Davrlar Toshkent vaqti bo'yicha hisoblanadi. `Barcha vaqt` mavjud bazadagi barcha yozuvlarni qamrab oladi.

## Serverdagi mavjud botni yangilash

Boshlangan operatsiyalarni tugating va bot ishlayotgan terminalda `Ctrl+C` bosing.
Shu loyiha papkasida bazaning zaxirasini olib, kodni yangilang:

```sh
mkdir -p backups
cp -p kassa.db "backups/kassa-before-update-$(date +%Y%m%d-%H%M%S).db"
git pull --ff-only
sh run.sh
```

Yangi kod birinchi ishga tushganda mavjud bazaga hisob turini qo'shadi.
Oldingi operatsiyalar naqd hisobda qoladi, karta hisobi 0 dan boshlanadi.
Mahalliy `.env` va `kassa.db` saqlanadi. Telegramda `/start` yuborib yangi menyuni oching.

## Tekshirish

```sh
.venv/bin/python -m unittest -v test_kassa.py
```

Testlar vaqtinchalik bazadan foydalanadi; Telegramga haqiqiy xabar yubormaydi.
