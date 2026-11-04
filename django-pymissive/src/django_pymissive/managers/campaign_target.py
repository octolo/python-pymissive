"""Queryset for campaign selection rows."""

from django.db import models
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce


class JSONListLength(models.Func):
    """Number of entries in a JSON array."""

    function = "JSON_ARRAY_LENGTH"
    output_field = models.IntegerField()

    def as_oracle(self, compiler, connection, **extra_context):
        return super().as_sql(
            compiler,
            connection,
            template="JSON_VALUE(%(expressions)s, '$.size()' RETURNING NUMBER)",
            **extra_context,
        )

    def as_postgresql(self, compiler, connection, **extra_context):
        return super().as_sql(
            compiler,
            connection,
            function="JSONB_ARRAY_LENGTH",
            **extra_context,
        )

    def as_mysql(self, compiler, connection, **extra_context):
        return super().as_sql(
            compiler,
            connection,
            function="JSON_LENGTH",
            **extra_context,
        )


class CampaignTargetQuerySet(models.QuerySet):
    def with_contacts(self):
        """Prefetch the linked object and the checked contact lists.

        One query for the generic targets of the chunk, one for the
        sub-targets. Reading either afterwards does not hit the database.
        """
        return self.prefetch_related("target", "to_campaignrecipienttarget")

    def with_target_count(self):
        """Annotate the number of explicitly selected contact values."""
        from ..models.campaign_target import CampaignRecipientTarget

        count = (
            CampaignRecipientTarget._base_manager.filter(target_id=OuterRef("pk"))
            .order_by()
            .values("target_id")
            .annotate(total=models.Sum(JSONListLength("values")))
            .values("total")
        )
        return self.annotate(
            target_count=Coalesce(
                Subquery(count, output_field=models.IntegerField()),
                Value(0),
            ),
        )


CampaignTargetManager = models.Manager.from_queryset(CampaignTargetQuerySet)
