#!/bin/sh
set -e

if [ "${DJANGO_DB_ENGINE:-postgresql}" = "sqlite" ]; then
    echo "Using SQLite database."
else
    echo "Waiting for PostgreSQL..."
    python <<'PY'
import os
import time
import psycopg

host = os.environ.get("POSTGRES_HOST", "db")
port = os.environ.get("POSTGRES_PORT", "5432")
dbname = os.environ.get("POSTGRES_DB", "bewohnerformular")
user = os.environ.get("POSTGRES_USER", "bewohnerformular")
password = os.environ.get("POSTGRES_PASSWORD", "")

last_error = None
for i in range(30):
    try:
        conn = psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password)
        conn.close()
        print("PostgreSQL is ready.")
        break
    except Exception as exc:
        last_error = exc
        print(f"Database not ready yet... {i + 1}/30")
        time.sleep(2)
else:
    raise RuntimeError(f"PostgreSQL is not reachable: {last_error}")
PY
fi

python manage.py check
python manage.py migrate --noinput
python manage.py collectstatic --noinput

if [ "${DJANGO_COMPILEMESSAGES:-0}" = "1" ]; then
    python manage.py compilemessages -l de -l en -l fa -l ar -l tr -l fr || true
fi

if [ "${DJANGO_SEED_DEMO_FORMS:-0}" = "1" ]; then
    python manage.py seed_government_demo_forms || true
fi

WEB_CONCURRENCY="${WEB_CONCURRENCY:-3}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-60}"
GUNICORN_GRACEFUL_TIMEOUT="${GUNICORN_GRACEFUL_TIMEOUT:-30}"
GUNICORN_KEEP_ALIVE="${GUNICORN_KEEP_ALIVE:-5}"

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "$WEB_CONCURRENCY" \
    --timeout "$GUNICORN_TIMEOUT" \
    --graceful-timeout "$GUNICORN_GRACEFUL_TIMEOUT" \
    --keep-alive "$GUNICORN_KEEP_ALIVE" \
    --max-requests 1000 \
    --max-requests-jitter 100
