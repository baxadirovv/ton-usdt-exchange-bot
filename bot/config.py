"""
.env faylidan sozlamalarni o'qish va tekshirish.

Barcha maxfiy ma'lumotlar (bot token, admin ID, mnemonic, DB ulanish)
faqat .env faylida saqlanadi — kodga hech qachon yozilmaydi.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url


class ConfigError(Exception):
    """Noto'g'ri yoki yetishmayotgan sozlama."""


WALLET_VERSIONS = ("v5r1", "v4r2", "tg")
NETWORKS = ("mainnet", "testnet")
MNEMONIC_TYPES = ("auto", "ton", "multichain")

# USDT (Tether USD₮) jetton master manzili — TON mainnet
DEFAULT_USDT_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: tuple[int, ...]
    database_url: str

    ton_network: str            # mainnet | testnet
    ton_mnemonic: str           # 12 yoki 24 ta so'z
    ton_wallet_version: str     # v5r1 (W5) | v4r2 | tg (Telegram Gram Wallet)
    ton_mnemonic_type: str      # auto | ton | multichain
    toncenter_api_key: str | None
    usdt_jetton_master: str

    web_host: str
    web_port: int
    public_url: str

    rate_update_interval: int   # soniya
    payment_timeout_minutes: int
    broadcast_per_minute: int
    timezone: str
    web_enabled: bool = True     # o'rnatilgan /pay serveri (VPS). Hostingda PHP (public/pay.php) ishlatiladi

    @property
    def is_testnet(self) -> bool:
        return self.ton_network == "testnet"

    @property
    def database_url_safe(self) -> str:
        """Logga chiqarish uchun (parolsiz)."""
        try:
            return make_url(self.database_url).render_as_string(hide_password=True)
        except Exception:  # noqa: BLE001
            return "<noto'g'ri DATABASE_URL>"

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ConfigError(f"{name} butun son bo'lishi kerak, siz yozgan: {raw!r}") from e


def build_database_url() -> str:
    """MySQL ulanish manzilini .env dan yig'adi.

    1) DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME (tavsiya — parolda maxsus belgilar bo'lsa ham ishlaydi)
    2) yoki tayyor DATABASE_URL (mysql://..., mysql+aiomysql://..., sqlite+aiosqlite:///... — sinov uchun)
    """
    db_name = _env("DB_NAME")
    if db_name:
        query = {"charset": "utf8mb4"}
        socket = _env("DB_SOCKET")
        if socket:
            query["unix_socket"] = socket
        url = URL.create(
            "mysql+aiomysql",
            username=_env("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            host=_env("DB_HOST", "localhost"),
            port=_env_int("DB_PORT", 3306),
            database=db_name,
            query=query,
        )
        return url.render_as_string(hide_password=False)

    raw = _env("DATABASE_URL")
    if not raw:
        raise ConfigError(
            "MySQL sozlamalari topilmadi. .env ga DB_HOST, DB_USER, DB_PASSWORD, DB_NAME ni yozing."
        )
    try:
        url = make_url(raw)
    except Exception as e:  # noqa: BLE001
        raise ConfigError(f"DATABASE_URL noto'g'ri: {e}") from e
    if url.get_backend_name() == "mysql":
        url = url.set(drivername="mysql+aiomysql")
        if "charset" not in url.query:
            url = url.update_query_dict({"charset": "utf8mb4"})
        return url.render_as_string(hide_password=False)
    if url.get_backend_name() in ("sqlite", "postgresql"):
        return raw
    raise ConfigError("DATABASE_URL faqat MySQL (mysql+aiomysql://...) bo'lishi mumkin.")


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on", "ha")


def load_config(env_path: str | os.PathLike | None = None) -> Config:
    """.env ni yuklaydi va Config qaytaradi. Xato bo'lsa ConfigError (o'zbekcha matn)."""
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path, override=False, interpolate=False)

    token = _env("BOT_TOKEN")
    if not token or ":" not in token:
        raise ConfigError("BOT_TOKEN topilmadi yoki noto'g'ri. .env fayliga @BotFather bergan tokenni yozing.")

    raw_admins = _env("ADMIN_IDS") or _env("ADMIN_ID") or ""
    admin_ids: list[int] = []
    for part in raw_admins.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            admin_ids.append(int(part))
        except ValueError as e:
            raise ConfigError(f"ADMIN_IDS ichida noto'g'ri qiymat: {part!r} (faqat raqamli Telegram ID)") from e
    if not admin_ids:
        raise ConfigError("ADMIN_IDS bo'sh. Kamida bitta admin Telegram ID yozing (masalan: ADMIN_IDS=123456789).")

    mnemonic = " ".join((_env("TON_MNEMONIC") or "").replace('"', "").replace("'", "").split())
    words = mnemonic.split()
    if len(words) not in (12, 24):
        raise ConfigError(
            f"TON_MNEMONIC 12 yoki 24 ta so'zdan iborat bo'lishi kerak (hozir {len(words)} ta). "
            "So'zlarni bitta probel bilan ajratib yozing."
        )

    network = (_env("TON_NETWORK", "mainnet") or "mainnet").lower()
    if network not in NETWORKS:
        raise ConfigError(f"TON_NETWORK faqat mainnet yoki testnet bo'lishi mumkin, siz yozgan: {network!r}")

    version = (_env("TON_WALLET_VERSION", "v5r1") or "v5r1").lower()
    if version in ("w5", "v5", "wallet_v5", "v5r1"):
        version = "v5r1"
    elif version in ("v4", "w4", "v4r2"):
        version = "v4r2"
    if version not in WALLET_VERSIONS:
        raise ConfigError(
            f"TON_WALLET_VERSION noto'g'ri: {version!r}. Ruxsat etilgan: v5r1 (W5), v4r2, tg"
        )

    mnemonic_type = (_env("TON_MNEMONIC_TYPE", "auto") or "auto").lower()
    if mnemonic_type not in MNEMONIC_TYPES:
        raise ConfigError("TON_MNEMONIC_TYPE faqat auto, ton yoki multichain bo'lishi mumkin.")

    public_url = (_env("PUBLIC_URL", "https://cripto.smm-api.uz") or "").rstrip("/")
    database_url = build_database_url()

    return Config(
        bot_token=token,
        admin_ids=tuple(admin_ids),
        database_url=database_url,
        ton_network=network,
        ton_mnemonic=mnemonic,
        ton_wallet_version=version,
        ton_mnemonic_type=mnemonic_type,
        toncenter_api_key=_env("TONCENTER_API_KEY"),
        usdt_jetton_master=_env("USDT_JETTON_MASTER", DEFAULT_USDT_MASTER) or DEFAULT_USDT_MASTER,
        web_host=_env("WEB_HOST", "127.0.0.1") or "127.0.0.1",
        web_port=_env_int("WEB_PORT", 8080),
        public_url=public_url,
        web_enabled=_env_bool("WEB_ENABLED", True),
        rate_update_interval=max(20, _env_int("RATE_UPDATE_INTERVAL", 60)),
        payment_timeout_minutes=max(1, _env_int("PAYMENT_TIMEOUT_MINUTES", 5)),
        broadcast_per_minute=max(1, min(1500, _env_int("BROADCAST_PER_MINUTE", 500))),
        timezone=_env("TIMEZONE", "Asia/Tashkent") or "Asia/Tashkent",
    )
