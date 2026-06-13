"""Top-level send shortcuts for django-pymissive.

Provides :func:`send_missive` plus per-type helpers (``send_email``,
``send_sms``, ``send_lre``, …) auto-generated from ``MISSIVE_TYPES``.

Usage::

    from django_pymissive.shortcuts import send_email, send_sms, send_lre

    # Send an email
    missive = send_email(
        name="Alice Martin",
        email="alice@example.com",
        subject="Hello",
        body_rich="<p>Hi Alice!</p>",
        sender_name="Octolo",
        sender_email="hello@octolo.tech",
    )

    # Send an SMS
    missive = send_sms(
        name="Alice Martin",
        phone="+33612345678",
        body_text="Hello from Octolo",
        sender_name="Octolo",
    )

    # Send a postal LRE without triggering the send immediately
    missive = send_lre(
        name="Alice Martin",
        address=my_geo_address,
        body_rich="<p>Letter body</p>",
        sender_name="Octolo",
        and_send=False,
    )
    missive.send_missive()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pymissive.config import GENERIC_SUPPORT, MISSIVE_TYPES

if TYPE_CHECKING:
    from django_pymissive.models import Missive

logger = logging.getLogger(__name__)


def _support_for_type(missive_type: str) -> str:
    """Return support category (email / phone / address / application) for *missive_type*.

    Raises:
        ValueError: If *missive_type* maps to no known support category.
    """
    mt = missive_type.lower()
    for support, types in GENERIC_SUPPORT.items():
        if mt in [t.lower() for t in types]:
            return support
    raise ValueError(
        f"Unknown missive_type {missive_type!r}: no support category found. "
        f"Available types: {', '.join(sorted(MISSIVE_TYPES))}."
    )


def send_missive(
    missive_type: str,
    *,
    # ── recipient ──────────────────────────────────────────────────────────
    name: str = "",
    email: str | None = None,
    phone: str | None = None,
    address=None,
    notification_id: str | None = None,
    # ── content ────────────────────────────────────────────────────────────
    subject: str | None = None,
    body_rich: str | None = None,
    body_text: str | None = None,
    # ── sender ─────────────────────────────────────────────────────────────
    sender_name: str | None = None,
    sender_email: str | None = None,
    sender_phone: str | None = None,
    sender_address=None,
    reply_to_name: str | None = None,
    reply_to_email: str | None = None,
    # ── missive options ────────────────────────────────────────────────────
    campaign=None,
    provider=None,
    acknowledgement: str | None = None,
    delivery_mode: str | None = None,
    priority: str | None = None,
    brand_name: str | None = None,
    # ── escape hatches ─────────────────────────────────────────────────────
    extra_missive_fields: dict | None = None,
    extra_recipient_fields: dict | None = None,
    and_send: bool = True,
) -> "Missive":
    """Create a :class:`~django_pymissive.models.Missive` with one recipient and optionally send it.

    Args:
        missive_type: Registered missive type key (``'email'``, ``'sms'``,
            ``'lre'``, ``'ere'``, …).  See ``pymissive.config.MISSIVE_TYPES``.
        name: Recipient display name.
        email: Recipient e-mail address — used when *support* is ``email``
            (types: ``email``, ``email_marketing``, ``ere``).
        phone: Recipient phone number — used when *support* is ``phone``
            (types: ``sms``, ``rcs``, ``voice_call``).
        address: Recipient postal address (``GeoaddressField`` value) — used
            when *support* is ``address`` (types: ``lre``, ``hand_delivery``).
        notification_id: Device / channel token — used when *support* is
            ``application`` (types: ``push_notification``, ``branded``).
        subject: Message subject (email).
        body_rich: Rich body (HTML, RTF, …) for email, LRE, etc.
        body_text: Plain-text body (sms, email fallback, …).
        sender_name: Display name of the sender.
        sender_email: Sender e-mail address.
        sender_phone: Sender phone number.
        sender_address: Sender postal address.
        reply_to_name: Reply-To display name.
        reply_to_email: Reply-To e-mail address.
        campaign: Optional :class:`~django_pymissive.models.MissiveCampaign`.
        provider: Provider override (``ProviderField`` value).
        acknowledgement: Acknowledgement level (see
            ``pymissive.config.MISSIVE_ACKNOWLEDGEMENT_LEVELS``).
        delivery_mode: Delivery mode — ``'economic'``, ``'normal'``,
            ``'premium'``, or ``'express'``.
        priority: Priority — ``'low'``, ``'normal'``, ``'high'``, or
            ``'urgent'``.
        brand_name: Brand name attached to the missive.
        extra_missive_fields: Extra kwargs forwarded verbatim to
            ``Missive.objects.create(…)``.  Must be a ``dict`` (not a JSON
            string).  Use it for provider-template payloads via
            ``additional_config``, e.g.::

                send_email(
                    name="Charles",
                    email="charles@example.com",
                    sender_name="Octolo",
                    sender_email="contact@octolo.tech",
                    provider="brevo",
                    extra_missive_fields={
                        "additional_config": {
                            "template_id": 1,
                            "use_provider_template": True,
                            "params": {"code": "113334"},
                        }
                    },
                )
        extra_recipient_fields: Extra kwargs forwarded verbatim to the
            recipient ``create(…)`` call.
        and_send: When ``True`` (default) call ``missive.send_missive()``
            immediately after creating the DB rows.  Pass ``False`` to only
            stage the missive for deferred / batch sending.

    Returns:
        The created (and optionally sent) :class:`~django_pymissive.models.Missive`.

    Raises:
        django.core.exceptions.ValidationError: If the missive cannot be sent
            (e.g. missing recipient or body).
    """
    from django_pymissive.models import (
        Missive,
        MissiveRecipientAddress,
        MissiveRecipientApplication,
        MissiveRecipientEmail,
        MissiveRecipientPhone,
        MissiveStatus,
    )

    # Resolve (and validate) the support before creating any DB row.
    support = _support_for_type(missive_type)

    missive_kwargs: dict = {
        "missive_type": missive_type,
        "status": MissiveStatus.DRAFT,
    }
    for _field, _value in (
        ("subject", subject),
        ("body_rich", body_rich),
        ("body_text", body_text),
        ("sender_name", sender_name),
        ("sender_email", sender_email),
        ("sender_phone", sender_phone),
        ("sender_address", sender_address),
        ("reply_to_name", reply_to_name),
        ("reply_to_email", reply_to_email),
        ("campaign", campaign),
        ("provider", provider),
        ("acknowledgement", acknowledgement),
        ("delivery_mode", delivery_mode),
        ("priority", priority),
        ("brand_name", brand_name),
    ):
        if _value is not None:
            missive_kwargs[_field] = _value
    if extra_missive_fields:
        missive_kwargs.update(extra_missive_fields)

    missive = Missive.objects.create(**missive_kwargs)

    recipient_kwargs: dict = {"missive": missive, "name": name}
    if support == "email":
        recipient_cls = MissiveRecipientEmail
        if email is not None:
            recipient_kwargs["email"] = email
    elif support == "phone":
        recipient_cls = MissiveRecipientPhone
        if phone is not None:
            recipient_kwargs["phone"] = phone
    elif support == "address":
        recipient_cls = MissiveRecipientAddress
        if address is not None:
            recipient_kwargs["address"] = address
    else:
        recipient_cls = MissiveRecipientApplication
        if notification_id is not None:
            recipient_kwargs["notification_id"] = notification_id
    if extra_recipient_fields:
        recipient_kwargs.update(extra_recipient_fields)

    recipient_cls.objects.create(**recipient_kwargs)

    if and_send:
        missive.send_missive()

    return missive


def _make_type_shortcut(missive_type: str):
    """Return ``(fn_name, fn)`` for a ``send_<missive_type>()`` helper."""
    fn_name = f"send_{missive_type.replace('-', '_')}"

    def _shortcut(**kwargs) -> "Missive":
        return send_missive(missive_type=missive_type, **kwargs)

    _shortcut.__name__ = fn_name
    _shortcut.__qualname__ = fn_name
    _shortcut.__doc__ = (
        f"Shortcut for :func:`send_missive` with ``missive_type={missive_type!r}``.\n\n"
        "Accepts the same keyword arguments as :func:`send_missive` "
        "except ``missive_type``."
    )
    return fn_name, _shortcut


# ── auto-generate send_<type>() for every registered missive type ──────────
_shortcuts: dict[str, "callable"] = {}

for _mt in MISSIVE_TYPES:
    _fn_name, _fn = _make_type_shortcut(_mt)
    _shortcuts[_fn_name] = _fn
    globals()[_fn_name] = _fn

__all__ = ["send_missive", *_shortcuts.keys()]
