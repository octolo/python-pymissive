"""Forms for missive event admin views."""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from ..models.missive import Missive
from ._fields import model_formfield


class RetrieveEventsForm(forms.Form):
    """Retrieve provider events between two dates."""

    start_date = forms.DateField(
        required=True,
        label=_("Start date"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        required=True,
        label=_("End date"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    as_task = forms.BooleanField(
        required=False,
        label=_("Run as task"),
        help_text=_("Launch via the configured task backend"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"] = model_formfield(
            Missive,
            "provider",
            required=True,
            label=_("Provider"),
        )
        self.fields["missive_type"] = model_formfield(
            Missive,
            "missive_type",
            required=True,
            label=_("Missive type"),
        )
        self.order_fields(["provider", "missive_type", "start_date", "end_date", "as_task"])

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        if start_date and end_date and end_date < start_date:
            raise ValidationError(_("End date must be on or after start date."))
        return cleaned
