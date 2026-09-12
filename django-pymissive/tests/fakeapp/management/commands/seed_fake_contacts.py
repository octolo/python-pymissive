"""Seed fakeapp categories/contacts and attach them to campaigns/missives.

Usage::

    ./manage.py seed_fake_contacts --ncategory 5 --ncontact 20
    ./manage.py seed_fake_contacts --ncategory 5 --ncontact 20 --randcampaign --randmissive
    ./manage.py seed_fake_contacts --randcampaign 2 --randmissive 2

Counts are targets: existing rows are kept, only the missing ones are created.
``--randcampaign`` / ``--randmissive`` take an optional N (default 1) and attach
N random contacts **and** N random categories on each campaign / missive.
"""

from __future__ import annotations

import random
import unicodedata
from typing import Iterable

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tests.fakeapp.models import Category, Contact


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

CATEGORIES: list[str] = [
    "Pro", "Particulier", "VIP", "Premium", "Standard", "Gold",
    "Silver", "PME", "Association", "Collectivite",
]


def _slug(value: str) -> str:
    """ASCII-fold and lowercase ``value`` for inclusion in an email local-part."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(ch.lower() if ch.isalnum() else "" for ch in ascii_only)


def _category_name(index: int) -> str:
    if 0 <= index < len(CATEGORIES):
        return CATEGORIES[index]
    return f"Categorie {index + 1}"


def _iter_new_contacts(
    rng: random.Random, *, need: int, existing_emails: set[str]
) -> Iterable[dict]:
    """Yield ``need`` contact dicts whose emails are not in ``existing_emails``."""
    remaining = need
    pairs = [(f, l) for f in FIRST_NAMES for l in LAST_NAMES]
    rng.shuffle(pairs)
    for first, last in pairs:
        if remaining <= 0:
            return
        local = f"{_slug(first)}.{_slug(last)}"
        email = f"{local}@example.com"
        suffix = 1
        while email in existing_emails:
            suffix += 1
            email = f"{local}{suffix}@example.com"
        existing_emails.add(email)
        remaining -= 1
        yield {"first_name": first, "last_name": last, "email": email}
    extra = 1
    while remaining > 0:
        email = f"contact{extra}@example.com"
        extra += 1
        if email in existing_emails:
            continue
        existing_emails.add(email)
        remaining -= 1
        yield {
            "first_name": "Contact",
            "last_name": str(extra - 1),
            "email": email,
        }


def _ensure_categories(ncategory: int) -> tuple[int, int]:
    """Create categories until ``Category`` count reaches ``ncategory``."""
    existing = Category.objects.count()
    need = ncategory - existing
    if need <= 0:
        return 0, existing
    names = set(Category.objects.values_list("name", flat=True))
    to_create: list[Category] = []
    index = 0
    while len(to_create) < need:
        name = _category_name(index)
        index += 1
        if name in names:
            continue
        names.add(name)
        to_create.append(Category(name=name))
    Category.objects.bulk_create(to_create)
    return len(to_create), existing + len(to_create)


def _ensure_contacts(ncontact: int, rng: random.Random) -> tuple[int, int]:
    """Create contacts until ``Contact`` count reaches ``ncontact``."""
    existing = Contact.objects.count()
    need = ncontact - existing
    if need <= 0:
        return 0, existing
    emails = set(Contact.objects.values_list("email", flat=True))
    categories = list(Category.objects.all())
    rows = []
    for row in _iter_new_contacts(rng, need=need, existing_emails=emails):
        if categories:
            row["category"] = rng.choice(categories)
        rows.append(Contact(**row))
    Contact.objects.bulk_create(rows)
    return len(rows), existing + len(rows)


def _existing_object_ids(qs, ct) -> set:
    return set(qs.filter(content_type=ct).values_list("object_id", flat=True))


def _attach_type(qs, *, objects, ct, count, rng, create) -> int:
    """Attach up to ``count`` distinct objects of this content type."""
    if not objects or count <= 0:
        return 0
    existing = _existing_object_ids(qs, ct)
    need = count - len(existing)
    if need <= 0:
        return 0
    available = [obj for obj in objects if obj.pk not in existing]
    rng.shuffle(available)
    added = 0
    for obj in available[:need]:
        create(obj)
        added += 1
    return added


def _attach_on(qs, *, contacts, categories, contact_ct, category_ct, count, rng, create):
    added = _attach_type(
        qs, objects=contacts, ct=contact_ct, count=count, rng=rng, create=create
    )
    added += _attach_type(
        qs, objects=categories, ct=category_ct, count=count, rng=rng, create=create
    )
    return added


def _attach_random_related(*, campaign_count: int, missive_count: int, rng: random.Random):
    from django_pymissive.models.campaign import MissiveCampaign
    from django_pymissive.models.missive import Missive
    from django_pymissive.models.related_object import (
        CampaignRelatedObject,
        MissiveRelatedObject,
    )

    contacts = list(Contact.objects.all())
    categories = list(Category.objects.all())
    contact_ct = ContentType.objects.get_for_model(Contact)
    category_ct = ContentType.objects.get_for_model(Category)
    attached_campaigns = 0
    skipped_campaigns = 0
    attached_missives = 0
    skipped_missives = 0

    if campaign_count:
        for campaign in MissiveCampaign.objects.all():
            added = _attach_on(
                campaign.to_campaignrelatedobject,
                contacts=contacts,
                categories=categories,
                contact_ct=contact_ct,
                category_ct=category_ct,
                count=campaign_count,
                rng=rng,
                create=lambda obj, campaign=campaign: CampaignRelatedObject.objects.create(
                    campaign=campaign, content_object=obj
                ),
            )
            if added:
                attached_campaigns += 1
            else:
                skipped_campaigns += 1

    if missive_count:
        for missive in Missive.objects.all():
            added = _attach_on(
                missive.to_missiverelatedobject,
                contacts=contacts,
                categories=categories,
                contact_ct=contact_ct,
                category_ct=category_ct,
                count=missive_count,
                rng=rng,
                create=lambda obj, missive=missive: MissiveRelatedObject.objects.create(
                    missive=missive, content_object=obj
                ),
            )
            if added:
                attached_missives += 1
            else:
                skipped_missives += 1

    return {
        "attached_campaigns": attached_campaigns,
        "skipped_campaigns": skipped_campaigns,
        "attached_missives": attached_missives,
        "skipped_missives": skipped_missives,
    }


class Command(BaseCommand):
    help = (
        "Seed fakeapp Category/Contact up to given counts, then optionally "
        "attach N random contacts and N random categories to campaigns and missives."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--ncategory",
            type=int,
            default=0,
            help="Target number of categories (create only the missing ones).",
        )
        parser.add_argument(
            "--ncontact",
            "--count",
            dest="ncontact",
            type=int,
            default=0,
            help="Target number of contacts (create only the missing ones).",
        )
        parser.add_argument(
            "--randcampaign",
            nargs="?",
            const=1,
            type=int,
            default=0,
            metavar="N",
            help=(
                "Attach N random contacts and N categories per campaign "
                "(N defaults to 1)."
            ),
        )
        parser.add_argument(
            "--randmissive",
            nargs="?",
            const=1,
            type=int,
            default=0,
            metavar="N",
            help=(
                "Attach N random contacts and N categories per missive "
                "(N defaults to 1)."
            ),
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
            help="Delete existing Contact/Category rows (and their related links) first.",
        )

    def handle(
        self,
        *args,
        ncategory: int,
        ncontact: int,
        randcampaign: int,
        randmissive: int,
        seed: int,
        reset: bool,
        **options,
    ):
        randcampaign = int(randcampaign or 0)
        randmissive = int(randmissive or 0)
        if ncategory < 0 or ncontact < 0:
            raise CommandError("--ncategory and --ncontact must be >= 0")
        if randcampaign < 0 or randmissive < 0:
            raise CommandError("--randcampaign and --randmissive must be >= 0")
        if ncategory == 0 and ncontact == 0 and not randcampaign and not randmissive:
            raise CommandError(
                "Specify --ncategory, --ncontact, --randcampaign and/or --randmissive."
            )

        rng = random.Random(seed)

        with transaction.atomic():
            if reset:
                self._reset()

            created_categories, total_categories = _ensure_categories(ncategory)
            created_contacts, total_contacts = _ensure_contacts(ncontact, rng)

            attach = {"attached_campaigns": 0, "skipped_campaigns": 0,
                      "attached_missives": 0, "skipped_missives": 0}
            if randcampaign or randmissive:
                attach = _attach_random_related(
                    campaign_count=randcampaign,
                    missive_count=randmissive,
                    rng=rng,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Categories: created={created_categories}, total={total_categories}. "
                f"Contacts: created={created_contacts}, total={total_contacts}."
            )
        )
        if randcampaign:
            self.stdout.write(
                f"Campaigns: attached={attach['attached_campaigns']}, "
                f"skipped={attach['skipped_campaigns']}."
            )
        if randmissive:
            self.stdout.write(
                f"Missives: attached={attach['attached_missives']}, "
                f"skipped={attach['skipped_missives']}."
            )

    def _reset(self) -> None:
        from django_pymissive.models.related_object import (
            CampaignRelatedObject,
            MissiveRelatedObject,
        )

        contact_ct = ContentType.objects.get_for_model(Contact)
        category_ct = ContentType.objects.get_for_model(Category)
        types = [contact_ct, category_ct]
        related_m, _ = MissiveRelatedObject.objects.filter(content_type__in=types).delete()
        related_c, _ = CampaignRelatedObject.objects.filter(content_type__in=types).delete()
        deleted_contacts, _ = Contact.objects.all().delete()
        deleted_categories, _ = Category.objects.all().delete()
        self.stdout.write(
            f"Reset: contacts={deleted_contacts}, categories={deleted_categories}, "
            f"missive_related={related_m}, campaign_related={related_c}."
        )
