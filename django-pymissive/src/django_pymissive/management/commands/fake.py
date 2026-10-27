"""
Post a random webhook for every missive the fake provider already sent.

Same function as the "Fake webhooks" admin view. The view enqueues it;
this command runs it here and prints the result.

Usage:
  ./manage.py fake
  ./manage.py fake --limit 20
  ./manage.py fake --seed 1
"""

from django.core.management.base import BaseCommand, CommandError

from ...fake_webhooks import FakeProviderDisabled, run_fake_webhooks


class Command(BaseCommand):
    help = "Post a random webhook for each sent fake missive (delivered, failed, still in progress, or cancelled)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of missives, oldest first.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Seed the random draw so the same events are posted again.",
        )

    def handle(self, *args, **options):
        try:
            result = run_fake_webhooks(limit=options["limit"], seed=options["seed"])
        except FakeProviderDisabled as exc:
            raise CommandError(str(exc)) from exc
        if options.get("verbosity", 1) >= 2:
            for row in result["results"]:
                events = ", ".join(row["events"])
                self.stdout.write(f"{row['missive_id']} {events} -> {row['status_code']} {row['url']}")
        self.stdout.write(self.style.SUCCESS(f"Done: {result['posted']} posted, {result['failed']} failed."))
