#!/bin/sh
# =====================================================================
#  Botni systemd xizmati sifatida o'rnatish: 24/7 ishlaydi, yiqilsa 5 soniyada
#  qayta turadi, server qayta yonganda o'zi ishga tushadi.
#
#  Ishlatish (root bilan, loyiha papkasida):
#      sh deploy/install_service.sh
#
#  Kod yangilangandan keyin ham shu buyruq — xizmat yangilanib, qayta ishga tushadi.
#  Ixtiyoriy sozlash:  RUN_USER=www-data SERVICE_NAME=cripto-bot sh deploy/install_service.sh
# =====================================================================
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Root bilan ishga tushiring:  sudo sh deploy/install_service.sh"
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
    echo "❌ systemd topilmadi — README dagi cron (run.sh) usulidan foydalaning."
    exit 1
fi

DIR=$(cd "$(dirname "$0")/.." && pwd)
SERVICE=${SERVICE_NAME:-cripto-bot}
PY="$DIR/venv/bin/python"
UNIT="/etc/systemd/system/$SERVICE.service"

# ---------- tekshiruvlar ----------
if [ ! -f "$DIR/main.py" ] || [ ! -f "$DIR/bot/app.py" ]; then
    echo "❌ $DIR — bot papkasi emas (main.py topilmadi)."
    exit 1
fi
if [ ! -x "$PY" ]; then
    echo "❌ Virtual muhit topilmadi: $PY"
    echo "   Avval:  cd \"$DIR\" && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
    exit 1
fi
if ! "$PY" -c "import aiogram, sqlalchemy, aiomysql, tonutils" >/dev/null 2>&1; then
    echo "❌ Kutubxonalar to'liq o'rnatilmagan:  \"$PY\" -m pip install -r \"$DIR/requirements.txt\""
    exit 1
fi
if [ ! -f "$DIR/.env" ]; then
    echo "❌ $DIR/.env topilmadi:  cp .env.example .env  va qiymatlarni to'ldiring."
    exit 1
fi

# ---------- xizmat foydalanuvchisi ----------
# Sayt egasi (FastPanel: /var/www/<foydalanuvchi>/data/www/...). PHP (pay.php) ham shu nomdan ishlaydi,
# shuning uchun .env ni ikkalasi ham o'qiy oladi, boshqalar esa — yo'q.
if [ -z "${RUN_USER:-}" ]; then
    RUN_USER=$(stat -c %U "$DIR/..")
    [ "$RUN_USER" = "root" ] && RUN_USER=$(stat -c %U "$DIR")
    if [ "$RUN_USER" = "root" ]; then
        if id www >/dev/null 2>&1; then RUN_USER=www          # aaPanel
        elif id www-data >/dev/null 2>&1; then RUN_USER=www-data  # Ubuntu/Debian nginx, apache
        fi
    fi
fi
if ! id "$RUN_USER" >/dev/null 2>&1; then
    echo "❌ Foydalanuvchi topilmadi: $RUN_USER  (RUN_USER=... bilan ko'rsating)"
    exit 1
fi
RUN_GROUP=$(id -gn "$RUN_USER")

echo "📁 Papka:          $DIR"
echo "👤 Foydalanuvchi:  $RUN_USER ($RUN_GROUP)"
echo "⚙️  Xizmat:         $SERVICE"
if [ -t 0 ]; then
    printf "Davom etamizmi? [Y/n] "
    read -r answer || answer=""
    case "$answer" in
        n|N|no|NO|yo*|Yo*) echo "Bekor qilindi."; exit 1 ;;
    esac
fi

# ---------- qo'lda (yoki cron orqali) ishlab turgan bot ----------
mkdir -p "$DIR/data"
if command -v flock >/dev/null 2>&1 && [ -f "$DIR/data/bot.lock" ] && ! systemctl is-active --quiet "$SERVICE"; then
    if ! flock -n "$DIR/data/bot.lock" true 2>/dev/null; then
        echo "⚠️  Bot hozir qo'lda ishlab turibdi (PID $(cat "$DIR/data/bot.lock" 2>/dev/null || echo '?'))."
        echo "   Avval uni to'xtating (o'sha terminalda Ctrl+C; cron qo'shgan bo'lsangiz — crontab -e dan run.sh qatorini o'chiring),"
        echo "   keyin shu buyruqni qayta ishga tushiring."
        exit 1
    fi
fi

# ---------- huquqlar ----------
chown -R "$RUN_USER:$RUN_GROUP" "$DIR"
chmod 600 "$DIR/.env"
chmod 755 "$DIR/run.sh" 2>/dev/null || true

# ---------- systemd xizmati ----------
cat > "$UNIT" <<EOF
[Unit]
Description=cripto.smm-api.uz Telegram bot ($DIR)
After=network-online.target mysql.service mariadb.service mysqld.service
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$DIR
ExecStart="$PY" main.py
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5
# to'xtatishda joriy TON transferi tugashini kutadi
TimeoutStopSec=90
NoNewPrivileges=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"

echo "⏳ Ishga tushirilmoqda..."
sleep 10
echo
if systemctl is-active --quiet "$SERVICE"; then
    echo "✅ Xizmat ishlayapti: $SERVICE"
else
    echo "❌ Xizmat ishlamayapti — quyidagi logni ko'ring:"
fi
echo "---------------------------------------------------------------"
journalctl -u "$SERVICE" -n 15 --no-pager -o cat 2>/dev/null || true
echo "---------------------------------------------------------------"
cat <<EOF
Foydali buyruqlar:
  journalctl -u $SERVICE -f        # jonli log (Ctrl+C — logdan chiqish, bot ishlashda davom etadi)
  systemctl restart $SERVICE       # qayta ishga tushirish (kod yangilangandan keyin)
  systemctl stop $SERVICE          # to'xtatish
  systemctl status $SERVICE        # holat

Endi "python main.py" ni qo'lda ishga tushirish shart emas — bot xizmat sifatida ishlaydi.
EOF
