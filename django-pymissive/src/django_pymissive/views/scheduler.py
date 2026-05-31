"""Scheduler progress view (HTML + JSON)."""

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView

from ..models.scheduler import MissiveScheduledCampaign


def wants_json(request) -> bool:
    """True when the client asks for a JSON payload instead of HTML."""
    if request.GET.get("format", "").lower() == "json":
        return True
    accept = request.META.get("HTTP_ACCEPT", "")
    return "application/json" in accept.lower()


@method_decorator(staff_member_required, name="dispatch")
class SchedulerProgressView(DetailView):
    """Live campaign-send progress, per missive type.

    HTML by default; JSON when ``?format=json`` or ``Accept: application/json``.
    The HTML page polls the JSON endpoint while the run is active.
    """

    model = MissiveScheduledCampaign
    template_name = "django_pymissive/scheduler_progress.html"
    context_object_name = "scheduler"

    def get_queryset(self):
        return MissiveScheduledCampaign.objects.select_related("campaign").with_counts()

    def render_to_response(self, context, **response_kwargs):
        if wants_json(self.request):
            return JsonResponse(self.object.progress_payload())
        return super().render_to_response(context, **response_kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        progress = self.object.progress_payload()
        context["progress"] = progress
        context["title"] = _("Campaign send: {}").format(progress["campaign_subject"])
        context["json_url"] = f"{self.request.path}?format=json"
        return context
