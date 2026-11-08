<div align="center">

# TON & USDT ayirboshlash boti

**TON (Gram) va USDT ni so'mga sotib oladigan va sotadigan Telegram bot** — hot wallet'dan blokcheynga avtomatik yuborish, to'lov callback'i bilan tasdiqlanadigan karta orqali balans to'ldirish, jonli bozor kurslari va Telegram ichidagi to'liq admin panel.

[English](README.md) · [O'zbekcha](README.uz.md)

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0_async-D71F00?logo=sqlalchemy&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL_%2F_MariaDB-utf8mb4-4479A1?logo=mysql&logoColor=white)
![TON](https://img.shields.io/badge/TON-TON_Center_%2B_USDT_jetton-0098EA?logo=ton&logoColor=white)

</div>

---

## Loyiha haqida

Mijoz botni ochadi, balansini bank kartasi orqali to'ldiradi va TON yoki USDT sotib oladi: bot o'zining **hot wallet**'i bilan tranzaksiyani imzolaydi, tangalarni mijozning manziliga yuboradi va natijani blokcheynda tasdiqlaydi — operatorning ishtirokisiz. Mijoz botga TON yoki USDT **sota** ham oladi: tangalarni bot hamyoniga izoh (memo) bilan yuboradi, skrinshot yuklaydi, admin tekshirib tasdiqlaydi va mijoz kartasiga pul o'tkazadi.

Narxlar, ustama, limitlar, balans to'ldirish kartasi, majburiy kanallar va referal foizi — hammasini admin **botning o'zidan** boshqaradi; `.env` faqat texnik va maxfiy qiymatlarni saqlaydi.

### Asosiy jihatlar

- **Buzilishga chidamli blokchein yuborish.** Har bir o'tkazma aniq `seqno` va 60 soniyalik `valid_until` bilan imzolanadi, uning hash'i, seqno'si va muddati xabar tarmoqqa yuborilishidan **oldin** bazaga yoziladi. Bot yiqilib qayta yonganda taxmin qilmaydi — aynan shu xabar natijasini qayta tekshiradi.
- **Pul faqat isbot bo'lganda qaytariladi.** Mijozga pul avtomatik faqat ikki holatda qaytariladi: *blokchein* soati `valid_until` dan o'tib ketgan va bizning xabar hash'i bilan tranzaksiya yo'q bo'lsa, yoki bizning tranzaksiyamiz topilib, unda hech narsa yuborilmagani aniq bo'lsa. Noaniq hamma holat `unknown` bo'lib adminga boradi (qayta tekshirish / yuborildi deb belgilash / qaytarish) — taxmin bilan na qaytariladi, na bajarilgan deb belgilanadi.
- **Kurs bir necha manbadan, himoyalar bilan.** TON/USD — CoinGecko, Binance va KuCoin'ning medianasi (10 % dan ko'p farq qilgan manba tashlanadi); USD/UZS — O'zbekiston Markaziy bankidan, uchta zaxira manba bilan. Yangilanishlar orasida 25 % (TON) yoki 10 % (USD/UZS) dan katta sakrash rad etiladi va adminlarga xabar boradi; 10 daqiqadan eski kurs savdoni to'xtatadi.
- **Zaxirani hisobga oladi.** Sotib olish mumkin bo'lgan miqdor = hot wallet balansi − gas zaxirasi (0.1 TON) − navbatdagi arizalar. Tugagan tanga uchun «kelganda xabar ber» tugmasi bor.
- **Noyob summali karta to'lovlari.** Har bir chekka shu daqiqada boshqa hech kim to'lamayotgan summa beriladi — kelgan to'lov aynan bitta mijozga mos keladi. Kechikkan to'lov ham hisobga olinadi, to'langan chek esa ikki marta mos kelmaydi.
- **Pul — butun sonlar.** So'm butun son, TON — nanoton, USDT — mikro-USDT; float yo'q. Balans faqat atomik shartli `UPDATE … WHERE balance >= summa` orqali o'zgaradi, ariza holatlari atomik compare-and-set o'tishlari bilan almashadi, MySQL deadlock'lari avtomatik qayta uriniladi.
- **Hosting yoki VPS'da ishlaydi.** cPanel kabi hostingda cron + PHP `/pay` qabul qiluvchisi, VPS'da systemd + o'rnatilgan aiohttp server. Fayl qulfi bitta nusxa ishlashini kafolatlaydi — ikki bot bir hamyon bilan imzolay olmaydi.
- **O'z xavfsizligini o'zi kuzatadi.** Bot har 6 soatda o'z ochiq manzilini tekshiradi va `.env`, kod yoki log internetdan yuklab olinadigan bo'lsa adminlarni ogohlantiradi.
- **Sinovdan o'tgan.** Telegram va TON tarmog'i soxta qilingan 54 ta avtomatik sinov — tarmoq ham, pul ham kerak emas.

