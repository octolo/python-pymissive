from django.utils import timezone

from ..models.scheduler import MissiveScheduledCampaign


def run_campaign(campaign_id):
    # Fetch by id only; run_with_tracking() performs the atomic send_date
    # claim and returns early if the run was already started by another worker.
    scheduled = MissiveScheduledCampaign.objects.get(id=campaign_id)
    scheduled.run_with_tracking()
