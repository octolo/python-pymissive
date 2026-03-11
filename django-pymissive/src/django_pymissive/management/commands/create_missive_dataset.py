"""
Create a dataset of missives for testing/development.

Loads fixtures: fixture_email.json, fixture_phone.json, fixture_postal.json
- Email: 2 recipients, 2 CC, 2 BCC, 1 sender, 1 reply-to
- Phone (SMS): 2 recipients
- Postal: 2 recipients

Usage:
  ./manage.py create_missive_dataset
  ./manage.py create_missive_dataset -f /path/to/custom_fixture.json
  ./manage.py create_missive_dataset -f fixture1.json -f fixture2.json

Or load fixtures directly:
  ./manage.py loaddata fixture_email fixture_phone fixture_postal
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

DEFAULT_FIXTURES = ["fixture_email", "fixture_phone", "fixture_postal"]


class Command(BaseCommand):
    help = (
        "Load missive dataset fixtures "
        "(email with 2 CC/2 BCC/2 recipients, phone with 2 recipients, postal with 2 recipients)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "-f",
            "--fixture",
            action="append",
            dest="fixtures",
            default=None,
            help="Path to fixture file (can be repeated for multiple files)",
        )

    def handle(self, *args, **options):
        fixtures = options.get("fixtures") or DEFAULT_FIXTURES
        call_command(
            "loaddata",
            *fixtures,
            verbosity=options.get("verbosity", 1),
        )
        self.stdout.write(
            self.style.SUCCESS(f"Dataset loaded: {len(fixtures)} fixture(s)")
        )