---

## Arxitektura

```mermaid
flowchart TB
    TG["Telegram<br/>Bot API"]
    BANK["Bank SMS / bildirishnoma ilovasi<br/>to'lov callback'i"]

    subgraph SRV["Sizning serveringiz"]
        PAYIN["/pay qabul qiluvchi<br/>hosting: public/pay.php<br/>VPS: o'rnatilgan aiohttp server"]
        subgraph APP["python main.py: bitta asyncio jarayoni"]
            DP["aiogram dispatcher<br/>menyu · sotib olish · sotish · balans · admin panel"]
            PS["PaymentService<br/>noyob summa bo'yicha moslash"]
            TW["TransferWorker<br/>bir vaqtda bitta yuborish"]
            TS["TonService<br/>hot wallet: imzolash, yuborish, tasdiqlash"]
            MS["MarketService<br/>kurs + zaxira, har 60 s"]
        end
        DB[("MySQL / MariaDB")]
    end

    TON["TON blokcheyni<br/>TON Center orqali"]
    RATES["Kurs manbalari<br/>CoinGecko · Binance · KuCoin · Markaziy bank"]

    TG <-->|"long polling"| DP
    BANK -->|"GET / POST /pay"| PAYIN
    PAYIN -->|"hosting: pay_inbox ga yozuv"| DB
    PAYIN -.->|"VPS: to'g'ridan-to'g'ri"| PS
    DB -->|"inbox har 2 s o'qiladi"| PS
    DP <-->|"foydalanuvchi, ariza, sozlamalar"| DB
    DP --> TW --> TS
    MS --> TS
    TS <--> TON
    MS --> RATES
```

Bot long polling bilan ishlaydi, shuning uchun Telegram'dan kiruvchi ulanish kerak emas — internetdan ochiq bo'lishi shart bo'lgan yagona narsa — `/pay` manzili.

---

## Imkoniyatlar

### Mijozlar uchun

- **🔄 Valyuta ayirboshlash** — **TonCoin (Gram)** va **USDT (TON tarmog'i)** ni sotib olish yoki sotish. Sotib olishda narx 2 daqiqa ushlab turiladi (kurs o'zgargan bo'lsa bot qayta tasdiqlashni so'raydi); sotishda narx 30 daqiqa kafolatlanadi.
- **💵 Balans va 💳 to'ldirish** — mijoz summani yozadi, karta raqami va o'tkazish uchun aniq summani oladi, to'lov tushishi bilan chek xabari yangilanadi. Chekni bekor qilish mumkin, sukut bo'yicha 5 daqiqadan keyin muddati tugaydi.
- **📊 Kurs va zaxira**, ariza tafsilotlari va Tonviewer havolasi bilan **📃 tarix**, **🔗 referal havola** (taklif qiluvchi har bir bajarilgan ayirboshlashdan foiz oladi), **📚 qo'llanma** va **☎️ qo'llab-quvvatlash**.
- Foydalanishdan oldin **majburiy kanallarga obuna**, tugagan tangalar uchun xabar berish va bloklanganlar uchun alohida ekran. Bot faqat shaxsiy chatlarda ishlaydi, guruh va kanallarga javob bermaydi.

### Admin panel (Telegram ichida)

