import django_rq
from .base import BaseCampaignBackend
from .campaign import run_campaign


class RQBackend(BaseCampaignBackend):
    def delay(self, campaign_id: int):
        queue = django_rq.get_queue("default")
        queue.enqueue(run_campaign, campaign_id)
