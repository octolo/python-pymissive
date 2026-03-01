from threading import Thread
from .base import BaseCampaignBackend
from .campaign import run_campaign


class ThreadBackend(BaseCampaignBackend):
    def delay(self, campaign_id: int):
        Thread(target=run_campaign, args=(campaign_id,), daemon=True).start()
