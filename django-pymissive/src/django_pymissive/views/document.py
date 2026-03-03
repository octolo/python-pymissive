from django.shortcuts import redirect
from django.views.generic import DetailView
from django.http import FileResponse, HttpResponse

from ..models.document import CampaignDocument, MissiveDocument


class BaseDocumentDownloadView(DetailView):
    """Base view for downloading a document by id."""

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
        response = HttpResponse(
            content,
            content_type="application/octet-stream",
        )
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response

    def get(self, request, *args, **kwargs):
        """Handle GET request."""
        doc_obj = self.get_object()
        doc = doc_obj.get_document()
        return self._build_response(doc_obj, doc)


class MissiveDocumentDownloadView(BaseDocumentDownloadView):
    """Download a missive document by id."""

    model = MissiveDocument


class CampaignDocumentDownloadView(BaseDocumentDownloadView):
    """Download a campaign document by id."""

    model = CampaignDocument
