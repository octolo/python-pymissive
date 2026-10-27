"""
Create a synthetic dataset of missives for testing/development.

Generates batches of DRAFT missives (email, sms, registered_letter by default).
Optionally attaches them to an existing campaign or creates one on the fly.

Usage examples
--------------
  # 300 missives, no campaign:
  ./manage.py create_missive_dataset 300

  # 300 missives, new campaign created automatically:
  ./manage.py create_missive_dataset 300 --campaign

  # 300 missives attached to an existing campaign:
  ./manage.py create_missive_dataset 300 --campaign <uuid>

  # 200 missives, email + sms only, new campaign:
  ./manage.py create_missive_dataset 200 --types email sms --campaign

  # Custom subject for the auto-created campaign:
  ./manage.py create_missive_dataset 100 --campaign --subject "My test campaign"
"""

from math import ceil

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

DEFAULT_TYPES = ["email", "sms", "registered_letter"]

# Fake data pools
_FIRST_NAMES = ["Alice", "Bob", "Carol", "David", "Eve", "Frank", "Grace", "Hugo"]
_LAST_NAMES = ["Martin", "Dupont", "Bernard", "Thomas", "Petit", "Robert", "Richard"]
_DOMAINS = ["example.com", "test.org", "demo.net", "sample.io"]
_STREETS = [
    "1 rue de la Paix",
    "12 avenue des Champs",
    "7 boulevard Haussmann",
    "42 rue du Faubourg",
    "3 allée des Roses",
]
_CITIES = ["Paris", "Lyon", "Marseille", "Bordeaux", "Nantes"]
_POSTCODES = ["75001", "69001", "13001", "33000", "44000"]
_PHONE_NUMBERS = [
    "+33612345678",
    "+33623456789",
    "+33634567890",
    "+33645678901",
    "+33656789012",
    "+33667890123",
]

# Minimal rich/text bodies per type
_BODY_RICH = {
    "email": "<p>Hello {name},</p><p>This is a test email. Reference: {ref}.</p>",
    "registered_letter": "<p>Madame, Monsieur {name},</p><p>Courrier de test. Référence : {ref}.</p>",
    "letter": "<p>Madame, Monsieur {name},</p><p>Courrier de test. Référence : {ref}.</p>",
}
_BODY_TEXT = {
    "sms": "Bonjour {name}, ceci est un SMS de test. Ref: {ref}.",
    "email": "Hello {name}, this is a test email. Reference: {ref}.",
}


def _name(i):
    first = _FIRST_NAMES[i % len(_FIRST_NAMES)]
    last = _LAST_NAMES[(i * 3) % len(_LAST_NAMES)]
    return f"{first} {last}"


def _email(i):
    first = _FIRST_NAMES[i % len(_FIRST_NAMES)].lower()
    last = _LAST_NAMES[(i * 3) % len(_LAST_NAMES)].lower()
    domain = _DOMAINS[i % len(_DOMAINS)]
    return f"{first}.{last}+{i}@{domain}"


def _phone(i):
    base = _PHONE_NUMBERS[i % len(_PHONE_NUMBERS)]
    # vary the last 4 digits
    suffix = str(i).zfill(4)[-4:]
    return base[:-4] + suffix


def _address(i):
    street = _STREETS[i % len(_STREETS)]
    city = _CITIES[i % len(_CITIES)]
    postcode = _POSTCODES[i % len(_POSTCODES)]
    return {
        "address": f"{street}, {postcode} {city}, France",
    }


def _ref(i):
    return f"DATASET-{i:06d}"


def _distribution(count, missive_types):
    per_type = ceil(count / len(missive_types))
    remaining = count
    result = {}
    for missive_type in missive_types:
        result[missive_type] = min(per_type, remaining)
        remaining -= result[missive_type]
    return result


def _resolve_campaign(command, campaign_id, subject):
    from django_pymissive.models import MissiveCampaign

    if campaign_id is None:
        command.stdout.write("No campaign — missives will be created standalone.")
        return None
    if campaign_id:
        try:
            campaign = MissiveCampaign.objects_plain.get(pk=campaign_id)
        except Exception as exc:
            raise CommandError(f"Campaign not found: {exc}") from exc
        command.stdout.write(f"Using campaign: {campaign.subject} ({campaign.pk})")
        return campaign
    campaign = MissiveCampaign.objects.create(
        subject=subject or f"Dataset {timezone.now().strftime('%Y-%m-%d %H:%M')}",
        email_body_rich="<p>Dataset body</p>",
        email_body_text="Dataset body",
        phone_body_text="Dataset SMS body",
    )
    command.stdout.write(command.style.SUCCESS(f"Created campaign: {campaign.subject} ({campaign.pk})"))
    return campaign


