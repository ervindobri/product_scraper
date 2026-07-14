#!/bin/sh
set -e

python manage.py migrate --noinput

# seed/refresh Store rows from the scraper registry (idempotent) — search
# silently returns nothing for stores missing from the DB
python manage.py sync_stores

# bootstrap an admin account on hosts without shell access (TrueNAS):
# reads DJANGO_SUPERUSER_USERNAME / _EMAIL / _PASSWORD from the env file.
# createsuperuser exits non-zero if the user already exists — that's fine.
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py createsuperuser --noinput || true
fi

# single worker: the per-query refresh locks in products/views.py are
# per-process, and sqlite prefers one writer; threads handle concurrency
exec gunicorn mysite.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 1 \
    --threads 8 \
    --timeout 180 \
    --access-logfile -
