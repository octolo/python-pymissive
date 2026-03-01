from .base import BaseCampaignBackend
from .campaign import run_campaign


class SyncBackend(BaseCampaignBackend):
    def delay(self, campaign_id: int):
        run_campaign(campaign_id)
