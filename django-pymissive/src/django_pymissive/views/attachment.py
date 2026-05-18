import logging

from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect
from django.views.generic import DetailView

from ..models.attachment import MissiveBaseAttachment

logger = logging.getLogger(__name__)

_ATTACHMENT_QUERYSETS = {
    "missive": MissiveBaseAttachment.objects.filter(missive__isnull=False, campaign__isnull=True),
    "campaign": MissiveBaseAttachment.objects.filter(campaign__isnull=False, missive__isnull=True),
}


class MissiveAttachmentDownloadView(DetailView):
    """Download an attachment by id, scoped to missive or campaign.

    The downloaded bytes go through the same ``attachment_processors``
    chain as the bytes sent to the provider, so the in-browser preview
    matches what the recipient eventually receives (watermark, signature,
    etc.). Skip the chain by passing ``?raw=1`` for legal/audit needs.
    """

    model = MissiveBaseAttachment

    def get_queryset(self):
        key = self.kwargs.get("campaign_or_missive", "")
        qs = _ATTACHMENT_QUERYSETS.get(key)
        if qs is None:
            raise Http404
        return qs

    def _content_disposition(self, attachment_obj, attachment):
        """Pick a filename for the Content-Disposition header."""
        if hasattr(attachment, "name") and attachment.name:
            return attachment.name.split("/")[-1] or "unnamed_attachment"
        if isinstance(attachment, dict):
            return attachment.get("name") or "unnamed_attachment"
        return (getattr(attachment_obj, "metadata", None) or {}).get(
            "name", "unnamed_attachment"
        )

    def _processed_content(self, attachment_obj, attachment) -> bytes | None:
        """Read the attachment bytes and run them through the processor chain.

        Works for both Django ``FieldFile`` instances (regular attachments)
        and plain Python file handles returned by virtual attachment
        helpers (e.g. ``open(path, "rb")`` / ``Path.open("rb")``). Returns
        ``None`` when ``attachment`` is not a readable file-like object
        (e.g. a dict with a redirect URL); callers should fall back to
        the legacy code path in that case.
        """
        if not hasattr(attachment, "read"):
            return None
        try:
            if hasattr(attachment, "seek"):
                try:
                    attachment.seek(0)
                except (OSError, ValueError):
                    pass
            content_bytes = attachment.read()
        finally:
            try:
                attachment.close()
            except Exception:
                pass
        if not content_bytes:
            return content_bytes
        try:
            return attachment_obj._apply_attachment_processors(content_bytes)
        except Exception as exc:
            logger.warning(
                "attachment processor chain failed for attachment %s: %s",
                attachment_obj.pk,
                exc,
            )
            return content_bytes

    def get(self, request, *args, **kwargs):
        attachment_obj = self.get_object()
        attachment = attachment_obj.get_attachment()
        skip_processors = request.GET.get("raw") in {"1", "true", "yes"}

        if not skip_processors:
            content = self._processed_content(attachment_obj, attachment)
            if content is not None:
                name = self._content_disposition(attachment_obj, attachment)
                ctype = getattr(attachment_obj, "mime_type", "") or "application/octet-stream"
                response = HttpResponse(content, content_type=ctype)
                response["Content-Disposition"] = f'attachment; filename="{name}"'
                return response

        if hasattr(attachment, "read") and hasattr(attachment, "name"):
            # Django FieldFile exposes open(); plain file handles (returned
            # by virtual attachment helpers) don't — they're already open
            # and only need a rewind via seek(0).
            if hasattr(attachment, "open") and callable(getattr(attachment, "open")):
                try:
                    attachment.open("rb")
                except (TypeError, ValueError):
                    pass
            elif hasattr(attachment, "seek"):
                try:
                    attachment.seek(0)
                except (OSError, ValueError):
                    pass
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
