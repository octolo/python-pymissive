"""Retrieve a missive from a provider by partner ID or internal UID."""

from __future__ import annotations

import logging
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .models.choices import (
    MissiveRecipientType,
    MissiveSupport,
    get_missive_support_from_type,
)
from .models.missive import Missive
from .models.recipient import MissiveRecipient

logger = logging.getLogger(__name__)

_RETRIEVE_FIELDS = (
    "subject",
    "body_rich",
    "body_text",
    "sender_name",
    "sender_email",
    "sender_phone",
    "sender_address",
    "reply_to_name",
    "reply_to_email",
    "reply_to_address",
    "brand_name",
)


def _lookup_by_substitute_or_pk(value) -> Missive | None:
    if value in (None, ""):
        return None
    found = Missive.objects.filter(substitute_id=str(value)).first()
    if found:
        return found
    try:
        return Missive.objects.filter(pk=uuid.UUID(str(value))).first()
    except ValueError:
        return None


def lookup_missive(partner_id=None, uid=None) -> Missive | None:
    """Return an existing missive for ``partner_id`` (external_id or pk) or ``uid``.

    ``uid`` matches ``substitute_id`` (provider custom_id / imported internal
    ref) then the missive UUID pk.
    """
    if partner_id:
        found = Missive.objects.filter(external_id=partner_id).first()
        if found:
            return found
        return _lookup_by_substitute_or_pk(partner_id)
    if uid:
        return _lookup_by_substitute_or_pk(uid)
    return None


def _has_retrieve_payload(response: dict) -> bool:
    """True when the provider actually returned missive data."""
    if response.get("events") or response.get("recipients"):
        return True
    return any(response.get(name) not in (None, "") for name in _RETRIEVE_FIELDS)


def _retrieve_kwargs(missive: Missive, partner_id=None, uid=None) -> dict:
    payload = {}
    partner_id = partner_id or missive.external_id
    if partner_id:
        payload["external_id"] = partner_id
        payload["partner_id"] = partner_id
    if uid:
        payload["internal_id"] = str(uid)
    return payload


def _normalize_retrieve_response(response) -> dict:
    if isinstance(response, list):
        return {"events": response}
    if not isinstance(response, dict):
        return {}
    return response


def _call_retrieve(missive: Missive, partner_id=None, uid=None) -> dict:
    if not missive.has_service("retrieve"):
        raise ValidationError(
            _("This provider does not support retrieve for this missive type.")
        )
    response = _normalize_retrieve_response(
        missive.call_provider_service(
            "retrieve", **_retrieve_kwargs(missive, partner_id=partner_id, uid=uid)
        )
    )
    if not _has_retrieve_payload(response):
        raise ValidationError(_("Missive not found."))
    return response


def _is_missive_billed(missive: Missive) -> bool:
    """True when every billed amount on this missive is marked paid."""
    qs = missive.to_missivebilling.filter(billing_amount__gt=0)
    return qs.exists() and not qs.filter(is_billed=False).exists()


def _ingest_retrieve_response(missive: Missive, response: dict, partner_id=None, uid=None) -> None:
    was_billed = _is_missive_billed(missive)
    with transaction.atomic():
        _apply_retrieve_response(missive, response, partner_id=partner_id, uid=uid)
        missive.save()
        if _recipients_from_response(response):
            _replace_retrieve_recipients(missive, response)
        events = response.get("events")
        if events:
            missive.to_missiveevent.all().delete()
            from .signals import suppress_event_billings

            with suppress_event_billings():
                missive.handle_events(events)
        for recipient in missive.recipients.all():
            recipient.set_status()
        missive.set_status()
    _refresh_retrieve_billings(missive)
    if was_billed:
        missive.set_billed()


def _refresh_retrieve_billings(missive: Missive) -> None:
    """Replace local billings only after a successful non-empty provider fetch."""
    if not missive.can_billings():
        return
    try:
        from .billings import _process_billing, load_provider_billings

        bills = load_provider_billings(**missive.get_serialized_data(attachments=False))
    except Exception:
        logger.exception("retrieve billings failed for missive %s", missive.pk)
        return
    if not bills:
        return
    missive.to_missivebilling.all().delete()
    for bill in bills:
        _process_billing(missive, bill)


