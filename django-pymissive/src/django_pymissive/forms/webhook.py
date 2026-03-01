"""Webhook form for django-missive."""

from django import forms
from django.utils.translation import gettext_lazy as _

from ..models.webhook import MissiveWebhook
from ..models.provider import MissiveProviderModel


class WebhookForm(forms.ModelForm):
    """Form for creating/editing webhooks."""

    url = forms.URLField(
        label=_("URL"), help_text="https://[BASE_DOMAIN]/webhook/provider/"
    )

    class Meta:
        model = MissiveWebhook
        fields = ["provider", "type", "url"]

    def save(self, commit=True):
        provider = self.cleaned_data.get("provider")
        provider = MissiveProviderModel.objects.get(name=provider)
        url = self.cleaned_data.get("url")
        service = f"set_webhook_{self.cleaned_data.get('type')}".lower()
        return getattr(provider._provider, service)(url)
