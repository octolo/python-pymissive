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
    "postal": "django_pymissive/postal_preview.html",
    "postal_registered": "django_pymissive/postal_preview.html",
    "postal_signature": "django_pymissive/postal_preview.html",
    "lre": "django_pymissive/postal_preview.html",
    "lre_qualified": "django_pymissive/postal_preview.html",
}

DEFAULT_TEMPLATE = "django_pymissive/base_preview.html"

POSTAL_PREVIEW_MISSIVE_TYPES = frozenset(
    k for k, v in MISSIVE_TEMPLATE_MAP.items()
    if v == "django_pymissive/postal_preview.html"
)


def missive_is_postal_like(m: Missive) -> bool:
    return (getattr(m, "missive_type", None) or "").lower() in POSTAL_PREVIEW_MISSIVE_TYPES


_PREVIEW_MODEL = {
    "missive": Missive,
    "campaign": MissiveCampaign,
}


def _campaign_preview_kind_to_missive_type(kind: str) -> str:
    """Map campaign ?type= (email|sms|postal) to a concrete MissiveType value."""
    k = (kind or "email").lower()
    if k == "sms":
        return str(MissiveType.SMS)
    if k in ("postal", "postal_registered", "postal_signature", "lre", "lre_qualified"):
        return str(MissiveType.LRE)
    return str(MissiveType.EMAIL)


def missive_for_campaign_preview(campaign: MissiveCampaign, preview_kind: str) -> Missive:
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
    missive._ensure_missive_defaults()
    return missive


def template_for_missive(missive: Missive) -> str:
    """Resolve template path from ``missive.missive_type``."""
    return MISSIVE_TEMPLATE_MAP.get((missive.missive_type or "").lower(), DEFAULT_TEMPLATE)


def build_preview_context(missive: Missive, post_data=None, postal_recipient_pk=None) -> dict:
    """Type-specific template context (email headers, SMS sender, postal meta)."""
    try:
        mt = (missive.missive_type or "").lower()
        if mt in ("email", "email_marketing", "ere"):
            return _build_email_context(missive)
        if mt in ("sms", "rcs"):
            return _build_sms_context(missive, post_data)
        if mt in POSTAL_PREVIEW_MISSIVE_TYPES:
            return _build_lre_context(missive, post_data, postal_recipient_pk)
    except Exception:
        pass
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

    for field_name, value in (form.cleaned_data or {}).items():
        if value is not None:
            try:
                setattr(instance, field_name, value)
            except (ValueError, TypeError):
                pass

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

    return instance


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
        return phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )
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
        order = [
            "address_line_1", "address_line_2", "address_line_3",
            "postal_code", "city", "state", "region", "country",
        ]
        lines = []
        for key in order:
            val = addr.get(key)
            if val and str(val).strip():
                lines.append(str(val).strip())
        if not lines:
            for val in addr.values():
                if val and str(val).strip():
                    lines.append(str(val).strip())
        return lines
    return [str(addr)]


def _build_lre_context(instance, post_data=None, postal_recipient_pk=None):
    """LRE sender/recipient/delivery context."""
    sender = getattr(instance, "sender", None) or {}
    sender_address = sender.get("address") if isinstance(sender, dict) else None
    if not sender_address:
        sender_address = getattr(instance, "sender_address", None)

    reply_to = getattr(instance, "reply_to", None)
    reply_to_address = None
    if isinstance(reply_to, dict):
        reply_to_address = reply_to.get("address")
    if not reply_to_address:
        reply_to_address = getattr(instance, "reply_to_address", None)

    recipients = []
    recipient_manager = getattr(instance, "to_missiverecipient", None)
    if recipient_manager and getattr(instance, "is_persisted", False):
        try:
            for r in recipient_manager.filter(
                recipient_type=MissiveRecipientType.RECIPIENT
            ).order_by("name", "pk"):
                recipients.append({
                    "pk": r.pk,
                    "name": r.name or "",
                    "address":  r.address,
                })
        except Exception:
            pass

    letter_rec = None
    letter_pk = None
    if postal_recipient_pk is not None and recipients:
        try:
            target = int(postal_recipient_pk)
        except (TypeError, ValueError):
            target = None
        if target is not None:
            for d in recipients:
                if d["pk"] == target:
                    letter_rec = d
                    letter_pk = d["pk"]
                    break
    if letter_rec is None and recipients:
        letter_rec = recipients[0]
        letter_pk = recipients[0]["pk"]

    acknowledgement_display = ""
    delivery_mode_display = ""
    priority_display = ""
    if hasattr(instance, "get_acknowledgement_display"):
        try:
            acknowledgement_display = instance.get_acknowledgement_display() or ""
        except Exception:
            pass
    if hasattr(instance, "get_delivery_mode_display"):
        try:
            delivery_mode_display = instance.get_delivery_mode_display() or ""
        except Exception:
            pass
    if hasattr(instance, "get_priority_display"):
        try:
            priority_display = instance.get_priority_display() or ""
        except Exception:
            pass

    return {
        "sender": sender,
        "sender_address": sender_address,
        "postal_recipients": recipients,
        "postal_letter_recipient": letter_rec,
        "postal_letter_recipient_pk": letter_pk,
        "acknowledgement_display": acknowledgement_display,
        "delivery_mode_display": delivery_mode_display,
        "priority_display": priority_display,
    }


