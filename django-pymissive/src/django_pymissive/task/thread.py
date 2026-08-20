from threading import Thread

from .base import BaseCampaignBackend
from .campaign import run_campaign


class ThreadBackend(BaseCampaignBackend):
    def delay(self, campaign_id: int):
        self.enqueue(run_campaign, campaign_id)

    def enqueue(self, func, *args, **kwargs):
        Thread(target=func, args=args, kwargs=kwargs, daemon=True).start()
