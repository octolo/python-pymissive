import django_rq

from .base import BaseCampaignBackend
from .campaign import run_campaign


class RQBackend(BaseCampaignBackend):
    def delay(self, campaign_id: int):
        self.enqueue(run_campaign, campaign_id)

    def enqueue(self, func, *args, **kwargs):
        queue = django_rq.get_queue("default")
        queue.enqueue(func, *args, **kwargs)
