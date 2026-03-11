"""Admin for MissiveConfig."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from ..models.config import MissiveConfig


@admin.register(MissiveConfig)
class MissiveConfigAdmin(admin.ModelAdmin):
    list_display = ["missive_type", "default_provider"]
    list_editable = ["default_provider"]
    ordering = ["missive_type"]