def _recipient_contact(missive_type, index):
    from django_pymissive.models.choices import MissiveSupport

    if missive_type == "sms":
        return MissiveSupport.PHONE, {"phone": _phone(index)}
    if missive_type in ("letter", "registered_letter", "ere", "hand_delivery"):
        return MissiveSupport.ADDRESS, {"address": _address(index)}
    return MissiveSupport.EMAIL, {"email": _email(index)}


def _create_type_batch(campaign, missive_type, count, start_index):
    from django_pymissive.models import Missive
    from django_pymissive.models.choices import (
        MissiveRecipientType,
        MissiveStatus,
    )
    from django_pymissive.models.recipient import MissiveRecipient

    missives = []
    for index in range(start_index, start_index + count):
        name = _name(index)
        reference = _ref(index)
        missive = Missive(
            **({} if campaign is None else {"campaign": campaign}),
            missive_type=missive_type,
            subject=f"[{missive_type.upper()}] Test {reference}",
            body_rich=_BODY_RICH.get(missive_type, "").format(name=name, ref=reference) or None,
            body_text=_BODY_TEXT.get(missive_type, "").format(name=name, ref=reference) or None,
            status=MissiveStatus.DRAFT,
        )
        missive._ensure_missive_defaults()
        missives.append(missive)

    created = Missive.objects.bulk_create(missives)
    recipients = []
    for offset, missive in enumerate(created):
        index = start_index + offset
        support, contact = _recipient_contact(missive_type, index)
        recipients.append(
            MissiveRecipient(
                missive=missive,
                recipient_type=MissiveRecipientType.RECIPIENT,
                recipient_support=support,
                name=_name(index),
                **contact,
            )
        )
    MissiveRecipient.objects.bulk_create(recipients)
    return len(created)


def _success_message(total_created, campaign):
    if campaign is None:
        return f"\n✓ {total_created} standalone missive(s) created"
    return f"\n✓ {total_created} missive(s) created in campaign '{campaign.subject}' ({campaign.pk})"


class Command(BaseCommand):
    help = (
        "Generate a synthetic dataset of DRAFT missives for testing. "
        "Pass a total count; missives are distributed evenly across the requested types."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "count",
            type=int,
            nargs="?",
            default=300,
            help="Total number of missives to create (default: 300).",
        )
        parser.add_argument(
            "--types",
            nargs="+",
            dest="types",
            default=None,
            metavar="TYPE",
            help=(
                f"Missive types to generate (default: {' '.join(DEFAULT_TYPES)}). "
                "Missives are distributed as evenly as possible."
            ),
        )
        parser.add_argument(
            "--campaign",
            dest="campaign_id",
            nargs="?",
            const="",
            default=None,
            metavar="UUID",
            help=(
                "Campaign to attach missives to. "
                "Without a value (--campaign alone) a new campaign is created. "
                "With a UUID, the existing campaign is used. "
                "When the flag is omitted entirely, missives are created without a campaign."
            ),
        )
        parser.add_argument(
            "--subject",
            dest="subject",
            default=None,
            metavar="TEXT",
            help="Subject for the auto-created campaign (ignored when --campaign is given).",
        )

    def handle(self, *args, **options):
        count = options["count"]
        if count < 1:
            raise CommandError("count must be ≥ 1.")

        missive_types = [value.lower() for value in options["types"] or DEFAULT_TYPES]
        campaign = _resolve_campaign(
            self,
            options.get("campaign_id"),
            options.get("subject"),
        )
        distribution = _distribution(count, missive_types)

        self.stdout.write(
            "Distribution: " + " | ".join(f"{missive_type}: {amount}" for missive_type, amount in distribution.items())
        )

        total_created = 0
        global_index = 0
        for missive_type, type_count in distribution.items():
            created = _create_type_batch(
                campaign,
                missive_type,
                type_count,
                global_index,
            )
            total_created += created
            global_index += type_count
            self.stdout.write(f"  {missive_type}: {created} missive(s) created")

        self.stdout.write(self.style.SUCCESS(_success_message(total_created, campaign)))
