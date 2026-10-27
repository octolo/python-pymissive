"""Forms for missive admin views."""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from ..models.missive import Missive
from ._fields import model_formfield


class RetrieveMissiveForm(forms.Form):
    """Retrieve or open a missive from a provider partner ID or internal UID."""

    partner_id = forms.CharField(
        required=False,
        label=_("Partner ID"),
        help_text=_("Provider external identifier (external_id)"),
    )
    uid = forms.CharField(
        required=False,
        label=_("Internal ID"),
        help_text=_("Internal missive UUID, or substitute/custom ID from another system"),
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
        self.order_fields(
            [
                "provider",
                "missive_type",
                "partner_id",
                "uid",
            ]
        )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        partner_id = (cleaned.get("partner_id") or "").strip() or None
        uid = (cleaned.get("uid") or "").strip() or None
        cleaned["uid"] = uid
        if not partner_id and not uid:
            raise ValidationError(_("Provide a partner ID or an internal ID."))
        cleaned["partner_id"] = partner_id
        return cleaned
