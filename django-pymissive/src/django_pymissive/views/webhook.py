"""Webhook view for receiving provider events."""

import logging

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView

from ..events import handle_events
from ..models.provider import MissiveProviderModel

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
        try:
            provider = self.get_object()
        except ObjectDoesNotExist as exc:
            # The provider queryset is virtual and raises the base
            # ObjectDoesNotExist, which DetailView does not turn into a 404 —
            # an unknown provider name in the URL would answer 500.
            raise Http404("Unknown provider") from exc
        missive_type = kwargs.get("missive_type")
        try:
            lost = handle_events(
                request.body, provider=provider, missive_type=missive_type
            )
        except Exception as e:
            # Normalization failed: the body is not something this provider can
            # read, and no retry will change that. 400 instead of 500 so the
            # provider stops resending it.
            logger.error(f"Error handling webhook: {e}", exc_info=True)
            return HttpResponse(status=400)
        if lost:
            # Ask for a retry. Ingestion is idempotent (``_upsert_event`` keys on
            # missive + event + occurred_at), so redelivering the whole batch
            # does not duplicate the events that did go through.
            logger.warning("Webhook: %s event(s) lost, asking for a retry", lost)
            return HttpResponse(status=503)
        return HttpResponse(status=200)
