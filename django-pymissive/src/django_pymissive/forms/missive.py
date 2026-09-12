"""Forms for missive admin views."""

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from ..models.missive import Missive


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
        help_text=_(
            "Internal missive UUID, or substitute/custom ID from another system"
        ),
    )

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
        self.fields["acknowledgement"] = Missive._meta.get_field(
            "acknowledgement"
        ).formfield(required=False)
        self.fields["delivery_mode"] = Missive._meta.get_field("delivery_mode").formfield(
            required=False
        )
        self.fields["priority"] = Missive._meta.get_field("priority").formfield(
            required=False
        )
        self.order_fields(
            [
                "provider",
                "missive_type",
                "acknowledgement",
                "delivery_mode",
                "priority",
                "partner_id",
                "uid",
            ]
        )

    def clean(self):
        cleaned = super().clean()
        partner_id = (cleaned.get("partner_id") or "").strip() or None
        uid = (cleaned.get("uid") or "").strip() or None
        cleaned["uid"] = uid
        if not partner_id and not uid:
            raise ValidationError(_("Provide a partner ID or an internal ID."))
        cleaned["partner_id"] = partner_id
        for name in ("acknowledgement", "delivery_mode", "priority"):
            value = cleaned.get(name)
            cleaned[name] = (value or "").strip() or None
        return cleaned