| Bo'lim | Admin nima qila oladi |
|---|---|
| 📊 Statistika | foydalanuvchilar, balanslar, holatlar bo'yicha arizalar, TON / USDT / so'mdagi aylanma, sof foyda (jami va bugun), to'langan referal bonuslar |
| 💰 Narxlar & Miqdor | so'mdagi ustama, minimal sotib olish, har tanga uchun sotish min / max, kurs va zaxirani majburan yangilash, manba va xatolarni ko'rish |
| 💳 To'lov tizimi | to'ldirish kartasi va egasi, to'ldirish limitlari, `/pay` callback manzilini ko'rsatish, secret key'ni almashtirish |
| 🛠 Qo'shimcha sozlamalar | admin username, yangiliklar va tarix kanallari, sotishda qabul qiladigan hamyon, sotib olishni yoqish / o'chirish |
| ⚙️ User boshqaruv | Telegram ID bo'yicha topish, balansga qo'shish yoki ayirish, bloklash / blokdan chiqarish |
| ✉️ Reklama yuborish | har qanday turdagi xabar, forward yoki nusxa, jonli hisobot, to'xtatish tugmasi, sukut bo'yicha daqiqasiga 500 ta |
| 📢 Kanallar | majburiy obuna kanallarini qo'shish, nomini o'zgartirish yoki o'chirish |
| 🔗 Referal | foiz va TOP-10 taklif qiluvchilar |
| Arizalar | sotish arizalarini (mijoz skrinshoti bilan) tasdiqlash yoki bekor qilish; noaniq o'tkazmalarni hal qilish (`/unknown`) |

Adminlar ishga tushish hisobotini (hamyon manzili, balanslar, kurslar, ogohlantirishlar) va mos kelmagan to'lovlar, muvaffaqiyatsiz yoki noaniq o'tkazmalar, kurs anomaliyalari va ochiq qolgan fayllar haqida zudlik bilan xabar oladi.

---

## Qanday ishlaydi

### Sotib olish: xavfsiz blokchein yuborish

```mermaid
sequenceDiagram
    participant C as Mijoz
    participant B as Bot
    participant D as Baza
    participant W as Transfer worker
    participant N as TON tarmog'i
    C->>B: valyuta, miqdor, hamyon manzili
    B-->>C: narx (bozor + ustama), 2 daqiqa amal qiladi
    C->>B: tasdiqlash
    B->>D: bitta tranzaksiya: balans -= jami, ariza = processing
    B->>W: arizani navbatga qo'yadi, miqdor zaxiradan band qilinadi
    W->>D: processing → sending
    W->>N: seqno o'qiladi, xabar imzolanadi (valid_until = hozir + 60 s)
    W->>D: xabar hash'i + seqno + valid_until YUBORISHDAN OLDIN saqlanadi
    W->>N: tashqi xabar tarmoqqa yuboriladi
    W->>N: seqno o'sishi kutiladi, tranzaksiya xabar hash'i bo'yicha topiladi
    alt tranzaksiya topildi va muvaffaqiyatli
        W->>D: sending → done, foyda va referal bonusi yoziladi
        W-->>C: bajarildi + Tonviewer havolasi
    else aniq bajarilmagan
        W->>D: sending → failed, balans qaytariladi
        W-->>C: pul qaytarildi
    else ikki tomonga ham isbotlab bo'lmaydi
        W->>D: sending → unknown
        W-->>B: adminlarga qaror qabul qilish uchun xabar
    end
```

Natija qanday aniqlanadi:

| Dalil | Natija |
|---|---|
| Bizning hamyon tranzaksiyamiz topildi va muvaffaqiyatli (USDT uchun jetton-wallet tranzaksiyasi ham) | `done` |
| Tranzaksiya topildi, lekin muvaffaqiyatsiz yoki chiquvchi xabar yo'q | `failed` — balans qaytariladi |
| Blokchein soati `valid_until` + zaxira vaqtdan o'tdi va bizning xabar hash'i bilan tranzaksiya yo'q | `failed` — balans qaytariladi |
| Seqno o'sdi, lekin tranzaksiya topilmadi, TON Center'ga ulanib bo'lmadi yoki boshqa har qanday shubha | `unknown` — admin hal qiladi |

```mermaid
stateDiagram-v2
    [*] --> processing: balansdan yechildi
    processing --> sending: worker oldi
    sending --> done: o'tkazma tasdiqlandi
    sending --> failed: aniq yuborilmagan
    sending --> unknown: isbotlab bo'lmaydi
    unknown --> sending: admin: qayta tekshirish
    unknown --> done: admin: yuborildi deb belgilash
    unknown --> failed: admin: pulni qaytarish
    processing --> failed: manzil noto'g'ri, hech narsa yuborilmadi
    done --> [*]
    failed --> [*]
```

