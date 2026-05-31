"""Admin for MissiveConfig."""

from django.contrib import admin
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel
from django_boosted.decorators import admin_boost_action, admin_boost_view

from ..models.config import MissiveConfig


@admin.register(MissiveConfig)
class MissiveConfigAdmin(AdminBoostModel):
    list_display = ["missive_type", "default_provider"]
    list_editable = ["default_provider"]
    ordering = ["missive_type"]

    def has_sync_provider_permission(self, request, obj=None):
        """Show the sync button only when a default provider is configured."""
        return bool(obj and obj.pk and obj.default_provider)

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
        return redirect(
            reverse("admin:django_pymissive_missiveconfig_change", args=[obj.pk])
        )
