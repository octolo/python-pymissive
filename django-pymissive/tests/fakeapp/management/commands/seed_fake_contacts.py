"""Seed ``fakeapp.Contact`` with deterministic fake people (no Faker).

Usage: ``./manage.py seed_fake_contacts [--count N] [--reset] [--seed N]``
"""

from __future__ import annotations

import random
import unicodedata
from typing import Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tests.fakeapp.models import Contact


FIRST_NAMES: list[str] = [
    "Aurélien", "Camille", "Jules", "Léa", "Manon", "Hugo", "Sofia", "Noah",
    "Yasmina", "Idris", "Émilie", "Mathilde", "Théo", "Inès", "Raphaël",
    "Charlotte", "Antoine", "Salma", "Élise", "Diego", "Anaïs", "Maël",
    "Olivia", "Younes", "Margaux",
]

LAST_NAMES: list[str] = [
    "Prevault", "Martin", "Dubois", "Lefèvre", "Bernard", "Moreau", "Garcia",
    "Roux", "Petit", "Lambert", "Rousseau", "Faure", "Mercier", "Blanc",
    "Giraud", "Da Silva", "Nguyen", "Benali", "Ferrari", "Khoury",
    "Schneider", "Müller", "O'Connor", "Lefebvre", "Picard",
]


def _slug(value: str) -> str:
    """ASCII-fold and lowercase ``value`` for inclusion in an email local-part."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(ch.lower() if ch.isalnum() else "" for ch in ascii_only)


def _iter_unique_contacts(rng: random.Random, count: int) -> Iterable[dict]:
    """``count`` distinct (first, last) pairs with unique emails."""
    pairs = [(f, l) for f in FIRST_NAMES for l in LAST_NAMES]
    rng.shuffle(pairs)
    seen_emails: set[str] = set()
    for first, last in pairs[: max(count, 0)]:
        local = f"{_slug(first)}.{_slug(last)}"
        email = f"{local}@example.com"
        suffix = 1
        while email in seen_emails:
            suffix += 1
            email = f"{local}{suffix}@example.com"
        seen_emails.add(email)
        yield {"first_name": first, "last_name": last, "email": email}


class Command(BaseCommand):
    help = (
        "Seed fakeapp.Contact with deterministic fake people for development "
        "(no external dependency)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=10,
            help="Number of contacts to create (default: 10).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=0,
            help="RNG seed for reproducible draws (default: 0).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing Contact rows before seeding.",
        )

    def handle(self, *args, count: int, seed: int, reset: bool, **options):
        if count <= 0:
            raise CommandError("--count must be a positive integer")
        max_combos = len(FIRST_NAMES) * len(LAST_NAMES)
        if count > max_combos:
            raise CommandError(
                f"--count={count} exceeds the {max_combos} unique first/last "
                "combinations available; add more names to FIRST_NAMES / LAST_NAMES."
            )

        rng = random.Random(seed)
        rows = list(_iter_unique_contacts(rng, count))

        with transaction.atomic():
            if reset:
                deleted, _ = Contact.objects.all().delete()
                self.stdout.write(f"Deleted {deleted} existing Contact row(s).")

            existing_emails = set(
                Contact.objects.filter(email__in=[r["email"] for r in rows])
                .values_list("email", flat=True)
            )
            to_create = [Contact(**r) for r in rows if r["email"] not in existing_emails]
            Contact.objects.bulk_create(to_create)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {len(to_create)} new Contact row(s) "
                f"(requested={count}, skipped_existing={len(rows) - len(to_create)})."
            )
        )
