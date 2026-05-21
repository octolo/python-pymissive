from django.contrib import admin

from .models import Contact, PdfDocument


@admin.register(PdfDocument)
class PdfDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "fixture_path")
    search_fields = ("name", "fixture_path")


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("id", "last_name", "first_name", "email")
    search_fields = ("last_name", "first_name", "email")
    ordering = ("last_name", "first_name")