Qayta ishga tushgandan keyin bot o'zi tiklanadi: navbatdagi arizalar yana navbatga qo'yiladi, xabar hash'i saqlangan arizalar birinchi bo'lib qayta tekshiriladi (seqno to'qnashmasligi uchun), hali hech narsa imzolanmagan arizalar esa — hech narsa yuborilgan bo'lishi mumkin emasligi uchun — qayta navbatga qo'yiladi.

### Sotish: mijoz → bot

1. Mijoz tanga va miqdorni tanlaydi (adminning limitlari doirasida). Bot o'zining qabul qiluvchi hamyon manzilini va `S123456` kabi tasodifiy izohni (memo) ko'rsatadi; narx 30 daqiqa kafolatlanadi.
2. Mijoz aynan shu miqdorni izoh bilan yuboradi, skrinshot yuklaydi va karta raqamini kiritadi.
3. Har bir admin skrinshot, karta, izoh va hamyon havolasi bilan birga **Tasdiqlash / Bekor qilish** tugmali arizani oladi. Kelgan o'tkazmani tekshirgach, admin mijoz kartasiga pul o'tkazadi va tasdiqlaydi; mijozga xabar boradi, referal bonusi va foyda yoziladi.
4. 30 daqiqalik kafolat tugagan bo'lsa, ko'rsatilgan va joriy narxning kichigi olinadi, jonli kurs bo'lmasa admin ogohlantiriladi.

### Noyob summali karta to'lovlari

```mermaid
sequenceDiagram
    participant C as Mijoz
    participant B as Bot
    participant S as Bank SMS / bildirishnoma ilovasi
    participant R as /pay qabul qiluvchi
    participant D as Baza
    C->>B: 100 000 so'm to'ldirmoqchiman
    B->>D: noyob summali chek (masalan 100 007), 5 daqiqalik taymer
    B-->>C: karta raqami va aniq summa
    C->>S: kartaga aynan 100 007 o'tkazadi
    S->>R: GET /pay?miqdor=100007.00&method=...&secret_key=...
    R->>D: xabar navbatga yoziladi (PHP) yoki bot chaqiriladi (aiohttp)
    B->>D: summa kutilayotgan chekka moslanadi, balans += summa
    B-->>C: balans to'ldirildi
```

- So'ralgan summa oxirgi 90 daqiqada yaratilgan boshqa chekda ishlatilgan bo'lsa, har bir chek noyob bo'lishi uchun tasodifiy 1–50 so'm qo'shiladi.
- Chek muddati tugaganidan yoki bekor qilinganidan keyin kelgan to'lov ham, chek oxirgi 45 daqiqa ichida yaratilgan bo'lsa, hisobga olinadi. To'langan chek qayta mos kelmaydi, shuning uchun takrorlangan SMS ikki marta pul qo'shmaydi.
- Hech bir chekka mos kelmagan to'lovlar jurnalga yoziladi va adminlarga xabar beriladi — admin mijozga qo'lda qo'shishi mumkin.
- PHP qabul qiluvchi bilan xabarlar `pay_inbox` jadvalida kutadi, shuning uchun botning qayta yonishi to'lovni yo'qotmaydi.

### Kurs va zaxira

| Qiymat | Manba | Qoida |
|---|---|---|
| TON / USD | CoinGecko, Binance, KuCoin | mediana; 10 % dan ko'p farq qilgan manba tashlanadi; birortasi ham mos kelmasa yangilanish bekor |
| USDT / USD | CoinGecko | faqat 0.9 – 1.1 oralig'ida qabul qilinadi, aks holda 1.0 |
| USD / UZS | O'zbekiston Markaziy banki → open.er-api.com → currency-api (ikki nusxa) | 30 daqiqa keshlanadi; Markaziy bank xato bersa bir soat so'ralmaydi |
| Zaxira | hot wallet'ning TON va USDT balansi (TON Center orqali) | kurs bilan birga yangilanadi (sukut bo'yicha 60 s) |

Bozor narxi = `USD narxi × USD/UZS`. Mijoz **sotib oladi** `bozor + ustama` narxida va **sotadi** `bozor` narxida. Sotib olishdan foyda = `miqdor × (narx − bozor) − referal bonusi`.

---

## Texnologiyalar

