"""Forms for webhook admin views."""

from django import forms
from django.utils.translation import gettext_lazy as _

from ..models.missive import Missive


class GenerateWebhookSecretForm(forms.Form):
    """Pick a provider and type to seed a webhook secret with Django SECRET_KEY."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"] = Missive._meta.get_field("provider").formfield(
            required=True,
            label=_("Provider"),
        )
        self.fields["missive_type"] = Missive._meta.get_field("missive_type").formfield(
            required=True,
            label=_("Missive type"),
        )
        self.fields["salt"] = forms.CharField(
            required=False,
            label=_("Salt"),
            help_text=_("Optional. Change it to mint a new token."),
        )
        self.fields["secret"] = forms.CharField(
            required=False,
            label=_("Webhook secret"),
            help_text=_(
                "Copy into WEBHOOK_SECRET for this provider, then re-create "
                "the webhook."
            ),
        )
        self.fields["webhook_url"] = forms.CharField(
            required=False,
            label=_("Webhook URL"),
            help_text=_("For providers that send Authorization (Brevo, Maileva)."),
        )
        self.fields["webhook_url_token"] = forms.CharField(
            required=False,
            label=_("Webhook URL with token"),
            help_text=_(
                "For providers that cannot set headers (Scaleway, SMS Partner)."
            ),
        )
        self.order_fields(
            [
                "provider",
                "missive_type",
                "salt",
                "secret",
                "webhook_url",
                "webhook_url_token",
            ]
        )
