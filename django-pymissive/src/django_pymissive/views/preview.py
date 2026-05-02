"""Preview views for Missive and MissiveCampaign models.

Campaign previews use an unsaved Missive with ``campaign`` (and ``campaign_id``) set,
so templates and compiled bodies use the same code paths as a real missive.
"""

from types import MethodType

from django.contrib.admin.views.decorators import staff_member_required
from django.forms import modelform_factory
from django.http import Http404, HttpResponse
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
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


def _safe_missive_context(missive):
    """Template context without preview/attachment widgets (unsaved missive has no pk)."""
    ctx = {}
    if missive.campaign_id:
        ctx = dict(getattr(missive.campaign, "additional_context", {}) or {})
    ctx.update(missive.additional_context or {})
    empty = mark_safe("")
    ctx["show_preview_browser"] = empty
    ctx["show_preview_browser_text"] = ""
    ctx["show_attachments_linked"] = empty
    ctx["show_attachments_linked_text"] = ""
    return ctx


def attach_unsaved_missive_preview_context(missive: Missive) -> None:
    """Bind a safe ``missive_context`` when the row is not saved (campaign preview, draft POST)."""
    if missive.pk is not None:
        return
    missive.missive_context = MethodType(_safe_missive_context, missive)


def missive_for_campaign_preview(campaign: MissiveCampaign, preview_kind: str) -> Missive:
    """Unsaved missive linked to ``campaign`` so getters and compilation match a real missive."""
    missive = Missive(
        campaign=campaign,
        missive_type=_campaign_preview_kind_to_missive_type(preview_kind),
        status=MissiveStatus.DRAFT,
        thread_type=MissiveThreadType.MISSIVE,
    )
    missive._ensure_missive_defaults()
    attach_unsaved_missive_preview_context(missive)
    return missive


def template_for_missive(missive: Missive) -> str:
    """Resolve template path from ``missive.missive_type``."""
    return MISSIVE_TEMPLATE_MAP.get((missive.missive_type or "").lower(), DEFAULT_TEMPLATE)


def build_preview_context(missive: Missive, post_data=None) -> dict:
    """Type-specific template context (email headers, SMS sender, postal meta)."""
    try:
        mt = (missive.missive_type or "").lower()
        if mt in ("email", "email_marketing", "ere"):
            return _build_email_context(missive)
        if mt in ("sms", "rcs"):
            return _build_sms_context(missive, post_data)
        if mt in ("postal", "postal_registered", "postal_signature", "lre", "lre_qualified"):
            return _build_lre_context(missive)
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


def _build_lre_context(instance, post_data=None):
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
    if recipient_manager and getattr(instance, "pk", None):
        try:
            for r in recipient_manager.filter(
                recipient_type=MissiveRecipientType.RECIPIENT
            ):
                recipients.append({
                    "name": r.name or "",
                    "address_lines": _geoaddress_lines(r.address),
                })
        except Exception:
            pass

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
        "sender_address_lines": _geoaddress_lines(sender_address),
        "postal_recipients": recipients,
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
            context["title"] = _("Preview: {} ({})").format(self.object, channel)
        else:
            context["title"] = _("Preview: {}").format(missive)

        extra = build_preview_context(missive)
        if extra:
            context.update(extra)
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
                "title": title,
            }
        else:
            if isinstance(instance, Missive):
                instance._ensure_missive_defaults()
            missive = instance
            attach_unsaved_missive_preview_context(missive)
            mt = self._preview_kind_for_missive(missive, request.POST)
            context = {
                "missive": missive,
                "title": _("Preview: {}").format(mt or "Missive"),
            }

        template_name = template_for_missive(missive)
        extra = build_preview_context(missive, post_data=request.POST)
        if extra:
            context.update(extra)
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

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        if self._key == "missive":
            pdf_bytes = self.object.body_to_pdf()
            filename = f"missive-{self.object.pk}.pdf"
        else:
            missive = missive_for_campaign_preview(self.object, "postal")
            pdf_bytes = missive.body_to_pdf()
            filename = f"campaign-{self.object.pk}.pdf"

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
