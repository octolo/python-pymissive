"""Admin for MissiveAttachment model."""

from django.contrib import admin

from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel

from ..models.attachment import (
    MissiveBaseAttachment,
    MissiveAttachment,
    MissiveVirtualAttachment,
    CampaignAttachment,
    CampaignVirtualAttachment
)


@admin.register(MissiveBaseAttachment)
class MissiveAttachmentAdmin(AdminBoostModel):
    """Admin for missive attachment model."""

    list_display = [
        "id",
        "attachment_type",
        "missive",
        "priority",
    ]
    list_filter = [
        "missive__missive_type",
    ]
    search_fields = [
        "missive__subject",
        "missive__recipient_name",
        "campaign__name",
    ]
    readonly_fields = [
        "attachment_object",
        "created_at",
        "updated_at",
    ]
    raw_id_fields = ["missive", "campaign",]

    fieldsets = [
        (
            None,
            {
                "fields": (
                    "campaign",
                    "missive",
                    "priority",
                    "attachment_file",
                    "external_id",
                    "page_count",
                    "linked",
                )
            },
        ),
    ]

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            _("Attachment Object"),
            [
                "attachment_content_type",
                "attachment_object_id",
                "attachment_object_arguments",
                "attachment_object",
            ],
        )
        self.add_to_fieldset(_("Comment/Timestamps"), ["comment", "created_at", "updated_at"])
        self.add_to_fieldset(_("Configs"), ["metadata"])


class MissiveAttachmentInline(admin.TabularInline):
    """Inline for missive attachments."""

    model = MissiveAttachment
    extra = 0
    fields = [
        "priority",
        "attachment_file",
        "external_id",
        "page_count",
        "linked",
    ]


class MissiveVirtualAttachmentInline(admin.TabularInline):
    """Inline for missive virtual attachments."""

    model = MissiveVirtualAttachment
    extra = 0
    fields = [
        "priority",
        "attachment_content_type",
        "attachment_object_id",
        "attachment_object_arguments",
        "external_id",
        "page_count",
        "linked",
    ]


class CampaignAttachmentInline(admin.TabularInline):
    """Inline for campaign attachments."""

    model = CampaignAttachment
    extra = 0
    fields = [
        "priority",
        "attachment_file",
        "external_id",
        "page_count",
        "linked",
    ]


class CampaignVirtualAttachmentInline(admin.TabularInline):
    """Inline for campaign virtual attachments."""

    model = CampaignVirtualAttachment
    extra = 0
    fields = [
        "priority",
        "attachment_content_type",
        "attachment_object_id",
        "attachment_object_arguments",
        "external_id",
        "page_count",
        "linked",
    ]