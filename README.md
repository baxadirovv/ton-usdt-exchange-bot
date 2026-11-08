<div align="center">

# TON & USDT Exchange Bot

**A Telegram bot that buys and sells TON (Gram) and USDT for Uzbek so'm** — automatic on-chain payouts from a hot wallet, card top-ups confirmed by a payment callback, live market rates and a complete admin panel inside Telegram.

[English](README.md) · [O'zbekcha](README.uz.md)

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0_async-D71F00?logo=sqlalchemy&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL_%2F_MariaDB-utf8mb4-4479A1?logo=mysql&logoColor=white)
![TON](https://img.shields.io/badge/TON-TON_Center_%2B_USDT_jetton-0098EA?logo=ton&logoColor=white)

</div>

---

## Overview

A customer opens the bot, tops up the balance by bank card and buys TON or USDT: the bot signs a transaction with its own **hot wallet**, sends the coins to the customer's address and confirms the result on the blockchain — with no operator involved. Customers can also **sell** TON or USDT to the bot: they send the coins to the bot's wallet with a memo, upload a screenshot, and an admin confirms and pays the customer's card.

Prices, markup, limits, the top-up card, mandatory channels and the referral percentage are all managed by the admin **from the bot itself**; `.env` holds only technical and secret values.

### Highlights

- **Crash-safe on-chain payouts.** Every transfer is signed with an explicit `seqno` and a 60-second `valid_until`, and its hash, seqno and expiry are written to the database **before** the message is broadcast. After a crash or restart the bot re-checks that exact message instead of guessing.
- **Refund only on proof.** A customer is refunded automatically only when the *blockchain* clock has passed `valid_until` and no transaction with our message hash exists, or when our transaction is found and provably sent nothing. Anything unclear becomes `unknown` and goes to an admin (re-check / mark as sent / refund) — it is never refunded or marked as done on a guess.
- **Rates from several sources, with guards.** TON/USD is the median of CoinGecko, Binance and KuCoin (a source that is more than 10 % off is dropped); USD/UZS comes from the Central Bank of Uzbekistan (CBU) with three fallbacks. A jump of more than 25 % (TON) or 10 % (USD/UZS) between refreshes is rejected and the admins are alerted; rates older than 10 minutes pause trading.
- **Reserve-aware.** What can be bought is the hot-wallet balance minus a gas reserve (0.1 TON) minus the amounts already queued. Sold-out coins offer a one-tap "notify me when it is back" alert.
- **Card top-ups with unique amounts.** Each invoice gets an amount nobody else is paying right now, so an incoming payment can be matched to exactly one customer. Late payments are still credited, and a paid invoice can never match twice.
- **Money is integers.** UZS as integers, TON in nanoton, USDT in micro-USDT — no floats. Balances change only through atomic conditional `UPDATE … WHERE balance >= amount`, order statuses move through atomic compare-and-set transitions, and MySQL deadlocks are retried automatically.
- **Runs on shared hosting or a VPS.** cron + a PHP `/pay` receiver on cPanel-style hosting, or systemd + the built-in aiohttp server on a VPS. A file lock guarantees a single running instance — two bots can never sign with the same wallet.
- **Watches its own security.** Every 6 hours the bot probes its public URL and alerts the admins if `.env`, the source or the log can be downloaded.
- **Tested.** 54 automated tests run against a fake Telegram API and a fake TON network — no network, no money.

---

## Architecture

```mermaid
flowchart TB
    TG["Telegram<br/>Bot API"]
    BANK["Bank SMS / notification app<br/>payment callback"]

    subgraph SRV["Your server"]
        PAYIN["/pay receiver<br/>shared hosting: public/pay.php<br/>VPS: built-in aiohttp server"]
        subgraph APP["python main.py: one asyncio process"]
            DP["aiogram dispatcher<br/>menus · buy · sell · balance · admin panel"]
            PS["PaymentService<br/>unique-amount matching"]
            TW["TransferWorker<br/>one on-chain send at a time"]
            TS["TonService<br/>hot wallet: sign, send, confirm"]
            MS["MarketService<br/>rates + reserve, every 60 s"]
        end
        DB[("MySQL / MariaDB")]
    end

    TON["TON blockchain<br/>via TON Center"]
    RATES["Rate sources<br/>CoinGecko · Binance · KuCoin · CBU"]

    TG <-->|"long polling"| DP
    BANK -->|"GET / POST /pay"| PAYIN
    PAYIN -->|"hosting: row in pay_inbox"| DB
    PAYIN -.->|"VPS: direct call"| PS
    DB -->|"inbox polled every 2 s"| PS
    DP <-->|"users, orders, settings"| DB
    DP --> TW --> TS
    MS --> TS
    TS <--> TON
    MS --> RATES
```

The bot uses long polling, so it needs no inbound connection from Telegram — the only thing that must be reachable from the internet is the `/pay` address.

---

## Features

### For customers

- **🔄 Exchange** — buy or sell **TonCoin (Gram)** and **USDT (TON network)**. When buying, the quote is held for 2 minutes (the bot asks to re-confirm if the rate moved); when selling, the price is guaranteed for 30 minutes.
- **💵 Balance and 💳 top-up** — the customer enters an amount, receives a card number and an exact amount to transfer, and sees the invoice update the moment the payment lands. An invoice can be cancelled, and it expires after 5 minutes by default.
- **📊 Rates and reserve**, **📃 history** with order details and a Tonviewer link, **🔗 referral link** (the inviter earns a percentage of every completed exchange), **📚 guide** and **☎️ support**.
- **Mandatory channel subscription** before use, stock alerts for sold-out coins, and a block screen for banned users. The bot works only in private chats and ignores groups and channels.

### Admin panel (inside Telegram)

| Section | What the admin can do |
|---|---|
| 📊 Statistics | users, balances, orders by status, turnover in TON / USDT / so'm, net profit (total and today), referral bonuses paid |
| 💰 Prices & amounts | markup in so'm, minimum buy, sell min / max per coin, force-refresh rates and reserve, see rate sources and errors |
| 💳 Payment system | top-up card and holder, top-up limits, show the `/pay` callback URL, rotate the secret key |
| 🛠 Extra settings | admin username, news and history channels, receiving wallet for sells, switch buying on / off |
| ⚙️ User management | look up a user by Telegram ID, add or subtract balance, block / unblock |
| ✉️ Broadcast | any message type, forward or copy, live progress, stop button, 500 messages / minute by default |
| 📢 Channels | add, rename or remove mandatory-subscription channels |
| 🔗 Referral | the percentage and the top-10 inviters |
| Orders | approve or cancel sell requests (with the customer's screenshot); resolve uncertain transfers (`/unknown`) |

Admins also get a start-up report (wallet address, balances, rates, warnings) and instant alerts about unmatched payments, failed or uncertain transfers, rate anomalies and exposed files.

---

## How it works

### Buying: a safe on-chain payout

```mermaid
sequenceDiagram
    participant C as Customer
    participant B as Bot
    participant D as Database
    participant W as Transfer worker
    participant N as TON network
    C->>B: currency, amount, wallet address
    B-->>C: price (market + markup), valid for 2 minutes
    C->>B: confirm
    B->>D: one transaction: balance -= total, order = processing
    B->>W: queue the order, the amount is held in the reserve
    W->>D: processing → sending
    W->>N: read seqno, sign the message (valid_until = now + 60 s)
    W->>D: save message hash + seqno + valid_until BEFORE sending
    W->>N: broadcast the external message
    W->>N: wait for the seqno to advance, find the transaction by message hash
    alt transaction found and successful
        W->>D: sending → done, profit and referral bonus recorded
        W-->>C: done + Tonviewer link
    else provably never executed
        W->>D: sending → failed, balance refunded
        W-->>C: refunded
    else cannot be proven either way
        W->>D: sending → unknown
        W-->>B: alert the admins to decide
    end
```

How the outcome is decided:

| Evidence | Result |
|---|---|
| Our wallet transaction is found and succeeded (for USDT, the jetton-wallet transaction succeeded too) | `done` |
| Our transaction is found but failed, or it sent no outgoing message | `failed` — balance refunded |
| The blockchain clock passed `valid_until` + margin and no transaction with our message hash exists | `failed` — balance refunded |
| The seqno advanced but the transaction cannot be found, TON Center cannot be reached, or anything else is doubtful | `unknown` — an admin decides |

```mermaid
stateDiagram-v2
    [*] --> processing: balance charged
    processing --> sending: worker picks it up
    sending --> done: transfer confirmed
    sending --> failed: provably not sent
    sending --> unknown: cannot prove either way
    unknown --> sending: admin: re-check
    unknown --> done: admin: mark as sent
    unknown --> failed: admin: refund
    processing --> failed: invalid address, nothing sent
    done --> [*]
    failed --> [*]
```

After a restart the bot recovers by itself: queued orders go back into the queue, orders with a saved message hash are re-checked first (so seqnos cannot collide), and orders that were stuck before anything was signed are re-queued because nothing can have been sent.

### Selling: customer → bot

1. The customer picks the coin and amount (within the admin's limits). The bot shows its receiving wallet address and a random memo such as `S123456`; the price is guaranteed for 30 minutes.
2. The customer sends exactly that amount with the memo, uploads a screenshot and enters their card number.
3. Every admin receives the request with the screenshot, card, memo and a wallet link, plus **Approve / Cancel** buttons. After checking the incoming transfer, the admin pays the customer's card and approves; the customer is notified and the referral bonus and profit are recorded.
4. If the 30-minute guarantee has expired, the lower of the quoted and the current price is used, and the admin is warned if no live rate exists.

### Card top-ups with unique amounts

```mermaid
sequenceDiagram
    participant C as Customer
    participant B as Bot
    participant S as Bank SMS / notification app
    participant R as /pay receiver
    participant D as Database
    C->>B: top up 100 000 so'm
    B->>D: invoice with a unique amount (for example 100 007), 5-minute timer
    B-->>C: card number and the exact amount
    C->>S: transfers exactly 100 007 to the card
    S->>R: GET /pay?miqdor=100007.00&method=...&secret_key=...
    R->>D: queue the message (PHP) or call the bot directly (aiohttp)
    B->>D: match the amount to the pending invoice, balance += amount
    B-->>C: balance topped up
```

- If the requested amount is already used by another invoice created in the last 90 minutes, 1–50 so'm are added at random so that every invoice is unique.
- A payment that arrives after the invoice expired or was cancelled is still credited when the invoice was created within the last 45 minutes. A paid invoice is never matched again, so a duplicated SMS cannot credit twice.
- Payments that match nothing are logged and reported to the admins, who can credit the customer manually.
- With the PHP receiver, messages wait in the `pay_inbox` table, so a bot restart never loses a payment.

### Rates and reserve

| Value | Source | Rule |
|---|---|---|
| TON / USD | CoinGecko, Binance, KuCoin | median; a source more than 10 % away is dropped; if none agree the update fails |
| USDT / USD | CoinGecko | accepted only between 0.9 and 1.1, otherwise 1.0 |
| USD / UZS | Central Bank of Uzbekistan → open.er-api.com → currency-api (two mirrors) | cached for 30 minutes; the central bank is skipped for an hour after a failure |
| Reserve | hot-wallet TON and USDT balance via TON Center | refreshed together with the rates (60 s by default) |

The market price is `USD price × USD/UZS`. The customer **buys** at `market + markup` and **sells** at `market`. The profit of a purchase is `amount × (price − market) − referral bonus`.

---

## Tech stack

| Layer | Technology |
|---|---|
| Language / framework | Python 3.10+ (tested on 3.12 and 3.13), aiogram 3 (async, long polling) |
| Database | MySQL 5.7+ / 8 or MariaDB (InnoDB, utf8mb4) through SQLAlchemy 2 async and aiomysql; SQLite (aiosqlite) for tests and local experiments |
| Blockchain | tonutils + ton-core, TON Center API and its v3 indexer for verification; wallets W5 (v5r1), v4r2 and Telegram Gram Wallet; the USDT jetton |
| HTTP | aiohttp (rate sources, TON Center, optional built-in `/pay` server); PHP with PDO MySQL (tested on 8.3) for the hosting receiver |
| Deployment | cron (`run.sh`) or systemd (`deploy/install_service.sh`); Apache / LiteSpeed `.htaccess` or nginx |

---

## Project structure

```
ton-usdt-exchange-bot/
├── main.py                  entry point (python main.py)
├── run.sh                   cron helper: starts the bot if it is not running
├── check_wallet.py          shows which addresses your mnemonic produces (never prints the words)
├── requirements.txt         runtime dependencies (pinned)
├── requirements-dev.txt     + pytest
├── .env.example             configuration template
├── bot/
│   ├── app.py               start-up, wiring, logging, shutdown, exposure watch
│   ├── config.py            .env loading and validation
│   ├── runtime.py           single-instance lock, "is .env downloadable?" probe
│   ├── texts.py, utils.py   all bot texts (Uzbek), money formatting and parsing
│   ├── callbacks.py, states.py, helpers.py
│   ├── db/                  models.py · repo.py (atomic queries, deadlock retry) · session.py
│   ├── services/
│   │   ├── ton.py           hot wallet: balances, sign / send / confirm, transaction lookup
│   │   ├── exchange.py      TransferWorker queue, profit and referral bookkeeping
│   │   ├── market.py        rate sources, guards, reserve
│   │   ├── payments.py      unique-amount invoices, /pay matching, inbox poller
│   │   └── settings.py · notify.py · broadcast.py · channels.py
│   ├── handlers/            menu · exchange_buy · exchange_sell · balance · info · fallback · admin/
│   ├── keyboards/ · middlewares/    access gate (blocks, channels, referrals) · menu reset
│   └── web/server.py        built-in /pay server (VPS mode)
├── public/                  the only web-facing folder: pay.php (hosting receiver), index.html
├── deploy/install_service.sh    systemd installer
├── data/                    created at run time: bot.log, bot.lock (git-ignored)
├── .htaccess (several)      deny-all guards for Apache / LiteSpeed
└── tests/                   54 tests (fake Telegram, fake TON network)
```

---

## Setup guide

### 1. Requirements

- Python 3.10+ (3.12 recommended) and MySQL 5.7+ / 8 or MariaDB.
- A bot token from [@BotFather](https://t.me/BotFather) and your Telegram ID (send `/id` to the finished bot, or ask [@userinfobot](https://t.me/userinfobot)).
- A **dedicated** TON wallet for the bot — start on **testnet** (free coins from [@testgiver_ton_bot](https://t.me/testgiver_ton_bot)).
- A domain with HTTPS for `/pay`, and something that calls it when money arrives (for example a bank-SMS forwarder app).
- Optional but recommended: a free TON Center API key from the [@toncenter](https://t.me/toncenter) bot (without it requests are limited to about 1 per second).

### 2. Install and point the domain at `public/`

```bash
git clone https://github.com/baxadirovv/ton-usdt-exchange-bot.git
cd ton-usdt-exchange-bot
python3 -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env && chmod 600 .env                  # then edit .env
```

Create the database and its user (the tables are created automatically on the first start):

```sql
CREATE DATABASE exchange_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'exchange_bot'@'localhost' IDENTIFIED BY 'a-strong-password';
GRANT ALL PRIVILEGES ON exchange_bot.* TO 'exchange_bot'@'localhost';
```

Then decide what the internet may see — this matters because `.env` holds the wallet's secret words:

- **Best: make `public/` the domain's document root.** Only `pay.php` (served as `/pay`) and an empty `index.html` are reachable; `.env`, `bot/` and `data/` are outside the web root.
- **Project folder as the document root** (common on cPanel): the root `.htaccess` closes everything except `/pay`. This works on Apache and LiteSpeed only.
- **nginx:** use one of the server blocks in section 6.

### 3. Configure `.env`

Fill in at least `BOT_TOKEN`, `ADMIN_IDS`, the `DB_*` values, `TON_MNEMONIC`, `TON_NETWORK`, `PUBLIC_URL` and `WEB_ENABLED` (every variable is described in the [reference](#configuration-reference) below). Then check that your mnemonic gives the address you expect:

```bash
python check_wallet.py      # lists the addresses of every wallet version, then the TON / USDT balance of the selected one
```

Compare the printed address with the one in your wallet app and put the matching version into `TON_WALLET_VERSION` (`v5r1`, `v4r2` or `tg`).

### 4. Run

```bash
python main.py              # quick test in a terminal; Ctrl+C stops it
```

For production use **one** of these (never both):

- **Shared hosting — cron.** Add a cron job that runs every minute: `/bin/sh /home/USER/ton-usdt-exchange-bot/run.sh`. It does nothing while the bot is running (`data/bot.lock`) and restarts the bot within a minute if it crashed. Use `PYTHON=/path/to/python` to choose the interpreter; output goes to `data/cron.log` and `data/bot.log`.
- **VPS — systemd.** `sudo sh deploy/install_service.sh` installs and starts a service that restarts on failure, starts at boot and waits up to 90 seconds on shutdown for an in-flight transfer to finish. Optional variables: `RUN_USER=…` and `SERVICE_NAME=…`. Logs: `journalctl -u <service> -f`.

### 5. First-time setup in the admin panel

Send `/start` to the bot from an account listed in `ADMIN_IDS` and open **🎛 Admin panel**. The bot also sends the admins a start-up report with the hot-wallet address, balances and any warnings.

1. **💳 Payment system** — enter the card number and holder, set the top-up limits, then open the callback URL and give it to your SMS / notification forwarder: `https://<your-domain>/pay?miqdor={miqdor}&method=CardXabarBot&secret_key=<key>` (the key is generated on the first start and can be rotated at any time).
2. **💰 Prices & amounts** — set the markup (1 000 so'm by default) and the buy / sell limits.
3. **🛠 Extra settings** — admin username, the history channel (the bot must be its admin) and, optionally, a separate wallet for incoming sells.
4. **📢 Channels** — mandatory-subscription channels (the bot must be their admin).
5. **Fund the hot wallet** with TON (the bot always keeps 0.1 TON for gas) and with the USDT you want to sell.

### 6. Web server hardening

The bot checks this for you every 6 hours (it requests `/.env`, `/bot/config.py`, `/main.py` and `/data/bot.log` from `PUBLIC_URL` and alerts every admin if any of them is served) — but verify it yourself too: `curl -I https://your-domain/.env` must **not** return `200`.

**Apache / LiteSpeed** are covered by the included `.htaccess` files: the root one opens only `/pay`, and `bot/`, `data/`, `deploy/` and `tests/` are denied outright.

**nginx — VPS mode** (`WEB_ENABLED=true`): proxy `/pay` to the built-in server and answer 404 to everything else.

```nginx
server {
    listen 443 ssl;
    server_name example.com;
    # ssl_certificate / ssl_certificate_key: for example from certbot

    location ~ ^/pay/?$ {
        proxy_pass http://127.0.0.1:8080;          # WEB_HOST:WEB_PORT
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location / { return 404; }
}
```

**nginx — hosting mode** (`WEB_ENABLED=false`, PHP-FPM): serve only `public/`. The PHP-FPM user must be able to read `.env`, because `pay.php` takes the database settings from it.

```nginx
server {
    listen 443 ssl;
    server_name example.com;
    root /var/www/ton-usdt-exchange-bot/public;    # .env, bot/ and data/ stay outside the web root
    # ssl_certificate / ssl_certificate_key: for example from certbot

    location ~ ^/pay/?$ {
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root/pay.php;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;    # adjust to your PHP version
    }
    location / { return 404; }
}
```

### 7. Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests
```

By default the tests use an in-memory SQLite database, a fake Telegram API and a fake TON network, so nothing touches the network or any money. To run them against MySQL as well (this also enables the end-to-end test of `public/pay.php`, which needs the `php` command), point them at an **empty throw-away database** — the tests drop and recreate its tables:

```bash
TEST_DATABASE_URL="mysql+aiomysql://user:password@127.0.0.1:3306/test_db?charset=utf8mb4" python -m pytest -q tests
```

---

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | token from @BotFather (**required**) |
| `ADMIN_IDS` | — | Telegram IDs of the admins, comma-separated (**required**) |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SOCKET` | `localhost`, `3306`, —, `root`, —, — | MySQL / MariaDB connection; setting `DB_NAME` selects this mode, `DB_SOCKET` is for socket-only hosts |
| `DATABASE_URL` | — | ready-made alternative to `DB_*`: `mysql+aiomysql://…`, or `sqlite+aiosqlite:///…` for experiments |
| `TON_NETWORK` | `mainnet` | `mainnet` (real money) or `testnet` |
| `TON_MNEMONIC` | — | 12 or 24 secret words of the hot wallet (**required**) |
| `TON_WALLET_VERSION` | `v5r1` | `v5r1` (W5), `v4r2` or `tg` (Telegram Gram Wallet) |
| `TON_MNEMONIC_TYPE` | `auto` | `auto`, `ton` or `multichain` |
| `TONCENTER_API_KEY` | empty | free key; without it about 1 request per second |
| `USDT_JETTON_MASTER` | official Tether jetton | change only for another jetton or a testnet |
| `PUBLIC_URL` | — | **set it to your domain**; used for the payment URL and the exposure check (the built-in fallback is the author's own domain) |
| `WEB_ENABLED` | `true` | built-in `/pay` server (VPS); `false` on hosting where `public/pay.php` receives payments |
| `WEB_HOST`, `WEB_PORT` | `127.0.0.1`, `8080` | bind address of the built-in server |
| `RATE_UPDATE_INTERVAL` | `60` | seconds between rate and reserve refreshes (minimum 20) |
| `PAYMENT_TIMEOUT_MINUTES` | `5` | lifetime of a top-up invoice (minimum 1) |
| `BROADCAST_PER_MINUTE` | `500` | broadcast speed, 1–1500 |
| `TIMEZONE` | `Asia/Tashkent` | time zone used in messages |

Stored in the database and changed from the admin panel: markup (1 000 so'm), minimum buy (0.1 TON, 1 USDT), sell limits (0.1–100 TON, 1–1 000 USDT), top-up limits (10 000–10 000 000 so'm), referral percentage (2 %), the card, channels and the `/pay` secret key.

---

## Security

- **The hot wallet is real money.** Use a dedicated wallet, keep only the working balance on it and refill when needed. The mnemonic lives only in `.env` (git-ignored, mode `600`); the bot's code never logs it (only the wallet address), and `check_wallet.py` never prints it. Anyone who sees the words controls the funds and a leaked mnemonic **cannot be revoked** — move the funds to a new wallet.
- **`.env` and the source must not be downloadable.** Use `public/` as the document root or the provided `.htaccess` / nginx rules, and read the bot's exposure alerts seriously.
- **`/pay` is protected by a secret key** (random, 32 hex characters, stored in the database, compared in constant time, rotatable from the admin panel). The key travels in the query string, so serve `/pay` over HTTPS and rotate the key if it ever leaks.
- **Unique amounts and one-shot matching** stop a duplicated or delayed payment from crediting the wrong customer or crediting twice.
- **One instance only:** a file lock prevents two bots from signing with the same wallet and colliding on the seqno.
- **No guessing with money:** payouts are refunded only on proof, and every uncertain case waits for a human.
- **Private chats and per-user ordering:** the bot ignores groups and channels, and updates from one user are processed one at a time, so a double tap cannot race.
- **Process hardening:** the systemd unit sets `NoNewPrivileges` and `ProtectSystem=full`.
- Run on testnet first, and make sure you comply with the regulations that apply to you before exchanging real money.

---

## License

© 2026 Saidakbar Bohodirov. All rights reserved. The source is published for review and as a portfolio piece — please get in touch before using it commercially. The software moves real money and is provided as is, without warranty.

## Author

**Saidakbar Bohodirov** — Python backend developer building Telegram products, payment automation and APIs.
GitHub: [baxadirovv](https://github.com/baxadirovv) · Portfolio: [saidakbar-projects.uz](https://saidakbar-projects.uz)
