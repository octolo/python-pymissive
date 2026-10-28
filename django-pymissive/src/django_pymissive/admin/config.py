"""Admin for MissiveConfig."""

from django.contrib import admin
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel  # type: ignore[import-untyped]
from django_boosted.decorators import admin_boost_action, admin_boost_view  # type: ignore[import-untyped]

from ..models.config import (
    MissiveConfig,
    load_typed_default_providers,
    typed_default_provider_changes,
    typed_default_providers,
)
from ..models.setting import MissiveSetting
from .permissions import ActionRightsMixin


def _describe_change(missive_type, current, provider):
    if current is None:
        return str(format_lazy(_("{type} → {new} (new)"), type=missive_type, new=provider))
    return str(
        format_lazy(
            _("{type}: {old} → {new} (replaced)"),
            type=missive_type,
            old=current or "-",
            new=provider,
        )
    )


@admin.register(MissiveConfig)
class MissiveConfigAdmin(ActionRightsMixin, AdminBoostModel):
    list_display = ["missive_type", "default_provider"]
    list_display_links = ["missive_type"]
    list_editable = ["default_provider"]
    ordering = ["missive_type"]

    def has_sync_provider_permission(self, request, obj=None):
        """Show the sync button only when a default provider is configured."""
        return bool(self.has_action_rights(request, obj) and obj and obj.pk and obj.default_provider)

    @admin_boost_action("sync_provider", _("Sync provider"))
    def handle_sync_provider(self, request, object_id):
        from django.contrib.admin.utils import unquote

        object_id = unquote(object_id)
        return redirect(
            reverse(
                "admin:django_pymissive_missiveconfig_sync_provider",
                args=[object_id],
            )
        )

    @admin_boost_view("confirm", _("Sync provider"), hidden=True)
    def sync_provider(self, request, obj, confirmed=False):
        from ..models.missive import Missive

        if not confirmed:
            count = Missive.objects.filter(
                missive_type=obj.missive_type,
                provider="",
            ).count()
            return {
                "confirm": format_lazy(
                    _(
                        "Assign provider «{provider}» to {count} missive(s) of type "
                        "«{missive_type}» that currently have no provider set?"
                    ),
                    provider=obj.default_provider,
                    count=count,
                    missive_type=obj.get_missive_type_display(),
                ),
            }

        updated = Missive.objects.filter(
            missive_type=obj.missive_type,
            provider="",
        ).update(provider=obj.default_provider)

        messages.success(
            request,
            format_lazy(
                _("{count} missive(s) updated with provider «{provider}»."),
                count=updated,
                provider=obj.default_provider,
            ),
        )
        return redirect(reverse("admin:django_pymissive_missiveconfig_change", args=[obj.pk]))

    @admin_boost_view("confirm", _("Load providers"), requires_object=False)
    def load_providers(self, request, confirmed=False):
        """Create or replace a config row for each per-type entry in the setting.

        The confirmation lists every row about to change, with the value a
        replacement overwrites. Rows already matching the setting are left alone.
        """
        self.require_action_rights(request)
        if not confirmed:
            if not typed_default_providers():
                message = _(
                    "PYMISSIVE_DEFAULT_PROVIDER has no per-type provider to load. "
                    "A plain string is the fallback and is not written here."
                )
            else:
                changes, _unchanged = typed_default_provider_changes()
                if not changes:
                    message = _("Every configuration already matches PYMISSIVE_DEFAULT_PROVIDER.")
                else:
                    message = format_lazy(
                        _("Apply these changes? {changes}"),
                        changes=", ".join(
                            _describe_change(missive_type, current, provider)
                            for missive_type, current, provider in changes
                        ),
                    )
            return {"confirm": message}
        created, replaced, unchanged = load_typed_default_providers()
        messages.success(
            request,
            format_lazy(
                _("{created} configuration(s) created, {replaced} replaced, {unchanged} unchanged."),
                created=created,
                replaced=replaced,
                unchanged=unchanged,
            ),
        )
        return redirect(reverse("admin:django_pymissive_missiveconfig_changelist"))

    @admin.display(description=_("Setting"))
    def setting_name(self, obj):
        return format_html("<strong>{}</strong>", obj.name)

    @admin.display(description=_("Default"))
    def setting_default(self, obj):
        return format_html('<span style="color: var(--secondary)">{}</span>', obj.default_value)

    @admin.display(description=_("Configured"))
    def setting_configured(self, obj):
        if not obj.configured_value:
            return ""
        return format_html('<span style="color: #fff">{}</span>', obj.configured_value)

    @admin_boost_view("list", _("Settings"), requires_object=False)
    def show_settings(self, request):
        """Read-only list of every setting this package reads."""
        return {
            "queryset": MissiveSetting.objects.all(),
            "list_display": ["setting_name", "setting_default", "setting_configured"],
        }
