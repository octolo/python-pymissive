from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect
from django.views.generic import DetailView

from ..models.attachment import MissiveBaseAttachment

_ATTACHMENT_QUERYSETS = {
    "missive": MissiveBaseAttachment.objects.filter(missive__isnull=False, campaign__isnull=True),
    "campaign": MissiveBaseAttachment.objects.filter(campaign__isnull=False, missive__isnull=True),
}


class MissiveAttachmentDownloadView(DetailView):
    """Download an attachment by id, scoped to missive or campaign."""

    model = MissiveBaseAttachment

    def get_queryset(self):
        key = self.kwargs.get("campaign_or_missive", "")
        qs = _ATTACHMENT_QUERYSETS.get(key)
        if qs is None:
            raise Http404
        return qs

    def _build_response(self, attachment_obj, attachment):
        """Build HTTP response from attachment object and attachment content."""
        if hasattr(attachment, "read") and hasattr(attachment, "name"):
            attachment.open("rb")
            name = (attachment.name and attachment.name.split("/")[-1]) or "unnamed_attachment"
            return FileResponse(attachment, as_attachment=True, filename=name)
        if isinstance(attachment, dict) and "url" in attachment:
            return redirect(attachment["url"])
        if isinstance(attachment, dict) and "content" in attachment:
            content = attachment["content"]
            name = attachment.get("name", "unnamed_attachment")
        else:
            content = attachment
            name = (getattr(attachment_obj, "metadata", None) or {}).get(
                "name", "unnamed_attachment"
            )
        response = HttpResponse(content, content_type="application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response

    def get(self, request, *args, **kwargs):
        attachment_obj = self.get_object()
        attachment = attachment_obj.get_attachment()
        return self._build_response(attachment_obj, attachment)
