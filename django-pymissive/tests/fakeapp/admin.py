from django.contrib import admin

from .models import PdfDocument


@admin.register(PdfDocument)
class PdfDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "fixture_path")
    search_fields = ("name", "fixture_path")
