from django import forms
from django.contrib import admin, messages
from pymissive.config import MISSIVE_TYPES, missive_support_for_type
from django.contrib.admin.widgets import FilteredSelectMultiple, ForeignKeyRawIdWidget
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import redirect
from django.urls import reverse
from django_boosted import AdminBoostModel, admin_boost_view

from django_pymissive.managers.related_object import object_id_value
from django_pymissive.models import CampaignStep, CampaignTarget, MissiveCampaign
from django_pymissive.services import (
    CampaignAlreadySending,
    select,
    selection_qs,
    start_selection,
    unselect,
)

from .generators import generate_campaign_contacts, generate_campaigns
from .models import (
    CampaignContact,
    Category,
    Contact,
    ContactAddress,
    ContactEmail,
    ContactPhone,
    PdfDocument,
)

_CONTACT_CHOICES = (
    ("all", "All"),
    ("first", "First"),
    ("partial", "Partial"),
)

#: Plural contact attribute read for a step, keyed by its support.
_SUPPORT_CONTACTS = {
    "email": "emails",
    "phone": "phones",
    "address": "addresses",
    "application": "notification_ids",
}


def _selection_form(selected_names, *, remove):
    """Admin form shown after the changelist action.

    A new class each time so the disabled contact list stays on the field
    when django-boosted rebinds the form from its class on POST.
    """

    class CampaignStepChoiceField(forms.ModelChoiceField):
        def label_from_instance(self, step):
            return f"{step.campaign} — {step.get_missive_type_display()} — {step}"

    class SelectionForm(forms.Form):
        selected = forms.CharField(
            label="Selected",
            required=False,
            disabled=True,
            initial=selected_names,
        )
        if remove:
            campaign_step = CampaignStepChoiceField(
                queryset=CampaignStep.objects.select_related("campaign").order_by(
                    "-campaign__created_at",
                    "campaign_id",
                    "position",
                ),
                label="Campaign step",
                widget=ForeignKeyRawIdWidget(
                    CampaignTarget._meta.get_field("campaign_step").remote_field,
                    admin.site,
                ),
            )
        else:
            campaign = forms.ModelChoiceField(
                queryset=MissiveCampaign.objects.order_by("-created_at"),
                label="Campaign",
                help_text="One target is created for each step a contact can receive.",
                widget=ForeignKeyRawIdWidget(
                    CampaignTarget._meta.get_field("campaign").remote_field,
                    admin.site,
                ),
            )
            contacts = forms.ChoiceField(
                choices=_CONTACT_CHOICES,
                initial="all",
                label="Contacts",
                help_text=(
                    "All stores every contact of the channel. First stores only the first. "
                    "Partial stores the first two when there are more than two."
                ),
            )
            send_now = forms.BooleanField(
                required=False,
                label="Send now",
                help_text=(
                    "After updating the checkboxes, send every target still checked "
                    "on the steps these contacts can receive. Uses the fake provider (no network)."
                ),
            )

    return SelectionForm


def _contacts_from_request(request):
    raw = request.GET.get("ids") or ""
    pks = [int(part) for part in raw.split(",") if part.strip().isdigit()]
    if not pks:
        return CampaignContact.objects.none()
    return CampaignContact.objects.filter(pk__in=pks).prefetch_related(
        "contact_emails",
        "contact_phones",
        "contact_addresses",
    )


def _redirect_to_selection(queryset, view_name):
    ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
    url = reverse(f"admin:fakeapp_campaigncontact_{view_name}")
    return redirect(f"{url}?ids={ids}")


def _contacts_for_step(contacts, step):
    """Contacts that have at least one value for this step's channel."""
    attr = _SUPPORT_CONTACTS.get(missive_support_for_type(step.missive_type))
    if not attr:
        return []
    return [contact for contact in contacts if getattr(contact, attr, None)]


