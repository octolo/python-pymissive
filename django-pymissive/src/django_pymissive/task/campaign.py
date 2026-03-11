from django.utils import timezone

from ..models.campaign import MissiveScheduledCampaign


def run_campaign(campaign_id):
    scheduled = MissiveScheduledCampaign.objects.get(
        id=campaign_id, send_date__isnull=True
    )
    scheduled.send_date = timezone.now()
    scheduled.save()
    scheduled.run_campaign()
    scheduled.ended_at = timezone.now()
    scheduled.save()
