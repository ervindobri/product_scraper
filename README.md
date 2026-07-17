# product_scraper

Price-comparison tool for electronics across Hungarian and EU webshops. A single search
query fans out to ~40 store scrapers in parallel (Alza, eMAG, MediaMarkt, Amazon,
Alternate, Coolblue, classifieds like Jófogás/Hardverapró/Marktplaats, and more), results
are relevance-scored and normalized to HUF, and price changes are tracked over time.

## Architecture

The repo has three main components plus deployment glue:

```
┌─────────────────┐         ┌──────────────────┐        ┌─────────────────┐
│ frontend/       │  REST   │ server/          │ import │ scraper/        │
│ Flutter web app ├────────►│ Django + DRF API ├───────►│ scrapers.py     │
│ (fluent_ui,     │ /api/…  │ SQLite, price    │        │ ~40 site        │
│  Riverpod, Dio) │         │ history, caching │        │ scrapers        │
└─────────────────┘         └──────────────────┘        └─────────────────┘
```

### `scraper/` — the scraping engine

- **`scrapers.py`** is the heart of the project: one `scrape_<site>(query, session)`
  function per store, each returning `[{site, name, price, url}, ...]`. The `SCRAPERS`
  registry at the bottom maps `(site_name, region_code, fn)`; everything else (GUI,
  server, region filters) is driven off that list.
- Techniques vary per site and are documented in the module docstring: plain
  `requests` + BeautifulSoup, `cloudscraper` for Cloudflare-protected shops, JSON-LD
  / `__NEXT_DATA__` / `data-initialdata` blob parsing, and direct JSON search APIs
  (Doofinder, Webhallen). Sites that are un-scrapable (Akamai/Turnstile challenges,
  pure client-side SPAs) raise an informative `RuntimeError` instead of silently
  returning nothing.
- **Shared pipeline**: `run_search()` runs all scrapers concurrently in a thread pool
  with a global timeout, and `enrich_result()` post-processes every hit — EUR prices
  are converted to HUF (FX rates from frankfurter.app, cached with a TTL), a numeric
  `amount_huf` is derived for cross-currency sorting, and a 0–100 relevance `score`
  is computed against the query (diacritic-insensitive word matching).
- **`main.py`** is a standalone Tkinter desktop GUI that uses the same pipeline:
  live per-store status badges, region filtering, sortable results, and "new since
  last search" highlighting. It works without the server.

### `server/` — Django REST API

- Django + Django REST Framework app (`server/products/`) exposing `Store`,
  `SearchQuery`, and `Product` viewsets under `/api/`.
- The main endpoint is `GET /api/queries/search/?query=...`: it serves cached
  products from the DB, and if the query has never been scraped or is older than
  one hour it re-runs the scrapers first (rate-throttled, one refresh per query at
  a time via a per-query lock).
- **`services.refresh_search_query()`** bridges Django to the scraper package: it
  upserts products by `(query, url)`, appends a `PriceHistory` row on every price
  change, bumps `last_seen` on products still listed (so delisted items age out),
  and tracks per-store scrape health (`last_success` / `failure_count`). If every
  store fails, nothing is written and the cached results keep serving.
- Data model: `Store` → `Product` ← `SearchQuery`, plus `PriceHistory` per product.
  SQLite database; `manage.py sync_stores` seeds the `Store` table from the
  `SCRAPERS` registry.

### `frontend/` — Flutter web client

Flutter app (`fluent_ui` widgets, Riverpod for state, Dio/Retrofit for networking)
that talks to the Django API: search input, product results table, and recent-queries
dialog. Built for web and served as static files by nginx.

## Deployment

Self-hosted on TrueNAS, reachable only over Tailscale at
`https://product-scraper.<tailnet>.ts.net`.

- **`Dockerfile`** — API image: Python 3.13 slim, copies `scraper/` + `server/`,
  runs gunicorn with whitenoise for static files, SQLite at `/data/db.sqlite3`.
- **`Dockerfile.web`** — frontend image: nginx serving the prebuilt Flutter web
  bundle (CI builds it first).
- **`.github/workflows/`** — CI publishes both images to GHCR, tagged with the
  commit SHA.
- **`deploy/truenas-app.yaml`** — TrueNAS custom-app compose file: a `tailscale`
  sidecar terminates TLS and path-routes on one origin (`/` → nginx web, `/api`,
  `/admin`, `/static` → Django), so no CORS is needed. The API and web containers
  share the sidecar's network namespace and are never exposed on the LAN. Secrets
  (`TS_AUTHKEY`, `DJANGO_SECRET_KEY`) live in an env file on the NAS.

## Running locally

```bash
# Desktop GUI (no server needed)
pip install -r requirements.txt
python scraper/main.py

# API server
cd server
python manage.py migrate
python manage.py sync_stores      # seed stores from the SCRAPERS registry
python manage.py runserver        # http://127.0.0.1:8000/api/

# Flutter frontend
cd frontend
flutter run -d chrome
```

## Adding a new store

Add a `scrape_<site>()` function to [scraper/scrapers.py](scraper/scrapers.py) and
register it in the `SCRAPERS` list — nothing else needs to change (the GUI, server,
and region filters all derive from the registry). See the existing scrapers for the
result-dict contract and per-technique examples, or use the `/add-scraper` Claude
Code skill in `.claude/skills/`.
