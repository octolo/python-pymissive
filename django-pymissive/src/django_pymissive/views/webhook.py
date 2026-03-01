"""Webhook view for receiving provider events."""


from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt


from django.views.generic import DetailView

from ..task.events import handle_events
from ..models.provider import MissiveProviderModel
import logging

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class WebhookView(DetailView):
    """Webhook view based on provider model."""

    model = MissiveProviderModel
    slug_field = "name"
    slug_url_kwarg = "provider"

    def post(self, request, *args, **kwargs):
        """Handle webhook POST request."""
        return self.handle_webhook(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """Handle webhook GET request."""
        return self.handle_webhook(request, *args, **kwargs)

    def handle_webhook(self, request, *args, **kwargs):
        provider = self.get_object()
        missive_type = kwargs.get("missive_type")
        handler = f"handle_webhook_{missive_type.lower()}"
        normalized = provider._provider.call_service_formatted(handler, payload=request.body)
        if normalized is not None and normalized.get("external_id"):
            try:
                missive = handle_events([normalized])
                missive.set_last_status()
            except Exception as e:
                logger.error(f"Error handling webhook: {e}")
        return HttpResponse(status=200)
