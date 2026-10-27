"""Fake data generators shared by ``seed_fake_contacts`` and the fakeapp admin."""

from __future__ import annotations

import random
import unicodedata
from typing import Iterable

from django.db import transaction

from .models import (
    CampaignContact,
    Category,
    Contact,
    ContactAddress,
    ContactEmail,
    ContactPhone,
)

FIRST_NAMES: list[str] = [
    "Aurélien",
    "Camille",
    "Jules",
    "Léa",
    "Manon",
    "Hugo",
    "Sofia",
    "Noah",
    "Yasmina",
    "Idris",
    "Émilie",
    "Mathilde",
    "Théo",
    "Inès",
    "Raphaël",
    "Charlotte",
    "Antoine",
    "Salma",
    "Élise",
    "Diego",
    "Anaïs",
    "Maël",
    "Olivia",
    "Younes",
    "Margaux",
]

LAST_NAMES: list[str] = [
    "Prevault",
    "Martin",
    "Dubois",
    "Lefèvre",
    "Bernard",
    "Moreau",
    "Garcia",
    "Roux",
    "Petit",
    "Lambert",
    "Rousseau",
    "Faure",
    "Mercier",
    "Blanc",
    "Giraud",
    "Da Silva",
    "Nguyen",
    "Benali",
    "Ferrari",
    "Khoury",
    "Schneider",
    "Müller",
    "O'Connor",
    "Lefebvre",
    "Picard",
]

CATEGORIES: list[str] = [
    "Pro",
    "Particulier",
    "VIP",
    "Premium",
    "Standard",
    "Gold",
    "Silver",
    "PME",
    "Association",
    "Collectivite",
]

STREETS: list[str] = [
    "rue de la Paix",
    "avenue Victor Hugo",
    "boulevard Voltaire",
    "rue Nationale",
    "place de la République",
    "rue des Lilas",
    "chemin des Vignes",
    "quai Saint-Michel",
]

CITIES: list[tuple[str, str]] = [
    ("75002", "Paris"),
    ("69001", "Lyon"),
    ("13001", "Marseille"),
    ("31000", "Toulouse"),
    ("33000", "Bordeaux"),
    ("59000", "Lille"),
    ("44000", "Nantes"),
    ("67000", "Strasbourg"),
]

EMAIL_DOMAINS: list[str] = ["example.com", "work.example.com", "mail.example.org"]


def slug(value: str) -> str:
    """ASCII-fold and lowercase ``value`` for inclusion in an email local-part."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(ch.lower() if ch.isalnum() else "" for ch in ascii_only)


def ensure_categories(ncategory: int) -> tuple[int, int]:
    """Create categories until ``Category`` count reaches ``ncategory``."""
    existing = Category.objects.count()
    need = ncategory - existing
    if need <= 0:
        return 0, existing
    names = set(Category.objects.values_list("name", flat=True))
    to_create: list[Category] = []
    index = 0
    while len(to_create) < need:
        name = CATEGORIES[index] if index < len(CATEGORIES) else f"Categorie {index + 1}"
        index += 1
        if name in names:
            continue
        names.add(name)
        to_create.append(Category(name=name))
    Category.objects.bulk_create(to_create)
    return len(to_create), existing + len(to_create)


def _iter_new_contacts(rng: random.Random, *, need: int, existing_emails: set[str]) -> Iterable[dict]:
    """Yield ``need`` contact dicts whose emails are not in ``existing_emails``."""
    remaining = need
    pairs = [(first, last) for first in FIRST_NAMES for last in LAST_NAMES]
    rng.shuffle(pairs)
    for first, last in pairs:
        if remaining <= 0:
            return
        local = f"{slug(first)}.{slug(last)}"
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
        yield {"first_name": "Contact", "last_name": str(extra - 1), "email": email}


def ensure_contacts(ncontact: int, rng: random.Random) -> tuple[int, int]:
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


def create_campaign_contact(first_name, last_name, *, emails=(), phones=(), addresses=()):
    """Create one contact. The first value of each list is the singular property."""
    contact = CampaignContact.objects.create(first_name=first_name, last_name=last_name)
    ContactEmail.objects.bulk_create(ContactEmail(contact=contact, email=e) for e in emails)
    ContactPhone.objects.bulk_create(ContactPhone(contact=contact, phone=p) for p in phones)
    ContactAddress.objects.bulk_create(ContactAddress(contact=contact, address=address) for address in addresses)
    return contact


@transaction.atomic
def generate_campaign_contacts(count, *, emails=2, phones=2, addresses=2, seed=0):
    """Create *count* contacts with *emails*, *phones* and *addresses* each."""
    rng = random.Random(seed)
    start = CampaignContact.objects.count()
    contacts = []
    for index in range(start, start + count):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        local = f"{slug(first)}.{slug(last)}.{index}"
        contacts.append(
            create_campaign_contact(
                first,
                last,
                emails=[f"{local}@{EMAIL_DOMAINS[n % len(EMAIL_DOMAINS)]}" for n in range(emails)],
                phones=[f"+336{rng.randint(10_000_000, 99_999_999)}" for _ in range(phones)],
                addresses=[_random_address(rng) for _ in range(addresses)],
            )
        )
    return contacts


def ensure_campaign_contacts(total, **kwargs) -> tuple[int, int]:
    """Create campaign contacts until their count reaches *total*."""
    missing = total - CampaignContact.objects.count()
    created = len(generate_campaign_contacts(missing, **kwargs)) if missing > 0 else 0
    return created, CampaignContact.objects.count()


def _random_address(rng):
    postal_code, city = rng.choice(CITIES)
    return {
        "address_line1": f"{rng.randint(1, 120)} {rng.choice(STREETS)}",
        "postal_code": postal_code,
        "city": city,
        "country": "France",
    }
