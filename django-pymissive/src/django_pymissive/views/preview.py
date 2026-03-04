"""Preview views for Missive and MissiveCampaign models."""

from types import SimpleNamespace

from django.contrib.admin.views.decorators import staff_member_required
from django.forms import modelform_factory
from django.http import Http404
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, View

from ..models.campaign import MissiveCampaign
from ..models.choices import MissiveRecipientType
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

CAMPAIGN_TEMPLATE_MAP = {
    "email": "django_pymissive/email_preview.html",
    "sms": "django_pymissive/sms_preview.html",
    "postal": "django_pymissive/postal_preview.html",
}

DEFAULT_TEMPLATE = "django_pymissive/base_preview.html"

_PREVIEW_CONFIG = {
    "missive": {"model": Missive, "template_map": MISSIVE_TEMPLATE_MAP},
    "campaign": {"model": MissiveCampaign, "template_map": CAMPAIGN_TEMPLATE_MAP},
}

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
    phone = getattr(instance, "sender_phone", None)
    ctx = {
        "sender_name": getattr(instance, "sender_name", "") or "",
        "sender_phone": str(phone) if phone else "",
    }
    if post_data and (not ctx["sender_phone"] or not ctx["sender_name"]):
        if not ctx["sender_phone"]:
            ctx["sender_phone"] = _phone_from_post(post_data, "sender_phone")
        if not ctx["sender_name"]:
            ctx["sender_name"] = post_data.get("sender_name", "")
    return ctx


def _build_context_by_type(preview_type, instance, post_data=None):
    pt = (preview_type or "").lower()
    if pt in ("email", "email_marketing", "ere"):
        return _build_email_context(instance)
    if pt in ("sms", "rcs"):
        return _build_sms_context(instance, post_data)
    if pt in ("postal", "postal_registered", "postal_signature", "lre", "lre_qualified"):
        return {}
    return {}


def _build_email_context(instance):
    """Email header context; recipients from to_missiverecipient when saved."""
    context = {
        "sender_name": getattr(instance, "sender_name", "") or "",
        "sender_email": getattr(instance, "sender_email", "") or "",
        "reply_to_name": "",
        "reply_to_email": "",
        "to_recipients": [],
        "cc_recipients": [],
        "bcc_recipients": [],
    }

    recipient_manager = getattr(instance, "to_missiverecipient", None)
    if recipient_manager is None or not getattr(instance, "pk", None):
        return context

    try:
        for r in recipient_manager.all():
            email = _format_recipient_email(r)
            item = {"name": r.name or "", "email": email}
            if r.recipient_type == MissiveRecipientType.REPLY_TO:
                context["reply_to_name"] = r.name or ""
                context["reply_to_email"] = email
            elif r.recipient_type == MissiveRecipientType.RECIPIENT:
                context["to_recipients"].append(item)
            elif r.recipient_type == MissiveRecipientType.CC:
                context["cc_recipients"].append(item)
            elif r.recipient_type == MissiveRecipientType.BCC:
                context["bcc_recipients"].append(item)
    except Exception:
        pass

    return context


def _campaign_attachments_physical(campaign):
    if not getattr(campaign, "pk", None):
        return []
    try:
        return list(campaign.attachments_physical)
    except Exception:
        return []


def _campaign_to_missive_preview(campaign, preview_type):
    attachments_physical = _campaign_attachments_physical(campaign)
    if preview_type == "email":
        return SimpleNamespace(
            subject=campaign.subject,
            body=campaign.body,
            body_text=campaign.body_text,
            body_compiled=campaign.body_compiled,
            body_text_compiled=campaign.body_text_compiled,
            sender_name=campaign.sender_name or "",
            sender_email=campaign.sender_email or "",
            sender_phone="",
            recipient_name="",
            sender_address=None,
            recipient_address=None,
            attachments_physical=attachments_physical,
        )
    if preview_type == "sms":
        return SimpleNamespace(
            body_text=getattr(campaign, "body_sms", "") or "",
            body="",
            sender_name=campaign.sender_name or "",
            sender_phone=getattr(campaign, "sender_phone", "") or "",
            attachments_physical=attachments_physical,
        )
    # postal
    return SimpleNamespace(
        body=(
            campaign.body_postal_compiled()
            if hasattr(campaign, "body_postal_compiled")
            else getattr(campaign, "body_postal", "") or ""
        ),
        body_text="",
        sender_name=campaign.sender_name or "",
        sender_address=getattr(campaign, "sender_address", None),
        recipient_name="",
        recipient_address=None,
        attachments_physical=attachments_physical,
    )


class PreviewView(DetailView):

    context_object_name = "missive"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        key = kwargs.get("campaign_or_missive", "")
        config = _PREVIEW_CONFIG.get(key)
        if config is None:
            raise Http404
        self._key = key
        self.model = config["model"]
        self._template_map = config["template_map"]

    def get_preview_type(self):
        if self._key == "missive":
            return (self.object.missive_type or "").lower()
        return self.request.GET.get("type", "email").lower()

    def get_preview_object(self):
        if self._key == "campaign":
            return _campaign_to_missive_preview(self.object, self.get_preview_type())
        return self.object

    def get_template_names(self):
        return [self._template_map.get(self.get_preview_type(), DEFAULT_TEMPLATE)]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        preview_type = self.get_preview_type()

        context["missive"] = self.get_preview_object()

        if self._key == "campaign":
            context["campaign"] = self.object
            context["title"] = _("Preview: {} ({})").format(self.object, preview_type)
        else:
            context["title"] = _("Preview: {}").format(self.object)

        type_ctx = _build_context_by_type(preview_type, self.object)
        if type_ctx:
            context.update(type_ctx)
        return context


@method_decorator(staff_member_required, name="dispatch")
class PreviewFormView(View):

    http_method_names = ["post"]

    def _get_config(self):
        key = self.kwargs.get("campaign_or_missive", "")
        config = _PREVIEW_CONFIG.get(key)
        if config is None:
            raise Http404
        return key, config

    def _get_preview_type(self, key, instance):
        if key == "missive":
            missive_type = getattr(instance, "missive_type", None) or self.request.POST.get("missive_type")
            if missive_type:
                instance.missive_type = missive_type
            return (missive_type or "").lower()
        return (
            self.request.GET.get("type")
            or self.request.POST.get("_preview_type")
            or self.request.POST.get("_preview")
            or "email"
        ).lower()

    def _get_context(self, key, instance, preview_type):
        if key == "campaign":
            return {
                "campaign": instance,
                "missive": _campaign_to_missive_preview(instance, preview_type),
                "title": _("Preview: {} ({})").format(getattr(instance, "name", None) or getattr(instance, "subject", None) or "Campaign", preview_type),
            }
        return {
            "missive": instance,
            "title": _("Preview: {}").format(preview_type or "Missive"),
        }

    def post(self, request, *args, **kwargs):
        key, config = self._get_config()
        model = config["model"]
        template_map = config["template_map"]

        form = _build_form(model, request.POST, pk=request.GET.get("pk"))
        instance = (
            form.save(commit=False)
            if form.is_valid()
            else _populate_from_invalid_form(model, form, request.POST)
        )

        preview_type = self._get_preview_type(key, instance)
        template_name = template_map.get(preview_type, DEFAULT_TEMPLATE)
        context = self._get_context(key, instance, preview_type)
        type_ctx = _build_context_by_type(preview_type, instance, post_data=request.POST)
        if type_ctx:
            context.update(type_ctx)
        return TemplateResponse(request, template_name, context)
