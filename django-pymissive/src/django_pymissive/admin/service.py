from django_providerkit.admin.service import ProviderServiceAdmin
from django_pymissive.models.service import MissiveServiceModel
from django.contrib import admin

@admin.register(MissiveServiceModel)
class MissiveServiceAdmin(ProviderServiceAdmin):
    """Admin for missive services."""
    pass