"""Resolve preview sources to one missive-based rendering pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _

from ..models.campaign import MissiveCampaign
from ..models.campaign_step import CampaignStep
from ..models.campaign_target import CampaignTarget
from ..models.choices import (
    MissiveRecipientType,
    MissiveStatus,
    MissiveThreadType,
    MissiveType,
)
from ..models.missive import Missive

MISSIVE_TEMPLATE_MAP = {
    "email": "django_pymissive/email_preview.html",
    "email_marketing": "django_pymissive/email_preview.html",
    "ere": "django_pymissive/email_preview.html",
    "sms": "django_pymissive/sms_preview.html",
    "rcs": "django_pymissive/sms_preview.html",
    "letter": "django_pymissive/postal_preview.html",
    "registered_letter": "django_pymissive/postal_preview.html",
    "hand_delivery": "django_pymissive/postal_preview.html",
}

DEFAULT_TEMPLATE = "django_pymissive/base_preview.html"
BRANDED_PREVIEW_TEMPLATE = "django_pymissive/branded_preview.html"
POSTAL_PREVIEW_MISSIVE_TYPES = frozenset(
    key for key, template in MISSIVE_TEMPLATE_MAP.items() if template == "django_pymissive/postal_preview.html"
)
_PREVIEW_RECIPIENT_FIELDS = ("email", "phone", "address", "notification_id")


class AmbiguousPreviewStep(ValueError):
    """Raised when a campaign preview needs an explicit step selection."""


@dataclass(frozen=True)
class PreviewRecipient:
    recipient_type: str
    name: str = ""
    email: object = ""
    phone: object = ""
    address: object = None
    notification_id: object = ""
    pk: None = None

    @classmethod
    def from_contact(cls, recipient_type: str, name: str, field: str, contact) -> PreviewRecipient:
        values: dict[str, object] = {key: "" for key in _PREVIEW_RECIPIENT_FIELDS}
        values["address"] = None
        values[field] = contact
        return cls(
            recipient_type=recipient_type,
            name=name or "",
            email=values["email"],
            phone=values["phone"],
            address=values["address"],
            notification_id=values["notification_id"],
        )


@dataclass(frozen=True)
class PreviewRuntimeData:
    related_objects: tuple[object, ...] = ()
    recipients: tuple[PreviewRecipient, ...] = ()


PreviewSource = Missive | MissiveCampaign | CampaignStep | CampaignTarget


@dataclass(frozen=True)
class ResolvedPreview:
    """A preview source normalized to the missive rendered by every frontend."""

    missive: Missive
    source: PreviewSource
    campaign: MissiveCampaign | None
    campaign_step: CampaignStep | None
    target: CampaignTarget | None
    preview_kind: str
    runtime_data: PreviewRuntimeData

    @property
    def template_names(self) -> list[str]:
        return template_for_missive(self.missive)


def missive_is_postal_like(missive: Missive) -> bool:
    return (getattr(missive, "missive_type", None) or "").lower() in POSTAL_PREVIEW_MISSIVE_TYPES


def normalize_brand(value) -> str:
    """Return a safe template slug, never an arbitrary template path."""
    brand = str(value or "").strip().lower()
    return brand if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", brand) else ""


def _provider_brand_candidates(provider) -> list:
    if not provider:
        return []
    inner = getattr(provider, "_provider", None)
    if inner is None:
        return []
    return [getattr(inner, "preview_brand", None)]


def missive_brand(missive: Missive) -> str:
    """Application selected by the provider, independent from missive type."""
    for candidate in _provider_brand_candidates(getattr(missive, "provider", None)):
        brand = normalize_brand(candidate)
        if brand:
            return brand
    return ""


def campaign_preview_query(*, kind: str, brand: str = "", campaign_step=None) -> str:
    """Query string selecting one campaign step and its preview template."""
    params = [f"type={(kind or 'email').lower()}"]
    normalized = normalize_brand(brand)
    if (kind or "").lower() == "branded" and normalized:
        params.append(f"brand={normalized}")
    if campaign_step is not None and getattr(campaign_step, "pk", None):
        params.append(f"step={campaign_step.pk}")
    return "?" + "&".join(params)


def preview_kind_for_missive_type(missive_type: str) -> str:
    mt = (missive_type or "").lower()
    if mt in POSTAL_PREVIEW_MISSIVE_TYPES:
        return "postal"
    if mt in ("sms", "rcs"):
        return "sms"
    if mt == "branded":
        return "branded"
    return "email"


def _preview_kind_to_missive_type(kind: str) -> str:
    normalized = (kind or "email").lower()
    if normalized == "sms":
        return str(MissiveType.SMS)
    if normalized == "branded":
        return str(MissiveType.BRANDED)
    if normalized in ("postal", "letter", "hand_delivery"):
        return str(MissiveType.LETTER)
    if normalized == "registered_letter":
        return str(MissiveType.REGISTERED_LETTER)
    return str(MissiveType.EMAIL)


def missive_for_campaign_preview(
    campaign: MissiveCampaign,
    preview_kind: str,
    *,
    brand: str | None = None,
    campaign_step: CampaignStep | None = None,
) -> Missive:
    """Build the unsaved missive used to preview a campaign step."""
    if campaign_step is not None:
        if campaign.pk and campaign_step.campaign_id != campaign.pk:
            raise ValueError("campaign_step does not belong to campaign")
        missive_type = campaign_step.missive_type
    else:
        missive_type = _preview_kind_to_missive_type(preview_kind)
        if campaign.pk:
            steps = list(
                campaign.to_campaignstep.filter(missive_type=missive_type).order_by("position", "pk")[:2],
            )
            if len(steps) > 1:
                raise AmbiguousPreviewStep(
                    f"Campaign {campaign.pk} has multiple {missive_type!r} steps; select one explicitly.",
                )
            campaign_step = steps[0] if steps else None
    missive = Missive(
        campaign_step=campaign_step,
        missive_type=missive_type,
        status=MissiveStatus.DRAFT,
        thread_type=MissiveThreadType.MISSIVE,
    )
    normalized_brand = normalize_brand(brand)
    if normalized_brand:
        missive.provider = normalized_brand
    missive._ensure_missive_defaults()
    return missive


def _target_object(row: CampaignTarget):
    if not row.content_type_id or not row.object_id:
        return None
    try:
        return row.target
    except ObjectDoesNotExist:
        return None


def missive_for_target_preview(row: CampaignTarget) -> Missive:
    """Build an unsaved target missive with pure related-object and recipient data."""
    from ..processors.build_target import ordered_target_contacts, recipient_field_for_missive_type

    step = row.campaign_step if row.campaign_step_id else None
    missive = missive_for_campaign_preview(
        row.campaign,
        preview_kind_for_missive_type(row.missive_type),
        campaign_step=step,
    )
    target = _target_object(row)
    field = recipient_field_for_missive_type(row.missive_type)
    recipients = (
        tuple(
            PreviewRecipient.from_contact(recipient_type, name, field, contact)
            for recipient_type, name, contact in ordered_target_contacts(row)
        )
        if field
        else ()
    )
    setattr(  # noqa: B010 - preview-only runtime data is not a model field
        missive,
        "_preview_runtime",
        PreviewRuntimeData(
            related_objects=(target,) if target is not None else (),
            recipients=recipients,
        ),
    )
    return missive


def _missive_for_preview_source(
    source: PreviewSource,
    *,
    preview_kind: str,
    brand: str,
    campaign_step: CampaignStep | None,
) -> Missive:
    if isinstance(source, Missive):
        return source
    if isinstance(source, CampaignTarget):
        return source.missive or missive_for_target_preview(source)
    if isinstance(source, CampaignStep):
        return missive_for_campaign_preview(
            source.campaign,
            preview_kind_for_missive_type(source.missive_type),
            brand=brand,
            campaign_step=source,
        )
    if isinstance(source, MissiveCampaign):
        return missive_for_campaign_preview(
            source,
            preview_kind,
            brand=brand,
            campaign_step=campaign_step,
        )
    raise TypeError(f"Unsupported preview source: {type(source).__name__}")


def _campaign_for_preview(
    source: PreviewSource,
    campaign_step: CampaignStep | None,
) -> MissiveCampaign | None:
    if campaign_step is not None:
        return campaign_step.campaign
    if isinstance(source, MissiveCampaign):
        return source
    if isinstance(source, CampaignTarget):
        return source.campaign
    return None


def resolve_preview(
    source: PreviewSource,
    *,
    preview_kind: str = "email",
    brand: str = "",
    campaign_step: CampaignStep | None = None,
) -> ResolvedPreview:
    """Normalize a campaign, step, missive or target to one preview value."""
    target = source if isinstance(source, CampaignTarget) else None
    missive = _missive_for_preview_source(
        source,
        preview_kind=preview_kind,
        brand=brand,
        campaign_step=campaign_step,
    )
    step = missive.campaign_step if missive.campaign_step_id else None
    kind = preview_kind_for_missive_type(missive.missive_type)
    runtime_data = getattr(missive, "_preview_runtime", PreviewRuntimeData())
    return ResolvedPreview(
        missive=missive,
        source=source,
        campaign=_campaign_for_preview(source, step),
        campaign_step=step,
        target=target,
        preview_kind=kind,
        runtime_data=runtime_data,
    )


def template_for_missive(missive: Missive) -> list[str]:
    brand = missive_brand(missive)
    mt = (missive.missive_type or "").lower()
    if brand or mt == "branded":
        names = [BRANDED_PREVIEW_TEMPLATE]
        if brand:
            names.insert(0, f"django_pymissive/branded/{brand}_preview.html")
        return names
    return [MISSIVE_TEMPLATE_MAP.get(mt, DEFAULT_TEMPLATE)]


def build_render_context(
    preview: ResolvedPreview,
    *,
    post_data=None,
    postal_recipient_pk=None,
) -> dict:
    """Build the complete template payload shared by GET and POST previews."""
    missive = preview.missive
    context = {
        "missive": missive,
        "title": preview_title(preview),
        "provider_address_css": missive.get_provider_address_css(),
        "sandbox_compiled_body": True,
    }
    if preview.campaign is not None:
        context.update(
            {
                "campaign": preview.campaign,
                "campaign_step": preview.campaign_step,
                "campaign_preview_kind": (
                    preview.campaign_step.missive_type if preview.campaign_step is not None else preview.preview_kind
                ),
            }
        )
    context.update(
        build_preview_context(
            missive,
            post_data=post_data,
            postal_recipient_pk=postal_recipient_pk,
        )
    )
    return context


def preview_title(preview: ResolvedPreview):
    if isinstance(preview.source, CampaignStep):
        return _("Preview: {} — {}").format(preview.source.campaign, preview.source)
    if isinstance(preview.source, MissiveCampaign):
        if preview.campaign_step is not None:
            return _("Preview: {} — {}").format(preview.source, preview.campaign_step)
        return _("Preview: {} ({})").format(preview.source, preview.preview_kind)
    if isinstance(preview.source, CampaignTarget):
        return _("Preview: {}").format(preview.source)
    return _("Preview: {}").format(preview.missive)


def build_preview_context(missive: Missive, post_data=None, postal_recipient_pk=None) -> dict:
    """Build channel-specific display context; compilation context stays on Missive."""
    mt = (missive.missive_type or "").lower()
    if missive_brand(missive) or mt == "branded":
        return _build_branded_context(missive)
    if mt in ("email", "email_marketing", "ere"):
        return _build_email_context(missive)
    if mt in ("sms", "rcs"):
        return _build_sms_context(missive, post_data)
    if mt in POSTAL_PREVIEW_MISSIVE_TYPES:
        return _build_postal_context(missive, postal_recipient_pk)
    return {}


def _phone_from_post(post_data, prefix):
    import phonenumbers

    value = post_data.get(prefix, "")
    if value:
        return str(value).strip()
    region = post_data.get(f"{prefix}_0", "")
    national = post_data.get(f"{prefix}_1", "")
    if not (region and national):
        return ""
    try:
        parsed = phonenumbers.parse(national.strip(), region.strip())
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except phonenumbers.NumberParseException:
        return f"{region} {national}".strip()


def _build_sms_context(instance, post_data=None):
    sender = getattr(instance, "sender", None) or getattr(instance, "phone_sender", {}) or {}
    context = {"sender": sender}
    if post_data and (not sender.get("phone") or not sender.get("name")):
        updated = dict(sender)
        if not updated.get("phone"):
            updated["phone"] = _phone_from_post(post_data, "sender_phone")
        if not updated.get("name"):
            updated["name"] = post_data.get("sender_phone_name", "") or post_data.get("sender_name", "")
        context["sender"] = updated
    return context


def _build_postal_context(instance, postal_recipient_pk=None):
    sender = getattr(instance, "sender", None) or {}
    recipients = _postal_recipients(instance)
    recipient, recipient_pk = _select_postal_recipient(recipients, postal_recipient_pk)
    return {
        "sender": sender,
        "sender_address": _address_value(instance, sender, "sender_address"),
        "postal_recipients": recipients,
        "postal_letter_recipient": recipient,
        "postal_letter_recipient_pk": recipient_pk,
    }


def _address_value(instance, value, fallback_attribute):
    address = value.get("address") if isinstance(value, dict) else None
    return address or getattr(instance, fallback_attribute, None)


def _postal_recipients(instance):
    runtime = getattr(instance, "_preview_runtime", None)
    if runtime is not None:
        return [
            {"pk": recipient.pk, "name": recipient.name or "", "address": recipient.address}
            for recipient in runtime.recipients
            if recipient.recipient_type == MissiveRecipientType.RECIPIENT
        ]
    recipient_manager = getattr(instance, "to_missiverecipient", None)
    if recipient_manager is None or not getattr(instance, "is_persisted", False):
        return []
    queryset = recipient_manager.filter(recipient_type=MissiveRecipientType.RECIPIENT).order_by("name", "pk")
    return [{"pk": recipient.pk, "name": recipient.name or "", "address": recipient.address} for recipient in queryset]


def _select_postal_recipient(recipients, recipient_pk):
    if not recipients:
        return None, None
    target = _optional_int(recipient_pk)
    recipient = next((candidate for candidate in recipients if candidate["pk"] == target), recipients[0])
    return recipient, recipient["pk"]


def _optional_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_branded_context(instance):
    author = (getattr(instance, "brand_name", None) or getattr(instance, "sender_name", None) or "").strip()
    return {
        "brand": missive_brand(instance),
        "author": author,
        "author_initial": (author[:1] or "B").upper(),
    }


def _build_email_context(instance):
    context = {
        "sender": _email_sender(instance),
        "reply_to": _email_reply_to(instance),
        "to_recipients": [],
        "cc_recipients": [],
        "bcc_recipients": [],
    }
    runtime = getattr(instance, "_preview_runtime", None)
    if runtime is not None:
        _append_email_recipients(context, runtime.recipients)
        return context
    recipient_manager = getattr(instance, "to_missiverecipient", None)
    if recipient_manager is None or not getattr(instance, "is_persisted", False):
        return context
    _append_email_recipients(context, recipient_manager.all())
    return context


def _email_sender(instance):
    sender = getattr(instance, "sender", None) or getattr(instance, "email_sender", None) or {}
    return sender if isinstance(sender, dict) else {}


def _email_reply_to(instance):
    reply_to = getattr(instance, "reply_to", None) or getattr(instance, "email_reply_to", None)
    if not isinstance(reply_to, dict):
        return reply_to
    has_value = (reply_to.get("email") or "").strip() or (reply_to.get("name") or "").strip()
    return reply_to if has_value else None


def _format_recipient_email(recipient):
    return recipient.email or (
        str(recipient.phone) if recipient.phone else str(recipient.address) if recipient.address else ""
    )


def _append_email_recipients(context, recipients):
    context_keys = {
        MissiveRecipientType.RECIPIENT: "to_recipients",
        MissiveRecipientType.CC: "cc_recipients",
        MissiveRecipientType.BCC: "bcc_recipients",
    }
    for recipient in recipients:
        key = context_keys.get(recipient.recipient_type)
        if key:
            context[key].append(
                {
                    "name": recipient.name or "",
                    "email": _format_recipient_email(recipient),
                }
            )
