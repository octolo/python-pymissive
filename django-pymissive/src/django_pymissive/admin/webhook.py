"""Admin for webhook model."""

from urllib.parse import unquote

from django import forms
from django.conf import settings
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel
from django_boosted.decorators import admin_boost_view

from pymissive.webhook_secret import generate_webhook_secret as make_webhook_secret

from ..forms.webhook import GenerateWebhookSecretForm
from ..models.webhook import MissiveWebhook
from .permissions import ActionRightsMixin


def _webhook_provider_name(webhook) -> str:
    name = getattr(webhook, "provider_name", None)
    if name:
        return str(name)
    provider = getattr(webhook, "provider", None)
    return getattr(provider, "name", None) or str(provider or "")


class ProviderListFilter(admin.SimpleListFilter):
    """Filter virtual webhooks by provider name."""

    title = _("Provider")
    parameter_name = "provider"

    def lookups(self, request, _model_admin):
        """Return list of providers as filter options."""
        try:
            provider_field = MissiveWebhook._meta.get_field("provider")
            choices = provider_field.get_provider_choices()
            return [choice for choice in choices if choice[0]]
        except Exception:
            return []

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        rows = getattr(queryset, "_result_cache", None)
        if rows is None:
            rows = list(queryset)
        kept = [obj for obj in rows if _webhook_provider_name(obj) == value]
        return queryset.model.objects.queryset_class(
            model=queryset.model, data=kept
        )


@admin.register(MissiveWebhook)
class MissiveWebhookAdmin(ActionRightsMixin, AdminBoostModel):
    """Admin for missive webhooks."""

    list_display = [
        "id",
        "provider",
        "type",
        "url",
        "created_at",
        "updated_at",
    ]
    list_filter = [ProviderListFilter, "type"]
    search_fields = [
        "url",
        "description",
    ]
    readonly_fields = ["id", "webhook_id", "url", "created_at", "updated_at"]

    def log_addition(self, request, _obj, _message):
        pass

    def log_change(self, request, _obj, _message):
        pass

    def log_deletion(self, request, _obj, _object_repr):
        pass

    def has_add_permission(self, request):
        return True

    def has_change_permission(self, request, obj=None):
        if obj:
            provider = obj.get_provider()
            return hasattr(provider._provider, f"update_webhook_{obj.type}")
        return False

    def has_delete_permission(self, request, obj=None):
        if obj:
            provider = obj.get_provider()
            return hasattr(provider._provider, f"delete_webhook_{obj.type}")
        return False

    def has_action_rights(self, request, obj=None) -> bool:
        # Change is denied on the changelist (virtual rows). Generating a
        # secret is a staff action, not an update of a subscription.
        return admin.ModelAdmin.has_view_permission(self, request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            readonly = list(self.readonly_fields)
            return readonly + ["provider"]
        return self.readonly_fields

    def change_fieldsets(self):
        self.add_to_fieldset(
            None,
            [
                "provider",
                "type",
                "scheme",
                "domain",
            ],
        )
        self.add_to_fieldset(_("Infos"), ["webhook_id", "url", "created_at", "updated_at"])

    def get_object(self, request, object_id, _from_field=None):
        webhook_id = unquote(object_id)
        provider = webhook_id.split("-")[0]
        qs = self.model.objects.get_queryset(provider)
        return next(
            (item for item in qs if str(item.webhook_id) == str(webhook_id)), None
        )

    def get_queryset(self, request):
        provider = request.GET.get(ProviderListFilter.parameter_name)
        if provider:
            return self.model.objects.get_queryset(provider)
        return self.model.objects.all_providers()

    def has_generate_webhook_secret_permission(self, request, obj=None):
        return self.has_action_rights(request, obj)

    @admin_boost_view(
        "adminform", _("Generate webhook secret"), requires_object=False
    )
    def generate_webhook_secret(self, request, form=None):
        """Show a secret seeded by provider name, UTC date, and SECRET_KEY."""
        self.require_action_rights(request)
        if form is None:
            return {
                "form": GenerateWebhookSecretForm(),
                "save_label": _("Generate"),
                "has_change_permission": True,
            }
        provider = str(form.cleaned_data["provider"])
        token = make_webhook_secret(provider, settings.SECRET_KEY)
        result = GenerateWebhookSecretForm(initial={"provider": provider})
        result.fields["secret"] = forms.CharField(
            initial=token,
            label=_("Webhook secret"),
            help_text=_(
                "Copy into WEBHOOK_SECRET for this provider, then re-create "
                "the webhook."
            ),
            widget=forms.TextInput(
                attrs={"readonly": "readonly", "style": "font-family:monospace"}
            ),
        )
        result.order_fields(["provider", "secret"])
        return {
            "form": result,
            "save_label": _("Generate"),
            "has_change_permission": True,
        }
