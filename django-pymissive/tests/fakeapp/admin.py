from django import forms
from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import redirect
from django.urls import reverse
from django_boosted import AdminBoostModel, admin_boost_view

from django_pymissive.managers.related_object import object_id_value
from django_pymissive.models import MissiveCampaign
from django_pymissive.services import (
    CampaignAlreadySending,
    select,
    selection_qs,
    start_selection,
    unselect,
)

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


_CONTACT_CHOICES = (
    ("all", "All"),
    ("first", "First"),
    ("partial", "Partial"),
)


def _selection_form(selected_names, *, remove):
    """Admin form shown after the changelist action.

    A new class each time so the disabled contact list stays on the field
    when django-boosted rebinds the form from its class on POST.
    """

    class SelectionForm(forms.Form):
        selected = forms.CharField(
            label="Selected",
            required=False,
            disabled=True,
            initial=selected_names,
        )
        campaign = forms.ModelChoiceField(queryset=MissiveCampaign.objects.order_by("-created_at"))
        missive_type = forms.ChoiceField(choices=_CHANNELS, label="Channel")
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
            label="Send this channel now",
            help_text=(
                "After updating the checkboxes, send every target still checked "
                "on this channel. Uses the fake provider (no network)."
            ),
        )

    if remove:
        del SelectionForm.base_fields["contacts"]
        del SelectionForm.base_fields["send_now"]
    return SelectionForm


def _contacts_from_request(request):
    raw = request.GET.get("ids") or ""
    pks = [int(part) for part in raw.split(",") if part.strip().isdigit()]
    if not pks:
        return CampaignContact.objects.none()
    return CampaignContact.objects.filter(pk__in=pks)


def _redirect_to_selection(queryset, view_name):
    ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
    url = reverse(f"admin:fakeapp_campaigncontact_{view_name}")
    return redirect(f"{url}?ids={ids}")


def _sync_checked(campaign, channel, queryset, mode):
    """Store the chosen slice of the channel (``emails``, ``phones``, …)."""
    from django_pymissive.processors.build_target import default_recipient_type

    targets = list(queryset)
    if not targets:
        return
    content_type = ContentType.objects.get_for_model(targets[0])
    rows = selection_qs(campaign, missive_type=channel, active_only=True).filter(
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
        campaign = form.cleaned_data["campaign"]
        channel = form.cleaned_data["missive_type"]
        if remove:
            count = unselect(campaign, channel, contacts)
            verb = "unchecked"
        else:
            count = select(campaign, channel, contacts)
            _sync_checked(campaign, channel, contacts, form.cleaned_data["contacts"])
            verb = "selected"
        self.message_user(
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
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                self.message_user(request, f'Send finished for "{campaign}" ({channel}).')
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
