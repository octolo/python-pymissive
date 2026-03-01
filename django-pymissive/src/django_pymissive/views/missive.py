"""Views for Missive model."""

from django.contrib.admin.views.decorators import staff_member_required
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView
from django.forms import modelform_factory

from ..models.missive import Missive
from ..models.choices import MissiveRecipientType

TEMPLATE_MAP = {
    "email": "django_pymissive/email_preview.html",
    "email_marketing": "django_pymissive/email_preview.html",
    "sms": "django_pymissive/sms_preview.html",
    "rcs": "django_pymissive/sms_preview.html",
    "postal": "django_pymissive/postal_preview.html",
    "postal_registered": "django_pymissive/postal_preview.html",
    "postal_signature": "django_pymissive/postal_preview.html",
    "lre": "django_pymissive/postal_preview.html",
    "lre_qualified": "django_pymissive/postal_preview.html",
    "ere": "django_pymissive/email_preview.html",
}


def _format_recipient_email(r):
    """Get email/contact string for a recipient."""
    return r.email or (str(r.phone) if r.phone else str(r.address) if r.address else "")


def _email_preview_context(missive):
    """Build context for email preview with multiple recipients."""
    sender_name = ""
    sender_email = ""
    reply_to_name = ""
    reply_to_email = ""
    to_recipients = []
    cc_recipients = []
    bcc_recipients = []

    if hasattr(missive, "to_missiverecipient") and missive.to_missiverecipient.exists():
        for r in missive.to_missiverecipient.all():
            email = _format_recipient_email(r)
            item = {"name": r.name or "", "email": email}
            if r.recipient_type == MissiveRecipientType.SENDER:
                sender_name = r.name or ""
                sender_email = email
            elif r.recipient_type == MissiveRecipientType.REPLY_TO:
                reply_to_name = r.name or ""
                reply_to_email = email
            elif r.recipient_type == MissiveRecipientType.RECIPIENT:
                to_recipients.append(item)
            elif r.recipient_type == MissiveRecipientType.CC:
                cc_recipients.append(item)
            elif r.recipient_type == MissiveRecipientType.BCC:
                bcc_recipients.append(item)
    else:
        sender = getattr(missive, "sender", None)
        if hasattr(sender, "name"):
            sender_name = sender.name or ""
            sender_email = _format_recipient_email(sender)
        recipient = getattr(missive, "first_recipient", None)
        if hasattr(recipient, "name"):
            to_recipients = [
                {
                    "name": recipient.name or "",
                    "email": _format_recipient_email(recipient),
                }
            ]
        reply_to = getattr(missive, "reply_to", None)
        if hasattr(reply_to, "name"):
            reply_to_name = reply_to.name or ""
            reply_to_email = _format_recipient_email(reply_to)

    return {
        "sender_name": sender_name,
        "sender_email": sender_email,
        "reply_to_name": reply_to_name,
        "reply_to_email": reply_to_email,
        "to_recipients": to_recipients,
        "cc_recipients": cc_recipients,
        "bcc_recipients": bcc_recipients,
    }


class MissivePreviewView(DetailView):
    """Preview a missive (email, SMS, postal, etc.) - Show existing object."""

    model = Missive
    context_object_name = "missive"

    def get_template_names(self):
        missive_type_key = (self.object.missive_type or "").lower()
        template = TEMPLATE_MAP.get(missive_type_key, "django_pymissive/base_preview.html")
        return [template]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = _("Preview: {}").format(self.object)
        template_name = self.get_template_names()[0]
        if "email_preview" in template_name or "email" in template_name:
            context.update(_email_preview_context(self.object))
        return context


@staff_member_required
@require_http_methods(["POST"])
def missive_preview_form(request):
    """Preview a missive from form data - Preview what it will look like."""
    pk = request.POST.get("id") or request.POST.get("_save")

    if pk:
        try:
            missive = Missive.objects.get(pk=pk)
            MissiveForm = modelform_factory(Missive, fields="__all__")
            form = MissiveForm(request.POST, instance=missive)
        except Missive.DoesNotExist:
            MissiveForm = modelform_factory(Missive, fields="__all__")
            form = MissiveForm(request.POST)
    else:
        MissiveForm = modelform_factory(Missive, fields="__all__")
        form = MissiveForm(request.POST)

    if form.is_valid():
        missive = form.save(commit=False)
    else:
        # If form is not valid, try to get values from cleaned_data first
        # (some fields might be valid even if the whole form is not)
        missive = form.instance if form.instance.pk else Missive()

        # Populate from cleaned_data if available
        if hasattr(form, "cleaned_data") and form.cleaned_data:
            for field_name, value in form.cleaned_data.items():
                if value is not None:
                    try:
                        setattr(missive, field_name, value)
                    except (ValueError, TypeError):
                        pass

        # Also populate from POST data for fields that might not be in cleaned_data
        # This ensures we get all the data even if validation fails
        for field_name in form.fields:
            if field_name in request.POST:
                value = request.POST[field_name]
                # Only set if value is not empty and field is not already set
                if value and (
                    not hasattr(missive, field_name)
                    or getattr(missive, field_name, None) is None
                ):
                    try:
                        # Use the form field's widget to extract the value from POST
                        # This handles special fields like PhoneNumberField correctly
                        field = form.fields[field_name]
                        if hasattr(field, "widget") and hasattr(
                            field.widget, "value_from_datadict"
                        ):
                            widget_value = field.widget.value_from_datadict(
                                request.POST, None, field_name
                            )
                            if widget_value:
                                # Try to clean the value using the field
                                try:
                                    cleaned_value = field.clean(widget_value)
                                    setattr(missive, field_name, cleaned_value)
                                except (ValueError, TypeError):
                                    # If cleaning fails, set the raw widget value
                                    setattr(missive, field_name, widget_value)
                        else:
                            # Fallback: try to clean the value directly
                            try:
                                cleaned_value = field.clean(value)
                                setattr(missive, field_name, cleaned_value)
                            except (ValueError, TypeError, AttributeError):
                                # If cleaning fails, set the raw value
                                setattr(missive, field_name, value)
                    except (ValueError, TypeError, AttributeError):
                        # If all else fails, try to set the raw value
                        try:
                            setattr(missive, field_name, value)
                        except (ValueError, TypeError):
                            pass

    missive_type = getattr(missive, "missive_type", None) or request.POST.get(
        "missive_type"
    )
    if missive_type:
        missive.missive_type = missive_type
    missive_type_key = (missive_type or "").lower()
    template_name = TEMPLATE_MAP.get(missive_type_key, "django_pymissive/base_preview.html")

    context = {
        "missive": missive,
        "title": _("Preview: {}").format(missive_type or "Missive"),
    }
    if "email_preview" in template_name or "email" in template_name:
        context.update(_email_preview_context(missive))

    return TemplateResponse(
        request,
        template_name,
        context,
    )
