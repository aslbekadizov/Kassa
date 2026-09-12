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
- `👥 Mijozlar` yoki `/mijozlar` — mijoz qo'shish va uning alohida hisobini ochish.
- `🧾 Boshqa xarajatlar` yoki `/boshqa` — mijozga tegishli bo'lmagan xarajatlar.
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

## Mijozlar hisobi

Mijozlar ro'yxati bo'sh boshlanadi. Eski kirim va xarajatlar, hatto izohida mijoz
ismi bo'lsa ham, mijozlarga avtomatik biriktirilmaydi va o'zgartirilmaydi.

1. `👥 Mijozlar` → `➕ Mijoz qo'shish` → mijozning ismini yozing.
2. Ismni yozgach bot darhol kirim turini so'raydi: so'm, dollar, karta yoki `💵 Dollar + 💳 Karta`.
3. Kerakli hisobni tanlang va miqdorni yozing. `Dollar + Karta` bo'lsa, avval dollarni,
   keyin kartaga tushgan so'mni yozasiz. Masalan: `300` dollar, keyin `500000` so'm karta.
4. Shu oynaga `Material 150000` yoki `Furnituraga 300$` yozsangiz, xarajat tanlangan mijozga yoziladi.
5. Kartadan xarajat uchun `💳 Mijoz uchun kartadan` tugmasini bosing, keyin `Usta 200000` deb yozing.
6. `📒 Mijoz hisobi` barcha kirim va xarajatlarni, jami olingan, ishlatilgan va qolgan pulni ko'rsatadi.

`Dollar + Karta` kirimining ikkala qismi karta summasi kiritilgach birga saqlanadi.
O'rtada bekor qilinsa, pul yozilmaydi; mijozning nomi saqlanadi. Hozircha pul
olinmagan bo'lsa ham `/cancel` bilan mijoz oynasiga o'tishingiz mumkin.
Keyingi safar mijozni ro'yxatdan tanlang. Yana kirim qo'shish uchun uning oynasida
`💰 Mijozdan pul oldim`ni bosing — shu to'rtta variant yana chiqadi.

Mijoz hisobidagi so'm (naqd va karta birga) va dollar alohida yuritiladi.
Mijoz qoldig'i — undan olingan puldan unga sarflangan pul ayirmasi; ko'proq
sarflansa, minus ko'rinadi. Dollar avtomatik ravishda so'mga aylantirilmaydi.
Har bir operatsiya umumiy naqd, dollar yoki karta qoldig'iga ham bir marta ta'sir qiladi.
Karta xarajati uchun umumiy kartadagi pul yetarli bo'lishi kerak.

Yozuv saqlangach mijoz oynasi ochiq qoladi. `/cancel` joriy kiritishni bekor qilib,
shu mijozga qaytaradi. Boshqa mijozga o'tish uchun `👥 Mijozlar`ni, umumiy hisobga
qaytish uchun `⬅️ Asosiy menyu`ni bosing. Oddiy `💰 Pul oldim` tugmasi umumiy kirim uchun.

Mijoz nomi 80 belgigacha bo'lishi mumkin. Katta-kichik harf va ortiqcha bo'shliqlar
bilan farqlanadigan nom qayta qo'shilsa, mavjud hisob ochiladi. Ismi bir xil ikki
mijoz uchun familiya yoki boshqa farqlovchi izohni nomga qo'shing.
Ro'yxat uzun bo'lsa, keyingi va oldingi sahifa tugmalari chiqadi.
Mijozlar va ularning yozuvlari bazada saqlanadi; bot qayta ishga tushganda mijozni qayta tanlang.

## Boshqa xarajatlar

`🧾 Boshqa xarajatlar` oynasida `Ijara 200000` yoki `Transport 20$` deb yozing.
Kartadan to'lov uchun `💳 Boshqa xarajat kartadan` tugmasini bosing.
Bu yozuvlar hech bir mijozga biriktirilmaydi, umumiy kassadan ayiriladi.
`📒 Boshqa xarajatlar hisobi` mijozga biriktirilmagan barcha xarajatlarni va jami
sarflangan so'm hamda dollarni ko'rsatadi. Eski mijozsiz xarajatlar ham shu ro'yxatda qoladi.
Asosiy menyuda avvalgidek to'g'ridan-to'g'ri yozilgan xarajatlar ham mijozsiz saqlanadi.

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
Mijoz oynasidan yozilgan kirim va xarajat xabarida mijozning nomi ham chiqadi.
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

Yangi kod birinchi ishga tushganda mavjud bazaga mijozlar uchun bo'sh ro'yxat va
operatsiyaga mijozni biriktirish maydonini qo'shadi. Eski operatsiyalar, ularning
summalari, naqd/karta hisobi va qoldiqlari saqlanadi; ularga mijoz biriktirilmaydi.
Mahalliy `.env` va `kassa.db` saqlanadi. Telegramda `/start` yuborib yangi menyuni oching.

`/reset` tasdiqlanganda mijozlarning kirim va xarajatlari ham umumiy tarix bilan
birga tozalanadi. Mijoz nomlari qoladi, ularning hisoblari 0 bo'ladi.
Avval olinadigan baza zaxirasi mijozlarni ham, barcha operatsiyalarni ham saqlaydi.

## Tekshirish

```sh
.venv/bin/python -m unittest -v test_kassa.py test_clients.py
```

Testlar vaqtinchalik bazadan foydalanadi; Telegramga haqiqiy xabar yubormaydi.
