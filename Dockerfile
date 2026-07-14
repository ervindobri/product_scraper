# Django API + scraper image for the product_scraper server.
# Build from the repo root: docker build -t product-scraper .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /repo

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# services.py imports scraper.scrapers via the repo root, so the image
# mirrors the repo layout: /repo/scraper + /repo/server
COPY scraper/ scraper/
COPY server/ server/

WORKDIR /repo/server

# admin + browsable-API assets, served by whitenoise
RUN python manage.py collectstatic --noinput

# sqlite + static live here; mount a dataset over it in production
RUN mkdir -p /data
ENV DJANGO_DB_PATH=/data/db.sqlite3

EXPOSE 8000

COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