def _sync_checked(campaign, campaign_step, queryset, mode):
    """Store the chosen slice of the channel (``emails``, ``phones``, …)."""
    from django_pymissive.processors.build_target import default_recipient_type

    targets = list(queryset)
    if not targets:
        return
    content_type = ContentType.objects.get_for_model(targets[0])
    channel = campaign_step.missive_type
    rows = selection_qs(
        campaign,
        missive_type=channel,
        active_only=True,
        campaign_step=campaign_step,
    ).filter(
        content_type=content_type,
        object_id__in=[object_id_value(target.pk) for target in targets],
    )
    for row in rows.with_contacts():
        values = row.sync_recipients(first=mode == "first")
        if mode != "partial" or len(values) <= 2:
            continue
        stored = row.to_campaignrecipienttarget.get(recipient_type=default_recipient_type(channel))
        stored.values = values[:2]
        stored.save(update_fields=["values"])


@admin.action(description="Select for a campaign")
def select_for_campaign(modeladmin, request, queryset):
    return _redirect_to_selection(queryset, "select_campaign")


@admin.action(description="Unselect from a campaign")
def unselect_from_campaign(modeladmin, request, queryset):
    return _redirect_to_selection(queryset, "unselect_campaign")


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


class GenerateCampaignsForm(forms.Form):
    count = forms.IntegerField(min_value=1, max_value=20, initial=1)
    missive_types = forms.MultipleChoiceField(
        choices=tuple(MISSIVE_TYPES.items()),
        initial=tuple(MISSIVE_TYPES),
        widget=FilteredSelectMultiple("missive types", is_stacked=False),
        label="Missive types",
        help_text="One step is created for every selected type, with text suited to that channel.",
    )
    seed = forms.IntegerField(required=False, help_text="Leave blank for a random draw.")


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

    def _campaign_selection(self, request, form, *, remove):
        contacts = list(_contacts_from_request(request))
        if not contacts:
            self.message_user(request, "Select at least one contact.", level=messages.WARNING)
            return redirect("admin:fakeapp_campaigncontact_changelist")
        if form is None:
            names = ", ".join(str(contact) for contact in contacts)
            return {
                "form": _selection_form(names, remove=remove)(),
                "save_label": "Unselect" if remove else "Select",
                "has_change_permission": True,
            }
        if remove:
            campaign_step = form.cleaned_data["campaign_step"]
            campaign = campaign_step.campaign
            channel = campaign_step.missive_type
            count = unselect(
                campaign,
                channel,
                contacts,
                campaign_step=campaign_step,
            )
            self.message_user(
                request,
                f'{count} {channel} target(s) unchecked on "{campaign}".',
            )
            return redirect("admin:fakeapp_campaigncontact_changelist")
        campaign = form.cleaned_data["campaign"]
        mode = form.cleaned_data["contacts"]
        count = 0
        channels = []
        for step in campaign.to_campaignstep.order_by("position", "pk"):
            eligible = _contacts_for_step(contacts, step)
            if not eligible:
                continue
            count += select(campaign, step.missive_type, eligible, campaign_step=step)
            _sync_checked(campaign, step, eligible, mode)
            channels.append(step.missive_type)
        self.message_user(request, f'{count} target(s) selected on "{campaign}".')
        if form.cleaned_data["send_now"] and channels:
            try:
                start_selection(
                    campaign,
                    channels,
                    build="tests.fakeapp.campaign_targets.build_campaign_contact",
                )
            except CampaignAlreadySending as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                listed = ", ".join(dict.fromkeys(channels))
                self.message_user(request, f'Send finished for "{campaign}" ({listed}).')
        return redirect("admin:fakeapp_campaigncontact_changelist")

    @admin_boost_view("adminform", "Select for a campaign", requires_object=False, hidden=True)
    def select_campaign(self, request, form=None):
        return self._campaign_selection(request, form, remove=False)

    @admin_boost_view("adminform", "Unselect from a campaign", requires_object=False, hidden=True)
    def unselect_campaign(self, request, form=None):
        return self._campaign_selection(request, form, remove=True)

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

    @admin_boost_view("adminform", "Generate campaign", requires_object=False)
    def generate_campaign(self, request, form=None):
        if form is None:
            return {
                "form": GenerateCampaignsForm(),
                "save_label": "Generate",
                "has_change_permission": True,
            }
        campaigns = generate_campaigns(**form.cleaned_data)
        self.message_user(request, f"{len(campaigns)} campaign(s) generated.")
        return redirect("admin:django_pymissive_missivecampaign_changelist")
