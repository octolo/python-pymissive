"""Admin for MissiveAttachment model."""

from django.contrib import admin

from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel

from ..models.document import (
    MissiveAttachment,
    MissiveDocument,
    MissiveVirtualAttachment,
)


class MissiveAttachmentInline(admin.TabularInline):
    """Inline for missive documents."""

    model = MissiveAttachment
    extra = 0
    fields = [
        "order",
        "document",
        "linked",
    ]


class MissiveVirtualAttachmentInline(admin.TabularInline):
    """Inline for missive virtual documents."""

    model = MissiveVirtualAttachment
    extra = 0
    fields = [
        "order",
        "document_content_type",
        "document_object_id",
        "document_object_arguments",
        "linked",
    ]


@admin.register(MissiveDocument)
class MissiveDocumentAdmin(AdminBoostModel):
    """Admin for missive document model."""

    list_display = [
        "id",
        "document_type",
        "missive",
        "order",
    ]
    list_filter = [
        "missive__missive_type",
    ]
    search_fields = [
        "missive__subject",
        "missive__recipient_name",
    ]
    readonly_fields = [
        "document_object",
    ]
    raw_id_fields = ["missive", "document_content_type"]

    fieldsets = [
        (
            None,
            {
                "fields": (
                    "missive",
                    "order",
                    "document",
                    "document_metadata",
                    "linked",
                )
            },
        ),
    ]

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            _("Document Object"),
            [
                "document_content_type",
                "document_object_id",
                "document_object_arguments",
                "document_object",
            ],
        )
