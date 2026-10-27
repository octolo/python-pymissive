from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django_boosted import AdminBoostModel, admin_boost_view

from django_pymissive.models import MissiveCampaign
from django_pymissive.services import CampaignAlreadySending, select, start_selection, unselect

from .generators import generate_campaign_contacts
from .models import (
    CampaignContact,
    Category,
    Contact,
    ContactAddress,
    ContactEmail,
    ContactPhone,
    PdfDocument,
)

#: Channels a CampaignContact can actually fill.
_CHANNELS = (
    ("email", "Email"),
    ("sms", "SMS"),
    ("letter", "Letter"),
)


class CampaignTargetSelectForm(forms.Form):
    """Campaign and channel for the admin selection action."""

    campaign = forms.ModelChoiceField(queryset=MissiveCampaign.objects.order_by("-created_at"))
    missive_type = forms.ChoiceField(choices=_CHANNELS, label="Channel")
    send_now = forms.BooleanField(
        required=False,
        label="Send this channel now",
        help_text=(
            "After updating the checkboxes, send every target still checked "
            "on this channel. Uses the fake provider (no network)."
        ),
    )


def _apply_selection(modeladmin, request, queryset, *, remove: bool):
    action = "unselect_from_campaign" if remove else "select_for_campaign"
    if "apply" in request.POST:
        form = CampaignTargetSelectForm(request.POST)
        if form.is_valid():
            campaign = form.cleaned_data["campaign"]
            channel = form.cleaned_data["missive_type"]
            if remove:
                count = unselect(campaign, channel, queryset)
                verb = "unchecked"
            else:
                count = select(campaign, channel, queryset)
                verb = "selected"
            modeladmin.message_user(
                request,
                f'{count} {channel} target(s) {verb} on "{campaign}".',
            )
            if not remove and form.cleaned_data["send_now"]:
                try:
                    start_selection(
                        campaign,
                        [channel],
                        build="tests.fakeapp.campaign_targets.build_campaign_contact",
                    )
                except CampaignAlreadySending as exc:
                    modeladmin.message_user(request, str(exc), level=messages.ERROR)
                else:
                    modeladmin.message_user(
                        request,
                        f'Send finished for "{campaign}" ({channel}).',
                    )
            return redirect("admin:fakeapp_campaigncontact_changelist")
    else:
        form = CampaignTargetSelectForm()
    if remove:
        form.fields.pop("send_now", None)
    return TemplateResponse(
        request,
        "admin/fakeapp/select_campaign_targets.html",
        {
            **modeladmin.admin_site.each_context(request),
            "form": form,
            "queryset": queryset,
            "opts": modeladmin.model._meta,
            "action": action,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
            "title": "Unselect from a campaign" if remove else "Select for a campaign",
        },
    )


@admin.action(description="Select for a campaign")
def select_for_campaign(modeladmin, request, queryset):
    return _apply_selection(modeladmin, request, queryset, remove=False)


@admin.action(description="Unselect from a campaign")
def unselect_from_campaign(modeladmin, request, queryset):
    return _apply_selection(modeladmin, request, queryset, remove=True)


@admin.register(PdfDocument)
class PdfDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "fixture_path")
    search_fields = ("name", "fixture_path")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("id", "last_name", "first_name", "email", "category")
    list_filter = ("category",)
    search_fields = ("last_name", "first_name", "email")
    ordering = ("last_name", "first_name")


class ContactEmailInline(admin.TabularInline):
    model = ContactEmail
    extra = 0


class ContactPhoneInline(admin.TabularInline):
    model = ContactPhone
    extra = 0


class ContactAddressInline(admin.TabularInline):
    model = ContactAddress
    extra = 0


class GenerateCampaignContactsForm(forms.Form):
    count = forms.IntegerField(min_value=1, max_value=1000, initial=10)
    emails = forms.IntegerField(min_value=0, max_value=10, initial=2)
    phones = forms.IntegerField(min_value=0, max_value=10, initial=2)
    addresses = forms.IntegerField(min_value=0, max_value=10, initial=2)
    seed = forms.IntegerField(required=False, help_text="Leave blank for a random draw.")


@admin.register(CampaignContact)
class CampaignContactAdmin(AdminBoostModel):
    list_display = ("id", "last_name", "first_name", "email", "phone", "address")
    search_fields = (
        "last_name",
        "first_name",
        "contact_emails__email",
        "contact_phones__phone",
    )
    ordering = ("last_name", "first_name")
    actions = (select_for_campaign, unselect_from_campaign)
    inlines = (ContactEmailInline, ContactPhoneInline, ContactAddressInline)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related(
                "contact_emails",
                "contact_phones",
                "contact_addresses",
            )
        )

    @admin_boost_view("adminform", "Generate contacts", requires_object=False)
    def generate_contacts(self, request, form=None):
        if form is None:
            return {
                "form": GenerateCampaignContactsForm(),
                "save_label": "Generate",
                "has_change_permission": True,
            }
        contacts = generate_campaign_contacts(**form.cleaned_data)
        self.message_user(request, f"{len(contacts)} campaign contact(s) generated.")
        return redirect("admin:fakeapp_campaigncontact_changelist")
