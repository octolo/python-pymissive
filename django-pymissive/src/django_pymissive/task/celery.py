from celery import shared_task
from .base import BaseCampaignBackend
from .campaign import run_campaign


@shared_task
def celery_campaign_task(campaign_id):
    run_campaign(campaign_id)


class CeleryBackend(BaseCampaignBackend):
    def delay(self, campaign_id: int):
        celery_campaign_task.delay(campaign_id)
