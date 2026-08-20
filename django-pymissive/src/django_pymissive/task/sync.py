from .base import BaseCampaignBackend
from .campaign import run_campaign


class SyncBackend(BaseCampaignBackend):
    def delay(self, campaign_id: int):
        self.enqueue(run_campaign, campaign_id)

    def enqueue(self, func, *args, **kwargs):
        func(*args, **kwargs)