| Qatlam | Texnologiya |
|---|---|
| Til / freymvork | Python 3.10+ (3.12 va 3.13 da sinalgan), aiogram 3 (async, long polling) |
| Baza | MySQL 5.7+ / 8 yoki MariaDB (InnoDB, utf8mb4) — SQLAlchemy 2 async va aiomysql orqali; sinov va mahalliy tajribalar uchun SQLite (aiosqlite) |
| Blokchein | tonutils + ton-core, TON Center API va tekshiruv uchun uning v3 indekstori; W5 (v5r1), v4r2 va Telegram Gram Wallet hamyonlari; USDT jetton |
| HTTP | aiohttp (kurs manbalari, TON Center, ixtiyoriy o'rnatilgan `/pay` server); hosting qabul qiluvchisi uchun PDO MySQL li PHP (8.3 da sinalgan) |
| Joylashtirish | cron (`run.sh`) yoki systemd (`deploy/install_service.sh`); Apache / LiteSpeed `.htaccess` yoki nginx |

---

## Loyiha tuzilmasi

```
ton-usdt-exchange-bot/
├── main.py                  kirish nuqtasi (python main.py)
├── run.sh                   cron yordamchisi: bot ishlamayotgan bo'lsa ishga tushiradi
├── check_wallet.py          mnemonicdan qaysi manzillar chiqishini ko'rsatadi (so'zlarni chiqarmaydi)
├── requirements.txt         ish uchun kutubxonalar (versiyalari qotirilgan)
├── requirements-dev.txt     + pytest
├── .env.example             sozlamalar namunasi
├── bot/
│   ├── app.py               ishga tushirish, ulash, log, to'xtatish, ochiqlik nazorati
│   ├── config.py            .env ni o'qish va tekshirish
│   ├── runtime.py           yagona nusxa qulfi, ".env yuklab olinadimi?" tekshiruvi
│   ├── texts.py, utils.py   botning barcha matnlari (o'zbekcha), pulni formatlash va o'qish
│   ├── callbacks.py, states.py, helpers.py
│   ├── db/                  models.py · repo.py (atomik so'rovlar, deadlock qayta urinish) · session.py
│   ├── services/
│   │   ├── ton.py           hot wallet: balans, imzolash / yuborish / tasdiqlash, tranzaksiya qidirish
│   │   ├── exchange.py      TransferWorker navbati, foyda va referal hisobi
│   │   ├── market.py        kurs manbalari, himoyalar, zaxira
│   │   ├── payments.py      noyob summali cheklar, /pay moslash, inbox o'quvchi
│   │   └── settings.py · notify.py · broadcast.py · channels.py
│   ├── handlers/            menu · exchange_buy · exchange_sell · balance · info · fallback · admin/
│   ├── keyboards/ · middlewares/    kirish nazorati (blok, kanallar, referal) · menyuga qaytarish
│   └── web/server.py        o'rnatilgan /pay server (VPS rejimi)
├── public/                  internetga qaragan yagona papka: pay.php (hosting qabul qiluvchisi), index.html
├── deploy/install_service.sh    systemd o'rnatuvchisi
├── data/                    ish vaqtida yaratiladi: bot.log, bot.lock (git ga kirmaydi)
├── .htaccess (bir nechta)   Apache / LiteSpeed uchun yopuvchi qoidalar
└── tests/                   54 ta sinov (soxta Telegram, soxta TON tarmog'i)
```

---

## Ishga tushirish

### 1. Talablar

- Python 3.10+ (3.12 tavsiya etiladi) va MySQL 5.7+ / 8 yoki MariaDB.
- [@BotFather](https://t.me/BotFather) dan bot tokeni va sizning Telegram ID'ingiz (tayyor botga `/id` yuboring yoki [@userinfobot](https://t.me/userinfobot) dan so'rang).
- Bot uchun **alohida** TON hamyon — **testnet**dan boshlang ([@testgiver_ton_bot](https://t.me/testgiver_ton_bot) bepul tanga beradi).
- `/pay` uchun HTTPS'li domen va pul tushganda uni chaqiradigan narsa (masalan, bank SMS'larini yo'naltiruvchi ilova).
- Ixtiyoriy, lekin tavsiya etiladi: [@toncenter](https://t.me/toncenter) botidan bepul TON Center API kaliti (kalitsiz so'rovlar soniyasiga taxminan 1 ta bilan cheklanadi).

### 2. O'rnatish va domenni `public/` ga qaratish

```bash
git clone https://github.com/baxadirovv/ton-usdt-exchange-bot.git
cd ton-usdt-exchange-bot
python3 -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env && chmod 600 .env                  # keyin .env ni tahrirlang
```

Baza va uning foydalanuvchisini yarating (jadvallar birinchi ishga tushishda avtomatik yaratiladi):

```sql
CREATE DATABASE exchange_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'exchange_bot'@'localhost' IDENTIFIED BY 'kuchli-parol';
GRANT ALL PRIVILEGES ON exchange_bot.* TO 'exchange_bot'@'localhost';
```

Endi internet nimani ko'rishi mumkinligini hal qiling — bu muhim, chunki `.env` da hamyonning maxfiy so'zlari bor:

- **Eng yaxshisi: domenning document root'ini `public/` ga qaratish.** Faqat `pay.php` (`/pay` sifatida) va bo'sh `index.html` ochiq bo'ladi; `.env`, `bot/` va `data/` web-papkadan tashqarida qoladi.
- **Document root — loyiha papkasi** (cPanel'da odatiy): ildizdagi `.htaccess` `/pay` dan boshqa hamma narsani yopadi. Bu faqat Apache va LiteSpeed'da ishlaydi.
- **nginx:** 6-bo'limdagi server bloklaridan birini ishlating.

### 3. `.env` ni to'ldirish

Kamida `BOT_TOKEN`, `ADMIN_IDS`, `DB_*` qiymatlari, `TON_MNEMONIC`, `TON_NETWORK`, `PUBLIC_URL` va `WEB_ENABLED` ni yozing (har bir o'zgaruvchi quyidagi [jadvalda](#sozlamalar-jadvali) tushuntirilgan). Keyin mnemonic siz kutgan manzilni berayotganini tekshiring:

```bash
python check_wallet.py      # hamyonning barcha versiyalari manzillarini, so'ng tanlanganining TON / USDT balansini ko'rsatadi
```

Chiqqan manzilni hamyon ilovangizdagi manzil bilan solishtiring va mos versiyani `TON_WALLET_VERSION` ga yozing (`v5r1`, `v4r2` yoki `tg`).

### 4. Ishga tushirish

```bash
python main.py              # terminalda tezkor sinov; Ctrl+C to'xtatadi
```

Ish rejimida quyidagilardan **bittasini** ishlating (ikkalasini emas):

- **Hosting — cron.** Har daqiqada ishlaydigan cron vazifa qo'shing: `/bin/sh /home/USER/ton-usdt-exchange-bot/run.sh`. Bot ishlab turganda u hech narsa qilmaydi (`data/bot.lock`), bot yiqilsa — bir daqiqa ichida qayta ishga tushiradi. Python yo'lini `PYTHON=/yo'l/python` bilan ko'rsating; chiqish `data/cron.log` va `data/bot.log` ga yoziladi.
- **VPS — systemd.** `sudo sh deploy/install_service.sh` xizmatni o'rnatadi va ishga tushiradi: yiqilsa qayta turadi, server yonganda o'zi boshlanadi, to'xtatishda esa ketayotgan o'tkazma tugashini 90 soniyagacha kutadi. Ixtiyoriy o'zgaruvchilar: `RUN_USER=…` va `SERVICE_NAME=…`. Log: `journalctl -u <xizmat> -f`.

### 5. Admin panelni birinchi marta sozlash

`ADMIN_IDS` dagi akkauntdan botga `/start` yuboring va **🎛 Admin panel** ni oching. Bot adminlarga hot wallet manzili, balanslar va ogohlantirishlar bilan ishga tushish hisobotini ham yuboradi.

1. **💳 To'lov tizimi** — karta raqami va egasini kiriting, to'ldirish limitlarini belgilang, so'ng callback manzilini oching va SMS / bildirishnoma yo'naltiruvchisiga bering: `https://<sizning-domeningiz>/pay?miqdor={miqdor}&method=CardXabarBot&secret_key=<kalit>` (kalit birinchi ishga tushishda yaratiladi va istalgan payt almashtiriladi).
2. **💰 Narxlar & Miqdor** — ustamani (sukut bo'yicha 1 000 so'm) va sotib olish / sotish limitlarini belgilang.
3. **🛠 Qo'shimcha sozlamalar** — admin username, tarix kanali (bot uning admini bo'lishi shart) va ixtiyoriy ravishda sotishda tangalar keladigan alohida hamyon.
4. **📢 Kanallar** — majburiy obuna kanallari (bot ularning admini bo'lishi shart).
5. **Hot wallet'ni to'ldiring** — TON bilan (bot gas uchun doim 0.1 TON qoldiradi) va sotmoqchi bo'lgan USDT bilan.

### 6. Web-serverni himoyalash

Buni bot sizning o'rningizga har 6 soatda tekshiradi (`PUBLIC_URL` dan `/.env`, `/bot/config.py`, `/main.py` va `/data/bot.log` ni so'raydi va birortasi ochiq bo'lsa barcha adminlarni ogohlantiradi) — lekin o'zingiz ham tekshiring: `curl -I https://sizning-domeningiz/.env` **200 qaytarmasligi** shart.

**Apache / LiteSpeed** uchun hammasi tayyor `.htaccess` fayllarida: ildizdagisi faqat `/pay` ni ochadi, `bot/`, `data/`, `deploy/` va `tests/` esa butunlay yopiq.

**nginx — VPS rejimi** (`WEB_ENABLED=true`): `/pay` ni o'rnatilgan serverga yo'naltiring, qolgan hammasiga 404 qaytaring.

```nginx
server {
    listen 443 ssl;
    server_name example.com;
    # ssl_certificate / ssl_certificate_key: masalan certbot'dan

    location ~ ^/pay/?$ {
        proxy_pass http://127.0.0.1:8080;          # WEB_HOST:WEB_PORT
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location / { return 404; }
}
```

**nginx — hosting rejimi** (`WEB_ENABLED=false`, PHP-FPM): faqat `public/` ni xizmat qildiring. PHP-FPM foydalanuvchisi `.env` ni o'qiy olishi kerak, chunki `pay.php` baza sozlamalarini undan oladi.

```nginx
server {
    listen 443 ssl;
    server_name example.com;
    root /var/www/ton-usdt-exchange-bot/public;    # .env, bot/ va data/ web-papkadan tashqarida qoladi
    # ssl_certificate / ssl_certificate_key: masalan certbot'dan

    location ~ ^/pay/?$ {
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root/pay.php;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;    # PHP versiyangizga moslang
    }
    location / { return 404; }
}
```

### 7. Sinovlar

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests
```

Sukut bo'yicha sinovlar xotiradagi SQLite bazasi, soxta Telegram API va soxta TON tarmog'idan foydalanadi — tarmoqqa ham, pulga ham tegmaydi. Ularni MySQL'da ham ishga tushirish uchun (bu `php` buyrug'i kerak bo'ladigan `public/pay.php` ning to'liq sinovini ham yoqadi) **bo'sh, vaqtinchalik bazani** ko'rsating — sinovlar uning jadvallarini o'chirib qayta yaratadi:

```bash
TEST_DATABASE_URL="mysql+aiomysql://user:parol@127.0.0.1:3306/test_db?charset=utf8mb4" python -m pytest -q tests
```

---

## Sozlamalar jadvali

| O'zgaruvchi | Standart | Tavsif |
|---|---|---|
| `BOT_TOKEN` | — | @BotFather tokeni (**majburiy**) |
| `ADMIN_IDS` | — | adminlarning Telegram ID'lari, vergul bilan (**majburiy**) |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SOCKET` | `localhost`, `3306`, —, `root`, —, — | MySQL / MariaDB ulanishi; `DB_NAME` yozilsa shu rejim tanlanadi, `DB_SOCKET` — faqat socket orqali ishlaydigan hostinglar uchun |
| `DATABASE_URL` | — | `DB_*` o'rniga tayyor manzil: `mysql+aiomysql://…`, tajriba uchun `sqlite+aiosqlite:///…` |
| `TON_NETWORK` | `mainnet` | `mainnet` (haqiqiy pul) yoki `testnet` |
| `TON_MNEMONIC` | — | hot wallet'ning 12 yoki 24 ta maxfiy so'zi (**majburiy**) |
| `TON_WALLET_VERSION` | `v5r1` | `v5r1` (W5), `v4r2` yoki `tg` (Telegram Gram Wallet) |
| `TON_MNEMONIC_TYPE` | `auto` | `auto`, `ton` yoki `multichain` |
| `TONCENTER_API_KEY` | bo'sh | bepul kalit; kalitsiz soniyasiga taxminan 1 ta so'rov |
| `USDT_JETTON_MASTER` | rasmiy Tether jetton | faqat boshqa jetton yoki testnet uchun o'zgartiring |
| `PUBLIC_URL` | — | **o'z domeningizni yozing**; to'lov manzili va ochiqlik tekshiruvi uchun ishlatiladi (kodning ichki zaxira qiymati muallifning o'z domeni) |
| `WEB_ENABLED` | `true` | o'rnatilgan `/pay` server (VPS); to'lovni `public/pay.php` qabul qiladigan hostingda `false` |
| `WEB_HOST`, `WEB_PORT` | `127.0.0.1`, `8080` | o'rnatilgan server manzili |
| `RATE_UPDATE_INTERVAL` | `60` | kurs va zaxirani yangilash oralig'i, soniya (kamida 20) |
| `PAYMENT_TIMEOUT_MINUTES` | `5` | to'ldirish chekining amal qilish muddati (kamida 1) |
| `BROADCAST_PER_MINUTE` | `500` | reklama tezligi, 1–1500 |
| `TIMEZONE` | `Asia/Tashkent` | xabarlarda ishlatiladigan vaqt mintaqasi |

Bazada saqlanadi va admin paneldan o'zgartiriladi: ustama (1 000 so'm), minimal sotib olish (0.1 TON, 1 USDT), sotish limitlari (0.1–100 TON, 1–1 000 USDT), to'ldirish limitlari (10 000–10 000 000 so'm), referal foizi (2 %), karta, kanallar va `/pay` secret key.

---

## Xavfsizlik

- **Hot wallet — haqiqiy pul.** Alohida hamyondan foydalaning, unda faqat ishchi balansni saqlang va kerak bo'lganda to'ldiring. Mnemonic faqat `.env` da turadi (git ga kirmaydi, ruxsat `600`); botning kodi uni hech qachon logga yozmaydi (faqat hamyon manzilini), `check_wallet.py` ham uni chiqarmaydi. Kim so'zlarni ko'rsa, mablag'ni boshqaradi va oshkor bo'lgan mnemonicni **bekor qilib bo'lmaydi** — mablag'ni yangi hamyonga o'tkazing.
- **`.env` va kod internetdan yuklab olinmasligi shart.** `public/` ni document root qiling yoki tayyor `.htaccess` / nginx qoidalarini ishlating, botning ochiqlik haqidagi ogohlantirishlarini jiddiy qabul qiling.
- **`/pay` secret key bilan himoyalangan** (tasodifiy, 32 ta hex belgi, bazada saqlanadi, doimiy vaqtda solishtiriladi, admin paneldan almashtiriladi). Kalit so'rov satrida yuboriladi, shuning uchun `/pay` ni HTTPS orqali ishlating va kalit oshkor bo'lsa uni almashtiring.
- **Noyob summalar va bir martalik moslash** takrorlangan yoki kechikkan to'lovning noto'g'ri mijozga yoki ikki marta yozilishiga yo'l qo'ymaydi.
- **Faqat bitta nusxa:** fayl qulfi ikki botning bir hamyon bilan imzolashi va seqno'da to'qnashishining oldini oladi.
- **Pul bilan taxmin yo'q:** pul faqat isbot bo'lganda qaytariladi, har bir noaniq holat odamni kutadi.
- **Shaxsiy chatlar va foydalanuvchi bo'yicha navbat:** bot guruh va kanallarni e'tiborsiz qoldiradi, bir foydalanuvchining hodisalari ketma-ket qayta ishlanadi — ikki marta bosish poyga yaratmaydi.
- **Jarayon himoyasi:** systemd xizmati `NoNewPrivileges` va `ProtectSystem=full` dan foydalanadi.
- Avval testnet'da sinab ko'ring va haqiqiy pul ayirboshlashdan oldin o'zingizga tegishli qonunlarga rioya qilishingizga ishonch hosil qiling.

---

## Litsenziya

© 2026 Saidakbar Bohodirov. Barcha huquqlar himoyalangan. Kod ko'rib chiqish va portfolio sifatida e'lon qilingan — tijoriy maqsadda foydalanishdan oldin menga murojaat qiling. Dastur haqiqiy pul bilan ishlaydi va kafolatsiz, «boricha» taqdim etiladi.

## Muallif

**Saidakbar Bohodirov** — Telegram mahsulotlari, to'lov avtomatizatsiyasi va API lar yaratadigan Python backend dasturchi.
GitHub: [baxadirovv](https://github.com/baxadirovv) · Portfolio: [saidakbar-projects.uz](https://saidakbar-projects.uz)
