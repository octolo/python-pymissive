"""Preview views for Missive and MissiveCampaign models.

Campaign previews use an unsaved Missive with ``campaign`` (and ``campaign_id``) set,
so templates and compiled bodies use the same code paths as a real missive.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.forms import modelform_factory
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, View

from ..models.campaign import MissiveCampaign
from ..models.choices import (
    MissiveRecipientType,
    MissiveStatus,
    MissiveThreadType,
    MissiveType,
)
from ..models.missive import Missive
from ..models.recipient import MissiveRecipient


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

# Allowlist: the brand is interpolated into a template path.
BRANDED_PREVIEW_BRANDS = frozenset({"discord", "slack", "teams"})

POSTAL_PREVIEW_MISSIVE_TYPES = frozenset(
    k for k, v in MISSIVE_TEMPLATE_MAP.items() if v == "django_pymissive/postal_preview.html"
)


def missive_is_postal_like(m: Missive) -> bool:
    return (getattr(m, "missive_type", None) or "").lower() in POSTAL_PREVIEW_MISSIVE_TYPES


_PREVIEW_MODEL = {
    "missive": Missive,
    "campaign": MissiveCampaign,
}


def _normalize_brand(value) -> str:
    """Return a preview brand, or ``""`` when it is not one we ship a template for."""
    brand = str(value or "").strip().lower()
    return brand if brand in BRANDED_PREVIEW_BRANDS else ""


def _provider_brand_candidates(provider) -> list:
    """Names that may identify the application: provider name, then its brands."""
    if not provider:
        return []
    inner = getattr(provider, "_provider", None)
    candidates = []
    if inner is not None:
        candidates.append(getattr(inner, "name", None))
        brands = getattr(inner, "brands", None) or []
        if isinstance(brands, (list, tuple)):
            candidates.extend(brands)
    candidates.append(getattr(provider, "_value", None))
    if isinstance(provider, str):
        candidates.append(provider)
    return candidates


def _missive_brand(missive: Missive) -> str:
    """Application the missive is sent through (discord, slack, teams).

    The provider decides, not ``missive_type``: a Discord notification is
    still ``notification``. ``brand_name`` is the sender's own brand
    (the company), so it is not used here.
    """
    for candidate in _provider_brand_candidates(getattr(missive, "provider", None)):
        brand = _normalize_brand(candidate)
        if brand:
            return brand
    return ""


def _brand_from_request(request, post_data=None) -> str:
    raw = request.GET.get("brand")
    if not raw and post_data is not None:
        raw = post_data.get("_preview_brand")
    return _normalize_brand(raw)


def campaign_preview_query(*, kind: str, brand: str = "") -> str:
    """Query string selecting a campaign preview template (``?type=…&brand=…``)."""
    params = [f"type={(kind or 'email').lower()}"]
    normalized = _normalize_brand(brand)
    if (kind or "").lower() == "branded" and normalized:
        params.append(f"brand={normalized}")
    return "?" + "&".join(params)


def _campaign_preview_kind_to_missive_type(kind: str) -> str:
    """Map campaign ?type= (email|sms|postal|branded) to a concrete MissiveType value."""
    k = (kind or "email").lower()
    if k == "sms":
        return str(MissiveType.SMS)
    if k == "branded":
        return str(MissiveType.BRANDED)
    if k in ("postal", "letter", "hand_delivery"):
        return str(MissiveType.LETTER)
    if k == "registered_letter":
        return str(MissiveType.REGISTERED_LETTER)
    return str(MissiveType.EMAIL)


def missive_for_campaign_preview(
    campaign: MissiveCampaign,
    preview_kind: str,
    *,
    brand: str | None = None,
) -> Missive:
    """Unsaved missive linked to ``campaign`` so getters and compilation match a real missive.

    The unsaved missive routes ``base_url + get_browser_preview_path()`` and the
    ``show_*`` snippets through ``self.campaign`` automatically (see
    ``Missive.get_browser_preview_path``), so no special context override is needed.
    """
    missive = Missive(
        campaign=campaign,
        missive_type=_campaign_preview_kind_to_missive_type(preview_kind),
        status=MissiveStatus.DRAFT,
        thread_type=MissiveThreadType.MISSIVE,
    )
    brand = _normalize_brand(brand)
    if brand:
        missive.provider = brand
    missive._ensure_missive_defaults()
    return missive


def template_for_missive(missive: Missive) -> list[str]:
    """Template candidates for ``missive``, first existing one wins.

    Discord, Slack and Teams use their preview whenever the provider (or one
    of its brands) matches, whatever the missive type. A branded missive with
    no known application falls back to the generic branded preview.
    """
    brand = _missive_brand(missive)
    mt = (missive.missive_type or "").lower()
    if brand or mt == "branded":
        names = [BRANDED_PREVIEW_TEMPLATE]
        if brand:
            names.insert(0, f"django_pymissive/branded/{brand}_preview.html")
        return names
    return [MISSIVE_TEMPLATE_MAP.get(mt, DEFAULT_TEMPLATE)]


def build_preview_context(missive: Missive, post_data=None, postal_recipient_pk=None) -> dict:
    """Type-specific template context (email headers, SMS sender, postal meta).

    Unknown types return ``{}``. A builder that fails raises: this context is
    also the postal PDF chrome, and swallowing the error used to render an
    empty preview instead of the real fault.
    """
    mt = (missive.missive_type or "").lower()
    if _missive_brand(missive) or mt == "branded":
        return _build_branded_context(missive)
    if mt in ("email", "email_marketing", "ere"):
        return _build_email_context(missive)
    if mt in ("sms", "rcs"):
        return _build_sms_context(missive, post_data)
    if mt in POSTAL_PREVIEW_MISSIVE_TYPES:
        return _build_postal_context(missive, post_data, postal_recipient_pk)
    return {}


def _build_form(model, post_data, pk=None):
    """Bound modelform; uses pk from args, POST id/_save, or explicit pk."""
    ModelForm = modelform_factory(model, fields="__all__")
    pk = pk or post_data.get("id") or post_data.get("_save")
    if pk:
        try:
            return ModelForm(post_data, instance=model.objects.get(pk=pk))
        except model.DoesNotExist:
            pass
    return ModelForm(post_data)


def _set_field(instance, form, field_name, value, post_data):
    """Set field via widget/clean logic or raw value."""
    field = form.fields[field_name]

    if hasattr(field, "widget") and hasattr(field.widget, "value_from_datadict"):
        widget_value = field.widget.value_from_datadict(post_data, None, field_name)
        if widget_value:
            try:
                setattr(instance, field_name, field.clean(widget_value))
                return
            except (ValueError, TypeError):
                setattr(instance, field_name, widget_value)
                return

    try:
        setattr(instance, field_name, field.clean(value))
    except (ValueError, TypeError, AttributeError):
        try:
            setattr(instance, field_name, value)
        except (ValueError, TypeError):
            pass


def _populate_from_invalid_form(model, form, post_data):
    """Instance from cleaned_data + raw POST for empty fields."""
    instance = form.instance if form.instance.pk else model()
    _apply_cleaned_form_data(instance, form.cleaned_data or {})
    _apply_raw_form_data(instance, form, post_data)
    return instance


def _apply_cleaned_form_data(instance, cleaned_data):
    for field_name, value in cleaned_data.items():
        if value is not None:
            try:
                setattr(instance, field_name, value)
            except (ValueError, TypeError):
                pass


def _apply_raw_form_data(instance, form, post_data):
    for field_name in form.fields:
        value = post_data.get(field_name)
        if not value or getattr(instance, field_name, None) is not None:
            continue
        try:
            _set_field(instance, form, field_name, value, post_data)
        except (ValueError, TypeError, AttributeError):
            try:
                setattr(instance, field_name, value)
            except (ValueError, TypeError):
                pass


def _format_recipient_email(r):
    return r.email or (str(r.phone) if r.phone else str(r.address) if r.address else "")


def _phone_from_post(post_data, prefix):
    """Phone from POST (single key or prefix_0/prefix_1)."""
    val = post_data.get(prefix, "")
    if val:
        return str(val).strip()
    region = post_data.get(f"{prefix}_0", "")
    national = post_data.get(f"{prefix}_1", "")
    if not (region and national):
        return ""
    try:
        import phonenumbers

        parsed = phonenumbers.parse(national.strip(), region.strip())
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except Exception:
        return f"{region} {national}".strip()


def _build_sms_context(instance, post_data=None):
    """SMS sender context; fallback to POST when instance is empty."""
    sender = getattr(instance, "sender", None) or getattr(instance, "phone_sender", {}) or {}
    ctx = {
        "sender": sender,
    }
    if post_data and (not sender.get("phone") or not sender.get("name")):
        updated = dict(sender)
        if not updated.get("phone"):
            updated["phone"] = _phone_from_post(post_data, "sender_phone")
        if not updated.get("name"):
            updated["name"] = post_data.get("sender_phone_name", "") or post_data.get("sender_name", "")
        ctx["sender"] = updated
    return ctx


def _geoaddress_lines(addr):
    """Extract displayable address lines from a GeoaddressField value."""
    if not addr:
        return []
    if isinstance(addr, str):
        return [addr] if addr.strip() else []
    if isinstance(addr, dict):
        return _geoaddress_dict_lines(addr)
    return [str(addr)]


def _geoaddress_dict_lines(addr):
    order = (
        "address_line_1",
        "address_line_2",
        "address_line_3",
        "postal_code",
        "city",
        "state",
        "region",
        "country",
    )
    lines = _nonempty_strings(addr.get(key) for key in order)
    return lines or _nonempty_strings(addr.values())


def _nonempty_strings(values):
    return [str(value).strip() for value in values if value and str(value).strip()]


def _build_postal_context(instance, post_data=None, postal_recipient_pk=None):
    """Postal sender/recipient/delivery context."""
    sender = getattr(instance, "sender", None) or {}
    recipients = _postal_recipients(instance)
    letter_recipient, letter_recipient_pk = _select_postal_recipient(recipients, postal_recipient_pk)
    return {
        "sender": sender,
        "sender_address": _address_value(instance, sender, "sender_address"),
        "postal_recipients": recipients,
        "postal_letter_recipient": letter_recipient,
        "postal_letter_recipient_pk": letter_recipient_pk,
        "acknowledgement_display": instance.get_acknowledgement_display() or "",
        "delivery_mode_display": instance.get_delivery_mode_display() or "",
        "priority_display": instance.get_priority_display() or "",
    }


def _address_value(instance, value, fallback_attribute):
    address = value.get("address") if isinstance(value, dict) else None
    return address or getattr(instance, fallback_attribute, None)


def _postal_recipients(instance):
    recipient_manager = getattr(instance, "to_missiverecipient", None)
    if recipient_manager is None or not getattr(instance, "is_persisted", False):
        return []
    queryset = recipient_manager.filter(recipient_type=MissiveRecipientType.RECIPIENT).order_by("name", "pk")
    return [{"pk": recipient.pk, "name": recipient.name or "", "address": recipient.address} for recipient in queryset]


def _select_postal_recipient(recipients, recipient_pk):
    if not recipients:
        return None, None
    target = _optional_int(recipient_pk)
    recipient = next(
        (candidate for candidate in recipients if candidate["pk"] == target),
        recipients[0],
    )
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
        "brand": _missive_brand(instance),
        "author": author,
        "author_initial": (author[:1] or "B").upper(),
    }


def _build_email_context(instance):
    """Email header context; recipients from to_missiverecipient when saved."""
    context = {
        "sender": _email_sender(instance),
        "reply_to": _email_reply_to(instance),
        "to_recipients": [],
        "cc_recipients": [],
        "bcc_recipients": [],
    }
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


class PreviewView(DetailView):
    """GET preview: ``missive`` URL uses the saved row; ``campaign`` builds an unsaved missive.

    Deliberately unauthenticated: this is the "view in browser" link that
    ``processors.body.add_preview_browser`` embeds in outgoing emails, so
    recipients must be able to open it. The unguessable UUID pk is what keeps it
    private. Being recipient-facing, it must also stay side-effect free — it
    must never regenerate the first-document PDF of an already sent missive.
    """

    context_object_name = "missive"
    _key: str
    _missive_for_preview: Missive
    recipient_pk: int | None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        key = kwargs.get("campaign_or_missive", "")
        model = _PREVIEW_MODEL.get(key)
        if model is None:
            raise Http404
        self._key = key
        self.model = model
        rp = kwargs.get("recipient_pk")
        if rp is not None:
            try:
                self.recipient_pk = int(rp)
            except (TypeError, ValueError):
                raise Http404
        else:
            self.recipient_pk = None

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.recipient_pk is not None and self._key != "missive":
            raise Http404
        if self._key == "missive" and self.recipient_pk is None and missive_is_postal_like(self.object):
            first = (
                MissiveRecipient.objects.filter(
                    missive_id=self.object.pk,
                    recipient_type=MissiveRecipientType.RECIPIENT,
                )
                .order_by("name", "pk")
                .first()
            )
            if first is not None:
                return redirect(
                    "django_pymissive:preview_recipient",
                    campaign_or_missive="missive",
                    pk=self.object.pk,
                    recipient_pk=first.pk,
                )
        if self.recipient_pk is not None:
            ok = MissiveRecipient.objects.filter(
                pk=self.recipient_pk,
                missive_id=self.object.pk,
                recipient_type=MissiveRecipientType.RECIPIENT,
            ).exists()
            if not ok:
                raise Http404
        return super().get(request, *args, **kwargs)

    def get_missive_for_preview(self) -> Missive:
        if hasattr(self, "_missive_for_preview"):
            return self._missive_for_preview
        if self._key == "campaign":
            kind = (self.request.GET.get("type") or "email").lower()
            self._missive_for_preview = missive_for_campaign_preview(
                self.object,
                kind,
                brand=_brand_from_request(self.request),
            )
        else:
            self._missive_for_preview = self.object
        return self._missive_for_preview

    def get_template_names(self):
        if not getattr(self, "object", None):
            return [DEFAULT_TEMPLATE]
        return template_for_missive(self.get_missive_for_preview())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        missive = self.get_missive_for_preview()
        context["missive"] = missive

        if self._key == "campaign":
            context["campaign"] = self.object
            channel = (self.request.GET.get("type") or "email").lower()
            context["campaign_preview_kind"] = channel
            context["title"] = _("Preview: {} ({})").format(self.object, channel)
        else:
            context["title"] = _("Preview: {}").format(missive)

        rp = self.recipient_pk if self._key == "missive" else None
        extra = build_preview_context(missive, postal_recipient_pk=rp)
        if extra:
            context.update(extra)
        context["provider_address_css"] = missive.get_provider_address_css()
        context["sandbox_compiled_body"] = True
        return context


@method_decorator(staff_member_required, name="dispatch")
class PreviewFormView(View):
    """POST preview from admin forms (optional); same missive-based rendering as ``PreviewView``."""

    http_method_names = ["post"]

    def _get_config(self):
        key = self.kwargs.get("campaign_or_missive", "")
        model = _PREVIEW_MODEL.get(key)
        if model is None:
            raise Http404
        return key, model

    def _preview_kind_for_campaign(self, post_data) -> str:
        return (
            self.request.GET.get("type") or post_data.get("_preview_type") or post_data.get("_preview") or "email"
        ).lower()

    def _preview_kind_for_missive(self, instance, post_data) -> str:
        missive_type = getattr(instance, "missive_type", None) or post_data.get("missive_type")
        if missive_type:
            instance.missive_type = missive_type
        return (missive_type or "").lower()

    def post(self, request, *args, **kwargs):
        key, model = self._get_config()

        form = _build_form(model, request.POST, pk=request.GET.get("pk"))
        instance = (
            form.save(commit=False) if form.is_valid() else _populate_from_invalid_form(model, form, request.POST)
        )

        if key == "campaign":
            preview_kind = self._preview_kind_for_campaign(request.POST)
            missive = missive_for_campaign_preview(
                instance,
                preview_kind,
                brand=_brand_from_request(request, request.POST),
            )
            title = _("Preview: {} ({})").format(
                getattr(instance, "name", None) or getattr(instance, "subject", None) or "Campaign",
                preview_kind,
            )
            context = {
                "missive": missive,
                "campaign": instance,
                "campaign_preview_kind": preview_kind,
                "title": title,
            }
        else:
            if isinstance(instance, Missive):
                instance._ensure_missive_defaults()
            missive = instance
            mt = self._preview_kind_for_missive(missive, request.POST)
            context = {
                "missive": missive,
                "title": _("Preview: {}").format(mt or "Missive"),
            }

        template_name = template_for_missive(missive)
        extra = build_preview_context(missive, post_data=request.POST, postal_recipient_pk=None)
        if extra:
            context.update(extra)
        context["provider_address_css"] = missive.get_provider_address_css()
        context["sandbox_compiled_body"] = True
        return TemplateResponse(request, template_name, context)


@method_decorator(staff_member_required, name="dispatch")
class DownloadPDFView(DetailView):
    """Download the compiled body as a PDF file."""

    _key: str
    recipient_pk: int | None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        key = kwargs.get("campaign_or_missive", "")
        model = _PREVIEW_MODEL.get(key)
        if model is None:
            raise Http404
        self._key = key
        self.model = model
        rp = kwargs.get("recipient_pk")
        if rp is not None:
            try:
                self.recipient_pk = int(rp)
            except (TypeError, ValueError):
                raise Http404
            if self._key != "missive":
                raise Http404
        else:
            self.recipient_pk = None

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        if self._key == "missive":
            rp = self.recipient_pk
            if rp is not None:
                ok = MissiveRecipient.objects.filter(
                    pk=rp,
                    missive_id=self.object.pk,
                    recipient_type=MissiveRecipientType.RECIPIENT,
                ).exists()
                if not ok:
                    raise Http404
            elif missive_is_postal_like(self.object):
                first = (
                    MissiveRecipient.objects.filter(
                        missive_id=self.object.pk,
                        recipient_type=MissiveRecipientType.RECIPIENT,
                    )
                    .order_by("name", "pk")
                    .first()
                )
                rp = first.pk if first else None
            else:
                rp = None
            pdf_bytes = self.object.body_to_pdf(postal_recipient_pk=rp)
            filename = f"missive-{self.object.pk}.pdf"
        else:
            if self.recipient_pk is not None:
                raise Http404
            preview_kind = (request.GET.get("type") or "postal").lower()
            missive = missive_for_campaign_preview(self.object, preview_kind)
            pdf_bytes = missive.body_to_pdf(postal_recipient_pk=None)
            filename = f"campaign-{self.object.pk}.pdf"

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
