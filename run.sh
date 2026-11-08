#!/bin/sh
# =====================================================================
#  Botni ishga tushirish / qayta tiklash (cron uchun).
#
#  cPanel → Cron Jobs → har daqiqada (* * * * *):
#    /bin/sh /home/USER/cripto.smm-api.uz/run.sh
#
#  Bot ishlab turgan bo'lsa — hech narsa qilmaydi (data/bot.lock qulfi).
#  Bot to'xtab qolgan bo'lsa — 1 daqiqa ichida qayta ishga tushadi.
#
#  Python yo'li boshqacha bo'lsa (masalan cPanel "Setup Python App" virtualenv):
#    PYTHON=/home/USER/virtualenv/cripto.smm-api.uz/3.12/bin/python /bin/sh /home/USER/cripto.smm-api.uz/run.sh
# =====================================================================
cd "$(dirname "$0")" || exit 1
mkdir -p data

if [ -n "$PYTHON" ]; then
    PY="$PYTHON"
elif [ -x venv/bin/python ]; then
    PY="venv/bin/python"
else
    PY="python3"
fi

exec "$PY" main.py >> data/cron.log 2>&1
