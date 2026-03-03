"""Views for MissiveCampaign model."""

from types import SimpleNamespace

from django.contrib.admin.views.decorators import staff_member_required
from django.forms import modelform_factory
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView

from ..models.campaign import MissiveCampaign

TEMPLATE_MAP = {
    "email": "django_pymissive/email_preview.html",
    "sms": "django_pymissive/sms_preview.html",
    "postal": "django_pymissive/postal_preview.html",
}


def _campaign_email_context():
    """Empty email header context for campaign preview (no sender/recipients)."""
    return {
        "sender_name": "",
        "sender_email": "-",
        "reply_to_name": "",
        "reply_to_email": "",
        "to_recipients": [],
        "cc_recipients": [],
        "bcc_recipients": [],
    }


def _campaign_to_missive_preview(campaign, preview_type):
    """Build a missive-like object for reuse of preview templates."""
    if preview_type == "email":
        return SimpleNamespace(
            subject=campaign.subject,
            body=campaign.body,
            body_text=campaign.body_text,
            body_compiled=campaign.body_compiled,
            body_text_compiled=campaign.body_text_compiled,
            sender_name="",
            sender_email="",
            sender_phone="",
            recipient_name="",
            sender_address=None,
            recipient_address=None,
            attachments_physical=[],
        )
    if preview_type == "sms":
        return SimpleNamespace(
            body_text=getattr(campaign, "body_sms", "") or "",
            body="",
            sender_name="",
            sender_phone="",
            attachments_physical=[],
        )
    # postal
    return SimpleNamespace(
        body=campaign.body_postal_compiled() if hasattr(campaign, "body_postal_compiled") else getattr(campaign, "body_postal", "") or "",
        body_text="",
        sender_name="",
        sender_address=None,
        recipient_name="",
        recipient_address=None,
        attachments_physical=[],
    )


class CampaignPreviewView(DetailView):
    """Preview a campaign (email, SMS or postal content)."""

    model = MissiveCampaign
    context_object_name = "campaign"

    def get_template_names(self):
        preview_type = self.request.GET.get("type", "email").lower()
        return [TEMPLATE_MAP.get(preview_type, TEMPLATE_MAP["email"])]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        preview_type = self.request.GET.get("type", "email").lower()
        context["title"] = _("Preview: {} ({})").format(self.object, preview_type)
        context["missive"] = _campaign_to_missive_preview(self.object, preview_type)
        if preview_type == "email":
            context.update(_campaign_email_context())
        return context


@staff_member_required
@require_http_methods(["POST"])
def campaign_preview_form(request):
    """Preview a campaign from form data."""
    pk = request.POST.get("id") or request.POST.get("_save")
    preview_type = (
        request.GET.get("type")
        or request.POST.get("_preview_type")
        or request.POST.get("_preview")
        or "email"
    ).lower()

    if pk:
        try:
            campaign = MissiveCampaign.objects.get(pk=pk)
            CampaignForm = modelform_factory(MissiveCampaign, fields="__all__")
            form = CampaignForm(request.POST, instance=campaign)
        except MissiveCampaign.DoesNotExist:
            CampaignForm = modelform_factory(MissiveCampaign, fields="__all__")
            form = CampaignForm(request.POST)
    else:
        CampaignForm = modelform_factory(MissiveCampaign, fields="__all__")
        form = CampaignForm(request.POST)

    if form.is_valid():
        campaign = form.save(commit=False)
    else:
        campaign = form.instance if form.instance.pk else MissiveCampaign()
        if hasattr(form, "cleaned_data") and form.cleaned_data:
            for field_name, value in form.cleaned_data.items():
                if value is not None:
                    try:
                        setattr(campaign, field_name, value)
                    except (ValueError, TypeError):
                        pass
        for field_name in form.fields:
            if field_name in request.POST:
                value = request.POST[field_name]
                if value and (
                    not hasattr(campaign, field_name)
                    or getattr(campaign, field_name, None) is None
                ):
                    try:
                        field = form.fields[field_name]
                        if hasattr(field, "widget") and hasattr(
                            field.widget, "value_from_datadict"
                        ):
                            widget_value = field.widget.value_from_datadict(
                                request.POST, None, field_name
                            )
                            if widget_value:
                                try:
                                    setattr(
                                        campaign,
                                        field_name,
                                        field.clean(widget_value),
                                    )
                                except (ValueError, TypeError):
                                    setattr(campaign, field_name, widget_value)
                        else:
                            try:
                                setattr(
                                    campaign,
                                    field_name,
                                    field.clean(value),
                                )
                            except (ValueError, TypeError, AttributeError):
                                setattr(campaign, field_name, value)
                    except (ValueError, TypeError, AttributeError):
                        try:
                            setattr(campaign, field_name, value)
                        except (ValueError, TypeError):
                            pass

    template_name = TEMPLATE_MAP.get(preview_type, TEMPLATE_MAP["email"])
    context = {
        "campaign": campaign,
        "missive": _campaign_to_missive_preview(campaign, preview_type),
        "title": _("Preview: {} ({})").format(campaign.name or "Campaign", preview_type),
    }
    if preview_type == "email":
        context.update(_campaign_email_context())
    return TemplateResponse(request, template_name, context)
