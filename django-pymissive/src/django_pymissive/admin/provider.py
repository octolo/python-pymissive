"""Admin for provider model."""

from django.contrib import admin

from django_providerkit.admin.provider import BaseProviderAdmin

from ..models.provider import MissiveProviderModel


@admin.register(MissiveProviderModel)
class ProviderAdmin(BaseProviderAdmin):
    """Admin for missive providers."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
