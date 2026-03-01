"""Admin for webhook model."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from ..models.webhook import MissiveWebhook
from django_boosted import AdminBoostModel
from urllib.parse import unquote


class ProviderListFilter(admin.SimpleListFilter):
    """Custom filter for provider field."""

    title = _("Provider")
    parameter_name = "provider"

    def lookups(self, request, _model_admin):
        """Return list of providers as filter options."""
        try:
            # Get the provider field from the model
            provider_field = MissiveWebhook._meta.get_field("provider")
            # Use the field's method to get choices
            choices = provider_field.get_provider_choices()
            # Remove the empty choice
            return [choice for choice in choices if choice[0]]
        except Exception:
            return []

    def queryset(self, request, queryset):
        """Filter queryset by provider."""
        return queryset


@admin.register(MissiveWebhook)
class MissiveWebhookAdmin(AdminBoostModel):
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
    readonly_fields = ["id", "webhook_id", "created_at", "updated_at"]

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
                "url",
            ],
        )
        self.add_to_fieldset(_("Infos"), ["webhook_id", "created_at", "updated_at"])

    def get_object(self, request, object_id, _from_field=None):
        webhook_id = unquote(object_id)
        provider = webhook_id.split("-")[0]
        qs = self.model.objects.get_queryset(provider)
        return next(
            (item for item in qs if str(item.webhook_id) == str(webhook_id)), None
        )

    def get_queryset(self, request):
        if provider := request.GET.get("provider"):
            return self.model.objects.get_queryset(provider)
        return self.model.objects.none()
