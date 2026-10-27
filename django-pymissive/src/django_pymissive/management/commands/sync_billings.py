"""
Sync billings for missives created since a given date.

Deletes existing billings and recreates them from the provider.

Usage:
  ./manage.py sync_billings --date 2026-03-01
  ./manage.py sync_billings -d 2026-01-15
"""

from datetime import datetime

from django.core.management.base import BaseCommand

from ...models.missive import Missive


class Command(BaseCommand):
    help = (
        "Sync billings for missives created since a given date: "
        "delete existing billings and recreate them from the provider."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "-d",
            "--date",
            required=True,
            help="Minimum creation date (YYYY-MM-DD). Missives created on or after this date are processed.",
        )

    def handle(self, *args, **options):
        date_str = options["date"]
        try:
            since = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            self.stderr.write(self.style.ERROR(f"Invalid date format: {date_str}. Use YYYY-MM-DD."))
            return

        missives = (
            Missive.objects.filter(created_at__date__gte=since)
            .filter(external_id__isnull=False)
            .exclude(external_id="")
            .order_by("created_at")
        )
        total = missives.count()
        synced = 0
        skipped = 0
        errors = 0

        for missive in missives:
            if not missive.can_billings():
                skipped += 1
                if options.get("verbosity", 1) >= 2:
                    self.stdout.write(f"Skipped {missive.id} (no get_billings or no external_id)")
                continue

            try:
                missive.to_missivebilling.all().delete()
                missive.get_billings()
                synced += 1
                if options.get("verbosity", 1) >= 2:
                    self.stdout.write(self.style.SUCCESS(f"Synced billings for missive {missive.id}"))
            except Exception as e:
                errors += 1
                self.stderr.write(self.style.ERROR(f"Error syncing missive {missive.id}: {e}"))

        self.stdout.write(
            self.style.SUCCESS(f"Done: {synced} synced, {skipped} skipped, {errors} errors (total: {total})")
        )
