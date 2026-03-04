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

    def _build_response(self, doc_obj, doc):
        """Build HTTP response from document object and document content."""
        if hasattr(doc, "read") and hasattr(doc, "name"):
            doc.open("rb")
            name = (doc.name and doc.name.split("/")[-1]) or "unnamed_document"
            return FileResponse(doc, as_attachment=True, filename=name)
        if isinstance(doc, dict) and "url" in doc:
            return redirect(doc["url"])
        if isinstance(doc, dict) and "content" in doc:
            content = doc["content"]
            name = doc.get("name", "unnamed_document")
        else:
            content = doc
            name = (getattr(doc_obj, "document_metadata", None) or {}).get(
                "name", "unnamed_document"
            )
        response = HttpResponse(content, content_type="application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response

    def get(self, request, *args, **kwargs):
        doc_obj = self.get_object()
        doc = doc_obj.get_attachment()
        return self._build_response(doc_obj, doc)