def retrieve_from_provider(
    *,
    missive: Missive | None = None,
    provider=None,
    missive_type=None,
    partner_id=None,
    uid=None,
) -> tuple[Missive, bool]:
    """Fetch missive data from the provider and persist it.

    Pass ``missive`` to update that row from the provider while keeping
    ``pk`` and ``external_id``. Each section (fields, recipients, events,
    billings) is replaced only when the payload actually contains it.
    Omit it to always create a new missive from the form fields; ``uid`` /
    ``partner_id`` are sent to the provider only. The missive type selects
    the provider service (``retrieve_letter``, ``retrieve_registered_letter``, …).
    """
    created = missive is None
    if created:
        missive = Missive(
            provider=provider,
            missive_type=missive_type,
            external_id=partner_id or None,
            substitute_id=str(uid) if uid else None,
        )
    else:
        partner_id = partner_id or missive.external_id
        uid = uid or missive.substitute_id or missive.pk
    response = _call_retrieve(missive, partner_id=partner_id, uid=uid)
    _ingest_retrieve_response(missive, response, partner_id=partner_id, uid=uid)
    return missive, created


def _nullable_substitute_id(value, pk=None) -> str | None:
    """Store a custom_id only when it differs from the local pk."""
    if value in (None, ""):
        return None
    value = str(value)
    if pk is not None and value == str(pk):
        return None
    return value


def _substitute_id_from_payload(payload: dict, fallback=None) -> str | None:
    for key in ("substitute_id", "custom_id", "internal_id"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    if fallback not in (None, ""):
        return str(fallback)
    return None


def _apply_retrieve_response(missive: Missive, response: dict, partner_id=None, uid=None) -> None:
    """Copy provided fields; leave local values when the payload omits them."""
    external_id = missive.external_id or (
        response.get("external_id")
        or response.get("message_id")
        or partner_id
    )
    for name in _RETRIEVE_FIELDS:
        value = response.get(name)
        if value not in (None, ""):
            setattr(missive, name, value)
    missive.external_id = external_id
    missive.substitute_id = _nullable_substitute_id(
        _substitute_id_from_payload(response, fallback=uid or missive.substitute_id),
        missive.pk,
    )


def _recipients_from_response(response: dict) -> list[dict]:
    recipients = list(response.get("recipients") or [])
    if recipients:
        return recipients
    seen = set()
    collected = []
    for event in response.get("events") or []:
        if not isinstance(event, dict):
            continue
        rec = event.get("recipient") if isinstance(event.get("recipient"), dict) else {}
        rec = dict(rec)
        if event.get("email") and not rec.get("email"):
            rec["email"] = event.get("email")
        if event.get("phone") and not rec.get("phone"):
            rec["phone"] = event.get("phone")
        key = rec.get("email") or rec.get("phone") or rec.get("id")
        if not key or key in seen:
            continue
        seen.add(key)
        collected.append(rec)
    return collected


def _recipient_support_from_payload(rec: dict, missive: Missive) -> str:
    if rec.get("address"):
        return MissiveSupport.ADDRESS
    if rec.get("email"):
        return MissiveSupport.EMAIL
    if rec.get("phone"):
        return MissiveSupport.PHONE
    if rec.get("notification_id"):
        return MissiveSupport.APPLICATION
    return missive.missive_support or get_missive_support_from_type(missive.missive_type)


def _replace_retrieve_recipients(missive: Missive, response: dict) -> None:
    """Drop local recipients and recreate them from the provider payload.

    Caller must have checked that the payload actually lists recipients.
    """
    missive.to_missiverecipient.all().delete()
    for rec in _recipients_from_response(response):
        if not isinstance(rec, dict):
            continue
        email = rec.get("email") or None
        phone = rec.get("phone") or None
        address = rec.get("address") or None
        name = rec.get("name") or ""
        if not email and not phone and not address and not name:
            continue
        MissiveRecipient.objects.create(
            missive=missive,
            recipient_type=MissiveRecipientType.RECIPIENT,
            recipient_support=_recipient_support_from_payload(rec, missive),
            name=name,
            email=email,
            phone=phone,
            address=address,
            external_id=rec.get("external_id") or None,
            substitute_id=_nullable_substitute_id(_substitute_id_from_payload(rec)),
            tracking_number=rec.get("tracking_number") or None,
        )
