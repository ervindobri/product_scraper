"""
Sync the default scraper list into the Store table.

Usage:
    python manage.py sync_stores

Idempotent: creates missing stores, updates url/country on existing ones
(matched by name), and leaves everything else untouched. The scraper
registry (scraper/scrapers.py SCRAPERS) is the single source of truth.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from products.models import Store
from products.services import REPO_DIR  # noqa: F401  (puts <repo> on sys.path)

# scraper names are the site domains, apart from these
URL_OVERRIDES = {
    "Jófogás.hu": "jofogas.hu",
    "Hardverapró": "hardverapro.hu",
}

REGION_COUNTRIES = {
    "hu": "Hungary",
    "de": "Germany",
    "fr": "France",
    "es": "Spain",
    "be": "Belgium",
    "it": "Italy",
    "nl": "Netherlands",
    "pl": "Poland",
    "se": "Sweden",
}


class Command(BaseCommand):
    help = "Create/update Store rows from the scraper registry (SCRAPERS)."

    def handle(self, *args, **options):
        try:
            from scraper.scrapers import SCRAPERS
        except ImportError as exc:
            raise CommandError(f"Could not import scraper registry from {REPO_DIR}: {exc}")

        created_count = updated_count = 0
        for name, region, _func in SCRAPERS:
            url = URL_OVERRIDES.get(name, name.lower())
            country = REGION_COUNTRIES.get(region, region)

            store, created = Store.objects.get_or_create(
                name=name,
                defaults={
                    "url": url,
                    "country": country,
                    "pub_date": timezone.now(),
                },
            )
            if created:
                created_count += 1
                self.stdout.write(f"  + {name} ({url}, {country})")
            elif store.url != url or store.country != country:
                store.url = url
                store.country = country
                store.save(update_fields=["url", "country"])
                updated_count += 1
                self.stdout.write(f"  ~ {name} ({url}, {country})")

        self.stdout.write(self.style.SUCCESS(
            f"Done: {created_count} created, {updated_count} updated, "
            f"{Store.objects.count()} stores total."
        ))
