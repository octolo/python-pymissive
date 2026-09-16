"""Admin for webhook model."""

from urllib.parse import unquote

from django.conf import settings
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel
from django_boosted.decorators import admin_boost_view

from pymissive.config import provider_service_name
from pymissive.webhook_secret import generate_webhook_secret as make_webhook_secret

from ..forms.webhook import GenerateWebhookSecretForm
from ..models.webhook import MissiveWebhook
from ..utils import build_webhook_url, get_base_url
from .permissions import ActionRightsMixin


def _admin_secret_extra(salt: str) -> str:
    """SECRET_KEY plus optional salt so staff can rotate the token."""
    extra = settings.SECRET_KEY
    salt = (salt or "").strip()
    if salt:
        extra = f"{extra}\n{salt}"
    return extra


def _generated_webhook_urls(provider_name: str, missive_type: str, token: str) -> tuple[str, str]:
    """Plain callback URL and the same path with the secret as last segment."""
    base = get_base_url(trailing_slash=False)
    return (
        build_webhook_url(base, provider_name, missive_type),
        build_webhook_url(base, provider_name, missive_type, token=token),
    )


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

    def _provider_has_webhook_service(self, obj, service: str) -> bool:
        try:
            service_name = provider_service_name(service, obj.type)
        except ValueError:
            return False
        provider = obj.get_provider()
        inner = getattr(provider, "_provider", None)
        return bool(inner) and hasattr(inner, service_name)

    def has_change_permission(self, request, obj=None):
        if obj:
            return self._provider_has_webhook_service(obj, "update_webhook")
        return False

    def has_delete_permission(self, request, obj=None):
        if obj:
            return self._provider_has_webhook_service(obj, "delete_webhook")
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
        payload = {
            "save_label": _("Generate"),
            "has_change_permission": True,
            "readonly_fields": ["secret", "webhook_url", "webhook_url_token"],
        }
        if form is None:
            return {**payload, "form": GenerateWebhookSecretForm()}
        provider = str(form.cleaned_data["provider"])
        missive_type = str(form.cleaned_data["missive_type"])
        salt = str(form.cleaned_data.get("salt") or "").strip()
        token = make_webhook_secret(provider, _admin_secret_extra(salt))
        url, url_token = _generated_webhook_urls(provider, missive_type, token)
        return {
            **payload,
            "form": GenerateWebhookSecretForm(
                initial={
                    "provider": provider,
                    "missive_type": missive_type,
                    "salt": salt,
                    "secret": token,
                    "webhook_url": url,
                    "webhook_url_token": url_token,
                }
            ),
        }
