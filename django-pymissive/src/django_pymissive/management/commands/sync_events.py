"""
Sync events for missives created since a given date.

Deletes events that are not client_initiated (i.e. provider webhook events),
re-fetches events from the provider when available, and updates status.

Usage:
  ./manage.py sync_events --date 2026-03-01
  ./manage.py sync_events -d 2026-01-15
  ./manage.py sync_events -d 2026-01-15 --noevent
"""

from datetime import datetime

from django.core.management.base import BaseCommand

from ...models.missive import Missive


class Command(BaseCommand):
    help = (
        "Sync events for missives created since a given date: "
        "delete non-client-initiated events, re-fetch from provider, update status."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "-d",
            "--date",
            required=True,
            help="Minimum creation date (YYYY-MM-DD). Missives created on or after this date are processed.",
        )
        parser.add_argument(
            "-n",
            "--noevent",
            action="store_true",
            help="Only process missives that have 0 or 1 event.",
        )

    def handle(self, *args, **options):
        date_str = options["date"]
        try:
            since = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            self.stderr.write(
                self.style.ERROR(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")
            )
            return

        missives = (
            Missive.objects.filter(created_at__date__gte=since, external_id__isnull=False)
            .exclude(external_id="")
            .order_by("created_at")
        )
        if options.get("noevent"):
            # count_event is a distinct annotation; a plain Count stacked on
            # other reverse-FK joins would skip missives that do have 0 or 1 event.
            missives = missives.with_counts().filter(count_event__lte=1)
        total = missives.count()
        synced = 0
        errors = 0

        for missive in missives:
            try:
                deleted, _ = missive.to_missiveevent.filter(
                    client_initiated=False
                ).delete()

                if missive.has_service("retrieve"):
                    missive.retrieve_missive()

                missive.set_status()
                for recipient in missive.to_missiverecipient.all():
                    recipient.set_status()

                synced += 1
                if options.get("verbosity", 1) >= 2:
                    self.stdout.write(
                        f"Synced events for missive {missive.id} (deleted {deleted} events)"
                    )
            except Exception as e:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(f"Error syncing missive {missive.id}: {e}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {synced} synced, {errors} errors (total: {total})"
            )
        )
