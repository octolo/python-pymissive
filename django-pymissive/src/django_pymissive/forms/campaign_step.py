from django import forms
from django.utils.translation import gettext_lazy as _

from ..models.campaign_step import CampaignStep
from ..models.choices import MissiveType


class CampaignStepForm(forms.ModelForm):
    class Meta:
        model = CampaignStep
        fields = "__all__"


class CampaignStepTypeForm(forms.Form):
    missive_type = forms.ChoiceField(
        choices=MissiveType.choices,
        label=_("Missive type"),
        help_text=_("Choose the type of campaign step to add."),
    )
