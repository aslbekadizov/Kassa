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
- `REPORT_CHAT_ID` — kirim va xarajat xabarlarini oladigan odamning Telegram ID raqami.

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
- `Furnituraga 300$` — asosiy menyudan naqd dollar hisobidan 300 dollar xarajat yozish.
- `💳 Kartadan` yoki `/kartadan` — masalan, `Ali 200000` deb kartadan xarajat yozish.
- `📊 Statistika` yoki `/statistika` — bugun, shu oy yoki barcha vaqt bo'yicha hisobot.
- `/hisob` — naqd so'm, dollar va karta qoldiqlari.
- `/tarix` — oxirgi 10 ta operatsiya, naqd yoki karta belgisi bilan.
- `/reset` — tasdiqlashdan keyin uchala hisob qoldig'i va tarixni tozalash. Avval `backups/` papkasiga baza zaxirasi olinadi.
- `/cancel` — joriy amalni bekor qilish.
- `/id` — Telegram ID raqami.

## Pul oldim

`💰 Pul oldim` tugmasidan keyin so'm yoki dollarni tanlab, kimdan olganingizni va
miqdorni bitta xabarda yozing:

- `🇺🇿 So'm` → `Alidan 500000` yoki `Ali akadan 500 000`: naqd so'mga 500 000 qo'shiladi.
- `🇺🇸 Dollar` → `Alidan 300`: dollar hisobiga $300 qo'shiladi.
- `🇺🇸 Dollar` → `Alidan 12.50$` yoki `Alidan 12,50 $`: $12.50 qo'shiladi.

Kimdan olingani tasdiqlash xabarida, tarixda va hisobot oluvchiga yuboriladigan
kirim xabarida ko'rinadi. Valyuta tanlangan tugma bilan belgilanadi.
Faqat summani yozish ham avvalgidek ishlaydi. Karta kirimida summani yozasiz.

## Dollar xarajatlari

Asosiy menyuda xarajat nomi va summani yozib, oxiriga `$` belgisini qo'ying:

- `Furnituraga 300$` — dollar qoldig'idan $300 ayiriladi.
- `Usta 12.50$` yoki `Usta 12,50 $` — dollar qoldig'idan $12.50 ayiriladi.

Summani musbat va ko'pi bilan ikki kasr xonasi bilan kiriting. Xarajat dollar sifatida
tarix, statistika va qabul qiluvchiga yuboriladigan xabarda ham ko'rsatiladi.
`$` belgisisiz xarajatlar so'mda hisoblanadi. `💳 Kartadan` bo'limi so'mda yuritiladi;
dollar xarajatini kiritish uchun `/cancel` bilan asosiy menyuga qayting.

## Karta hisobi

Karta hisobi so'mda yuritiladi. O'tkazmani bank ilovangizda bajarasiz, keyin botga yozasiz.

1. `💰 Pul oldim` → `💳 Karta` → `500000`: karta qoldig'iga 500 000 so'm qo'shiladi.
2. `💳 Kartadan` → `Ali 200000`: faqat karta qoldig'idan 200 000 so'm ayiriladi.
3. Karta qoldig'i 300 000 so'm bo'ladi; naqd so'm va dollar qoldiqlari o'zgarmaydi.

Kartadagi mablag' yetarli bo'lmasa, xarajat yozilmaydi. Har bir karta xarajati uchun
`💳 Kartadan` tugmasini bosing. Saqlangandan keyin bot asosiy menyuga qaytadi.
Hisobotni oladigan odamga har bir kirim va xarajat alohida yuboriladi.
Xabarda hisob turi (naqd so'm, dollar yoki karta), summa, vaqt, kirimda kimdan olingani
(kiritilgan bo'lsa) va xarajatda izohi ko'rsatiladi.
Qoldiqlar, statistika, tarix, dollar maydalash va reset haqidagi xabarlar unga yuborilmaydi.
Kassa amallari va to'liq hisobotlar faqat `CASHIER_ID` dagi kassir uchun ochiq.

Qabul qiluvchini almashtirish uchun serverdagi `.env` faylida `REPORT_CHAT_ID` ni yangilab,
botni qayta ishga tushiring. Yangi qabul qiluvchi botga `/start` yuborgan bo'lishi kerak.
Xabar yetib bormasa, operatsiya bazada saqlanadi va kassirga bu haqda bildiriladi.

## Statistika

Avval `Bugun`, `Shu oy` yoki `Barcha vaqt` davrini tanlang. Hisobotda faqat:

- Tanlangan davrdagi barcha xarajatlar: izoh, summa, naqd yoki karta hisobi va vaqt.
- Shu davrda jami sarflangan so'm (naqd va karta birga) va dollar alohida.
- Hozirgi naqd so'm, karta va dollar qoldiqlari.

Har bir xarajat alohida satrda chiqadi, bir xil nomdagilari ham alohida saqlanadi.
Ro'yxat vaqt bo'yicha tartiblanadi; uzun bo'lsa, to'liq holda bir nechta xabarga bo'linadi.
`Bugun` va `Shu oy` Toshkent vaqti bo'yicha joriy kun va kalendar oyni bildiradi.
`Barcha vaqt` mavjud bazadagi barcha xarajatlarni qamrab oladi.
Qoldiqlar tanlangan davrdan qat'i nazar hozirgi hisobni ko'rsatadi.
Dollar maydalash xarajatlar ro'yxati va jami sarfga qo'shilmaydi, qoldiqlarda hisobga olinadi.

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
