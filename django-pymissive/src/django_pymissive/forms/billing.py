"""Forms for missive billing admin views."""

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from ..models.missive import Missive


def _is_related_export_path(path: str) -> bool:
    parts = str(path).split(".")
    if len(parts) < 2:
        return False
    return all(
        part.isidentifier() and not part.startswith("_") and "__" not in part
        for part in parts
    )


class BillingDateRangeForm(forms.Form):
    """Start/end dates shared by billing admin forms."""

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

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        if start_date and end_date and end_date < start_date:
            raise ValidationError(_("End date must be on or after start date."))
        return cleaned


class BillingFilterForm(BillingDateRangeForm):
    """Date range with optional provider / missive type filters."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"] = Missive._meta.get_field("provider").formfield(
            required=False,
            label=_("Provider"),
        )
        self.fields["missive_type"] = Missive._meta.get_field("missive_type").formfield(
            required=False,
            label=_("Missive type"),
        )
        self.order_fields(
            ["provider", "missive_type", "start_date", "end_date"]
        )


class RetrieveBillingsForm(BillingDateRangeForm):
    """Retrieve provider billings between two dates."""

    as_task = forms.BooleanField(
        required=False,
        label=_("Run as task"),
        help_text=_("Launch via the configured task backend"),
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
        self.order_fields(
            ["provider", "missive_type", "start_date", "end_date", "as_task"]
        )


class ExportBillingsForm(BillingFilterForm):
    """Export stored billings between two dates as CSV."""

    fields = forms.JSONField(
        required=False,
        label=_("Fields"),
        help_text=_(
            'Dotted paths on missive related objects, e.g. ["contact.last_name", "contact.category.name"]. Multiple related objects become columns path.1, path.2, ….'
        ),
        initial=[],
    )
    one_row = forms.BooleanField(
        required=False,
        label=_("One row per missive"),
        help_text=_(
            "Turn billing labels into columns; the cell value is the billed amount."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        widget_path = getattr(settings, "PYMISSIVE_JSON_WIDGET", None)
        if widget_path:
            self.fields["fields"].widget = import_string(widget_path)()
        self.order_fields(
            ["provider", "missive_type", "start_date", "end_date", "one_row", "fields"]
        )

    def clean_fields(self):
        value = self.cleaned_data.get("fields")
        if value in (None, [], {}):
            return []
        if not isinstance(value, list):
            raise ValidationError(
                _("Fields must be a JSON list of dotted paths (e.g. contact.last_name).")
            )
        paths = []
        for item in value:
            if not isinstance(item, str) or not _is_related_export_path(item.strip()):
                raise ValidationError(
                    _("Invalid related-object path: %(path)s"),
                    params={"path": item},
                )
            paths.append(item.strip())
        return paths