def _build_email_context(instance):
    """Email header context; recipients from to_missiverecipient when saved."""
    sender = getattr(instance, "sender", None) or getattr(instance, "email_sender", None) or {}
    if not isinstance(sender, dict):
        sender = {}
    reply_to = getattr(instance, "reply_to", None) or getattr(instance, "email_reply_to", None)
    if isinstance(reply_to, dict) and not (
        (reply_to.get("email") or "").strip() or (reply_to.get("name") or "").strip()
    ):
        reply_to = None
    context = {
        "sender": sender,
        "reply_to": reply_to,
        "to_recipients": [],
        "cc_recipients": [],
        "bcc_recipients": [],
    }

    recipient_manager = getattr(instance, "to_missiverecipient", None)
    if recipient_manager is None or not getattr(instance, "pk", None):
        return context

    try:
        for r in recipient_manager.all():
            if r.recipient_type == MissiveRecipientType.RECIPIENT:
                email = _format_recipient_email(r)
                context["to_recipients"].append({"name": r.name or "", "email": email})
            elif r.recipient_type == MissiveRecipientType.CC:
                email = _format_recipient_email(r)
                context["cc_recipients"].append({"name": r.name or "", "email": email})
            elif r.recipient_type == MissiveRecipientType.BCC:
                email = _format_recipient_email(r)
                context["bcc_recipients"].append({"name": r.name or "", "email": email})
    except Exception:
        pass

    return context


class PreviewView(DetailView):
    """GET preview: ``missive`` URL uses the saved row; ``campaign`` builds an unsaved missive."""

    context_object_name = "missive"

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
        if (
            self._key == "missive"
            and self.recipient_pk is None
            and missive_is_postal_like(self.object)
        ):
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
            self._missive_for_preview = missive_for_campaign_preview(self.object, kind)
        else:
            self._missive_for_preview = self.object
        return self._missive_for_preview

    def get_template_names(self):
        if not getattr(self, "object", None):
            return [DEFAULT_TEMPLATE]
        return [template_for_missive(self.get_missive_for_preview())]

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
        context["provider_address_css_lre"] = missive.get_provider_address_css_lre()
        # For postal-like missives the preview shows the same PDF as the one
        # sent to the provider — regenerate it so processors / body changes
        # are reflected. No-op for unsaved missives (campaign preview).
        if missive_is_postal_like(missive):
            missive.ensure_first_document()
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
            self.request.GET.get("type")
            or post_data.get("_preview_type")
            or post_data.get("_preview")
            or "email"
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
            form.save(commit=False)
            if form.is_valid()
            else _populate_from_invalid_form(model, form, request.POST)
        )

        if key == "campaign":
            preview_kind = self._preview_kind_for_campaign(request.POST)
            missive = missive_for_campaign_preview(instance, preview_kind)
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
        context["provider_address_css_lre"] = missive.get_provider_address_css_lre()
        return TemplateResponse(request, template_name, context)


@method_decorator(staff_member_required, name="dispatch")
class DownloadPDFView(DetailView):
    """Download the compiled body as a PDF file."""

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
