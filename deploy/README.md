# Deploying to TrueNAS over Tailscale

The server runs as a two-container stack on TrueNAS (SCALE 24.10+ / Community
Edition): a `tailscale/tailscale` sidecar joins the tailnet as the node
`product-scraper` and terminates HTTPS, and the Django API container shares its
network namespace. The API is reachable **only** from the tailnet at:

    https://product-scraper.<tailnet>.ts.net

No LAN port, no port forwarding. Any device with the Tailscale app (including
your phone, anywhere in the world) can reach it.

## One-time Tailscale setup

1. Admin console > **DNS**: enable **MagicDNS** and **HTTPS Certificates**.
2. Admin console > **Access controls**: add a tag for servers if you don't
   have one, e.g. `"tagOwners": {"tag:server": ["autogroup:admin"]}`.
3. Admin console > **Settings > Keys**: generate an **auth key** with tag
   `tag:server` (tagged nodes never expire). Copy it — it goes into
   `TS_AUTHKEY` below.

## Image

TrueNAS pulls images, it doesn't build them. GitHub Actions
(`.github/workflows/docker-publish.yml`) builds and pushes
`ghcr.io/ervindobri/product-scraper:latest` on every push to `main` that
touches the server/scraper.

> GHCR packages are **private by default**. After the first push, open the
> package on GitHub (Profile > Packages > product-scraper > Package settings)
> and set visibility to **Public**, or add GHCR login credentials on TrueNAS.

Alternative without GitHub Actions — build straight on the NAS:

```sh
ssh admin@truenas
git clone https://github.com/ervindobri/product_scraper.git && cd product_scraper
docker build -t product-scraper:latest .
# then use image: product-scraper:latest in the app YAML
```

## Deploy on TrueNAS

1. Create the storage directories (as datasets or plain folders), e.g.
   `/mnt/<pool>/apps/product-scraper/ts-state` and
   `/mnt/<pool>/apps/product-scraper/data`.
2. Put the secrets on the NAS — copy
   [product-scraper.env.example](product-scraper.env.example) to
   `/mnt/<pool>/apps/product-scraper/product-scraper.env`, fill in
   `TS_AUTHKEY` (the **full** key, ID + secret half) and `DJANGO_SECRET_KEY`
   (`openssl rand -base64 48`), then `chmod 600` it. The compose file loads
   it via `env_file:`, so no secrets ever appear in the YAML or in git.
3. Open [truenas-app.yaml](truenas-app.yaml) and adjust the non-secret
   values if needed: pool name in the paths and your tailnet name (the `xxx`
   in `product-scraper.xxx.ts.net` — shown on the admin console DNS page).
4. TrueNAS UI > **Apps > Discover > ⋮ > Install via YAML**, name it
   `product-scraper`, paste the YAML, save.
5. First start: the sidecar joins the tailnet, the API container runs
   migrations and starts gunicorn. Check
   `https://product-scraper.<tailnet>.ts.net/api/` from any tailnet device.

To create an admin user, set `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` /
`_PASSWORD` in the env file — the entrypoint runs
`createsuperuser --noinput` on startup (a no-op once the account exists).
With shell access you can instead run `python manage.py createsuperuser`
in the `product-scraper-api` container.

## Updating

Push to `main` (or rebuild on the NAS), then in the TrueNAS app UI use
**Upgrade** on the app — that's what pulls the new `:latest`. A plain
restart/redeploy reuses the cached image and will NOT pick up changes.
The SQLite DB and the Tailscale node identity live on the mounted datasets
and survive upgrades.

## Frontend (Flutter web)

The `web` service serves the Flutter web build via nginx on :8080 in the same
shared network namespace. The serve config path-routes: `/` goes to the
frontend, `/api`, `/api-auth`, `/admin` and `/static` go to Django. Everything
is one origin (`https://product-scraper.<tailnet>.ts.net`), so no CORS.

`.github/workflows/web-publish.yml` builds the bundle (Flutter 3.35.6) and
pushes `ghcr.io/ervindobri/product-scraper-web` on pushes to `main` touching
`frontend/`. Like the API image, the GHCR package must be set to **Public**
after the first push.

The app calls the API at the relative `/api/` by default on web
([dio_client.dart](../frontend/lib/core/network/dio_client.dart)); native
desktop/mobile builds default to `http://127.0.0.1:8000/api/` and can be
pointed elsewhere with
`--dart-define=API_BASE_URL=https://product-scraper.<tailnet>.ts.net/api/`.

## Notes / gotchas

- **Persist `/var/lib/tailscale`** (the `ts-state` mount). Without it every
  redeploy registers a new node (`product-scraper-1`, `-2`, …).
- Gunicorn runs **1 worker + 8 threads** on purpose: the per-query scrape
  locks in `products/views.py` are per-process and SQLite wants a single
  writer. Don't scale workers without moving those locks to the DB.
- The Docker healthcheck for the sidecar gates the API start
  (`depends_on: service_healthy`), so the API never runs before the tailnet
  link is up.
- `AllowFunnel` is `false` — flipping it to `true` (plus a `funnel` ACL) would
  publish the API to the whole internet via Tailscale Funnel. Leave it off
  unless that's what you want.
