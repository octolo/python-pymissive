"""Forms for webhook admin views."""

from django import forms
from django.utils.translation import gettext_lazy as _

from ..models.missive import Missive


class GenerateWebhookSecretForm(forms.Form):
    """Pick a provider to seed a webhook secret with Django SECRET_KEY."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"] = Missive._meta.get_field("provider").formfield(
            required=True,
            label=_("Provider"),
        )
        self.order_fields(["provider"])
