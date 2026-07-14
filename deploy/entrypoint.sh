#!/bin/sh
set -e

python manage.py migrate --noinput

# single worker: the per-query refresh locks in products/views.py are
# per-process, and sqlite prefers one writer; threads handle concurrency
exec gunicorn mysite.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 1 \
    --threads 8 \
    --timeout 180 \
    --access-logfile -
