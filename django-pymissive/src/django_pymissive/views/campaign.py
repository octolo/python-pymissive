"""Campaign progress view (HTML + JSON)."""

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView

from ..models.campaign import MissiveCampaign
from .scheduler import wants_json


@method_decorator(staff_member_required, name="dispatch")
class CampaignProgressView(DetailView):
    """Live campaign progress across all missives, per channel.

    HTML by default; JSON when ``?format=json`` or ``Accept: application/json``.
    The HTML page polls the JSON endpoint while the campaign is processing.
    """

    model = MissiveCampaign
    template_name = "django_pymissive/campaign_progress.html"
    context_object_name = "campaign"

    def render_to_response(self, context, **response_kwargs):
        if wants_json(self.request):
            return JsonResponse(self.object.progress_payload())
        return super().render_to_response(context, **response_kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        progress = self.object.progress_payload()
        context["progress"] = progress
        context["title"] = _("Campaign: {}").format(self.object.subject)
        context["json_url"] = f"{self.request.path}?format=json"
        return context
