"""Retrieve a missive from a provider by partner ID or internal UID."""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models.choices import MissiveRecipientType
from .models.missive import Missive
from .models.recipient import MissiveRecipient

_RETRIEVE_FIELDS = (
    "subject",
    "body_rich",
    "body_text",
    "sender_name",
    "sender_email",
    "sender_phone",
    "reply_to_name",
    "reply_to_email",
    "brand_name",
)


def lookup_missive(partner_id=None, uid=None) -> Missive | None:
    """Return an existing missive for ``partner_id`` (external_id or pk) or ``uid``."""
    if partner_id:
        found = Missive.objects.filter(external_id=partner_id).first()
        if found:
            return found
        try:
            partner_uid = uuid.UUID(str(partner_id))
        except ValueError:
            return None
        return Missive.objects.filter(pk=partner_uid).first()
    if uid:
        return Missive.objects.filter(pk=uid).first()
    return None


def _has_retrieve_payload(response: dict) -> bool:
    """True when the provider actually returned missive data."""
    if response.get("events") or response.get("recipients"):
        return True
    return any(response.get(name) not in (None, "") for name in _RETRIEVE_FIELDS)


def get_or_retrieve_from_provider(
    *,
    provider,
    missive_type,
    partner_id=None,
    uid=None,
) -> tuple[Missive, bool]:
    """Return ``(missive, created)`` from partner ID or internal UID.

    If a missive already exists (``external_id`` or ``id``), it is returned.
    Otherwise the provider ``retrieve`` service is called and a missive is
    created only when the response contains missive data.
    """
    found = lookup_missive(partner_id=partner_id, uid=uid)
    if found:
        return found, False

    missive = Missive(
        provider=provider,
        missive_type=missive_type,
        external_id=partner_id or None,
    )
    if uid:
        missive.id = uid
    if not missive.has_service("retrieve"):
        raise ValidationError(
            _("This provider does not support retrieve for this missive type.")
        )
    payload = {}
    if partner_id:
        payload["external_id"] = partner_id
        payload["partner_id"] = partner_id
    if uid:
        payload["internal_id"] = str(uid)
    response = missive.call_provider_service("retrieve", **payload)
    if isinstance(response, list):
        response = {"events": response}
    elif not isinstance(response, dict):
        response = {}
    if not _has_retrieve_payload(response):
        raise ValidationError(_("Missive not found."))
    _apply_retrieve_response(missive, response, partner_id=partner_id)
    missive.save()
    _create_retrieve_recipients(missive, response)
    events = response.get("events")
    if events:
        missive.handle_events(events)
    for recipient in missive.recipients.all():
        recipient.set_status()
    missive.set_status()
    return missive, True


def _apply_retrieve_response(missive: Missive, response: dict, partner_id=None) -> None:
    """Copy retrieve payload fields onto this (unsaved) missive."""
    external_id = (
        response.get("external_id")
        or response.get("message_id")
        or partner_id
        or missive.external_id
    )
    if external_id:
        missive.external_id = external_id
    for name in _RETRIEVE_FIELDS:
        value = response.get(name)
        if value not in (None, ""):
            setattr(missive, name, value)


def _create_retrieve_recipients(missive: Missive, response: dict) -> None:
    """Create recipients from retrieve ``recipients`` or unique event targets."""
    recipients = list(response.get("recipients") or [])
    if not recipients:
        seen = set()
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
            recipients.append(rec)
    for rec in recipients:
        if not isinstance(rec, dict):
            continue
        email = rec.get("email") or None
        phone = rec.get("phone") or None
        if not email and not phone and not rec.get("address"):
            continue
        MissiveRecipient.objects.create(
            missive=missive,
            recipient_type=MissiveRecipientType.RECIPIENT,
            recipient_support=missive.missive_support,
            name=rec.get("name") or "",
            email=email,
            phone=phone,
            address=rec.get("address") or None,
            external_id=rec.get("external_id") or None,
        )
