"""
Create a synthetic dataset of missives for testing/development.

Generates batches of DRAFT missives (email, sms, lre by default).
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

import uuid
from math import ceil

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

DEFAULT_TYPES = ["email", "sms", "lre"]

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

# Minimal HTML/text bodies per type
_BODY_HTML = {
    "email": "<p>Hello {name},</p><p>This is a test email. Reference: {ref}.</p>",
    "lre": "<p>Madame, Monsieur {name},</p><p>Courrier de test. Référence : {ref}.</p>",
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
        from django_pymissive.models import MissiveCampaign, Missive
        from django_pymissive.models.recipient import MissiveRecipient
        from django_pymissive.models.choices import (
            MissiveRecipientType,
            MissiveStatus,
            MissiveSupport,
        )

        count = options["count"]
        if count < 1:
            raise CommandError("count must be ≥ 1.")

        types = options["types"] or DEFAULT_TYPES
        types = [t.lower() for t in types]

        # ---- resolve campaign ----
        # options["campaign_id"] is:
        #   None  → flag absent → no campaign
        #   ""    → --campaign alone → create a new campaign
        #   "<id>"→ --campaign <uuid> → use existing campaign
        campaign_id = options.get("campaign_id")
        if campaign_id is None:
            campaign = None
            self.stdout.write("No campaign — missives will be created standalone.")
        elif campaign_id == "":
            subject = options["subject"] or f"Dataset {timezone.now().strftime('%Y-%m-%d %H:%M')}"
            campaign = MissiveCampaign.objects.create(
                subject=subject,
                body_html="<p>Dataset body</p>",
                body_text="Dataset body",
                body_sms="Dataset SMS body",
            )
            self.stdout.write(self.style.SUCCESS(f"Created campaign: {campaign.subject} ({campaign.pk})"))
        else:
            try:
                campaign = MissiveCampaign.objects_plain.get(pk=campaign_id)
            except (MissiveCampaign.DoesNotExist, Exception) as exc:
                raise CommandError(f"Campaign not found: {exc}") from exc
            self.stdout.write(f"Using campaign: {campaign.subject} ({campaign.pk})")

        # ---- distribute count across types ----
        per_type = ceil(count / len(types))
        # adjust last type so total == count
        distribution = {}
        remaining = count
        for i, t in enumerate(types):
            if i == len(types) - 1:
                distribution[t] = remaining
            else:
                distribution[t] = min(per_type, remaining)
                remaining -= distribution[t]

        self.stdout.write(
            "Distribution: " + " | ".join(f"{t}: {n}" for t, n in distribution.items())
        )

        # ---- create missives ----
        total_created = 0
        global_index = 0

        for missive_type, type_count in distribution.items():
            missives = []
            recipients = []

            for i in range(type_count):
                idx = global_index + i
                name = _name(idx)
                ref = _ref(idx)

                body_html = _BODY_HTML.get(missive_type, "").format(name=name, ref=ref) or None
                body_text = _BODY_TEXT.get(missive_type, "").format(name=name, ref=ref) or None

                m = Missive(
                    **({} if campaign is None else {"campaign": campaign}),
                    missive_type=missive_type,
                    subject=f"[{missive_type.upper()}] Test {ref}",
                    body_html=body_html,
                    body_text=body_text,
                    status=MissiveStatus.DRAFT,
                )
                m._ensure_missive_defaults()
                missives.append(m)

            created = Missive.objects.bulk_create(missives)

            for i, m in enumerate(created):
                idx = global_index + i
                name = _name(idx)
                if missive_type == "email":
                    recipients.append(MissiveRecipient(
                        missive=m,
                        recipient_type=MissiveRecipientType.RECIPIENT,
                        recipient_support=MissiveSupport.EMAIL,
                        name=name,
                        email=_email(idx),
                    ))
                elif missive_type == "sms":
                    recipients.append(MissiveRecipient(
                        missive=m,
                        recipient_type=MissiveRecipientType.RECIPIENT,
                        recipient_support=MissiveSupport.PHONE,
                        name=name,
                        phone=_phone(idx),
                    ))
                elif missive_type in ("lre", "ere", "hand_delivery"):
                    recipients.append(MissiveRecipient(
                        missive=m,
                        recipient_type=MissiveRecipientType.RECIPIENT,
                        recipient_support=MissiveSupport.ADDRESS,
                        name=name,
                        address=_address(idx),
                    ))
                else:
                    # generic fallback — email
                    recipients.append(MissiveRecipient(
                        missive=m,
                        recipient_type=MissiveRecipientType.RECIPIENT,
                        recipient_support=MissiveSupport.EMAIL,
                        name=name,
                        email=_email(idx),
                    ))

            MissiveRecipient.objects.bulk_create(recipients)

            total_created += len(created)
            global_index += type_count
            self.stdout.write(f"  {missive_type}: {len(created)} missive(s) created")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ {total_created} missive(s) created in campaign '{campaign.subject}' ({campaign.pk})"
            )
        )
