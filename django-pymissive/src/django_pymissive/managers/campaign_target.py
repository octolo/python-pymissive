"""Queryset for campaign selection rows."""

from django.db import models


class CampaignTargetQuerySet(models.QuerySet):
    def with_contacts(self):
        """Prefetch the linked object and the checked contact lists.

        One query for the generic targets of the chunk, one for the
        sub-targets. Reading either afterwards does not hit the database.
        """
        return self.prefetch_related("target", "to_campaignrecipienttarget")


CampaignTargetManager = models.Manager.from_queryset(CampaignTargetQuerySet)
