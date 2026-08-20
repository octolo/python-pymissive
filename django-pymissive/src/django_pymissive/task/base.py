class BaseCampaignBackend:
    def delay(self, campaign_id: int):
        raise NotImplementedError

    def enqueue(self, func, *args, **kwargs):
        """Run ``func`` through this backend (sync, thread, celery, or rq)."""
        raise NotImplementedError
