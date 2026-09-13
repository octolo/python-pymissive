from django.db import models
from django.db.models.expressions import Subquery, OuterRef
from django.db.models import F, Max
from django.db.models.functions import Coalesce
from pymissive.config import normalize_support

from ..models.choices import MissiveSupport

#: Column carrying the contact value, per support. Ordered as
#: :pyattr:`MissiveRecipient.target` resolves them.
SUPPORT_VALUE_FIELD = {
    MissiveSupport.ADDRESS: "address",
    MissiveSupport.EMAIL: "email",
    MissiveSupport.PHONE: "phone",
    MissiveSupport.APPLICATION: "notification_id",
}


class MissiveRecipientManager(models.Manager):
    """Manager for the MissiveRecipient model."""

    def last_event_subquery(self, field: str = "event"):
        from ..models.event import MissiveEvent

        return Subquery(
            MissiveEvent.objects.filter(
                missive_id=OuterRef("missive_id"),
                recipient_id=OuterRef("id"),
            )
            .order_by("-occurred_at", "-id")
            .values("event")[:1],
            output_field=models.CharField(),
        )

    def targets_by_missive(self, missive_ids, *, support: str | None = None) -> dict:
        """``{str(missive_id): [target, …]}`` for a batch of missives.

        Resolves the contact value of each recipient the way
        :pyattr:`MissiveRecipient.target` does, but for a whole page of missives
        in a single query — so a list view never has to walk recipients row by
        row, nor map support → column itself.

        Values keep their natural Python type: a string for e-mail, phone and
        notification id, the address dict for postal supports. Recipients with
        no contact value at all fall back to their ``name`` (a hand delivery
        recorded from a name only, for instance) and are skipped when they have
        neither.

        ``support`` restricts the result to one channel (a support key, alias or
        missive type); without it every recipient of the missives is returned.
        """
        missive_ids = [mid for mid in (missive_ids or []) if mid]
        if not missive_ids:
            return {}
        fields = SUPPORT_VALUE_FIELD
        normalized = normalize_support(support) if support else ""
        if support and not normalized:
            raise ValueError(f"Unknown missive support: {support!r}")
        # _base_manager rather than self: get_queryset() annotates count_event,
        # and its LEFT JOIN on the events survives .values() — which only drops
        # the column — leaving the rows to group multiplied by the events. Fifty
        # missives with 3 recipients and 20 events each: 3 000 rows scanned and
        # grouped for 150 read. The prefetch it also carries is ignored anyway.
        qs = self.model._base_manager.filter(missive_id__in=missive_ids)
        if normalized:
            qs = qs.filter(recipient_support=normalized)
            fields = {normalized: SUPPORT_VALUE_FIELD[normalized]}

        by_missive: dict[str, list] = {}
        columns = ("missive_id", "recipient_support", "name", *fields.values())
        for row in qs.order_by("name", "id").values(*columns):
            value = next(
                (
                    row[field]
                    for support_key, field in fields.items()
                    if support_key == row["recipient_support"] and row.get(field)
                ),
                None,
            ) or row["name"]
            if not value:
                continue
            by_missive.setdefault(str(row["missive_id"]), []).append(value)
        return by_missive

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related("missive")
        qs = qs.prefetch_related("to_recipientevent")
        qs = qs.annotate(
            count_event=models.Count(
                "to_recipientevent",
            ),
            last_event=self.last_event_subquery(field="event"),
            last_event_reason=self.last_event_subquery(field="reason"),
            last_event_date=Coalesce(
                Max("to_recipientevent__occurred_at"), F("created_at")
            ),
        )
        return qs


class MissiveRecipientEmailManager(models.Manager):
    """Manager for the MissiveRecipientEmail model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(recipient_support=MissiveSupport.EMAIL)
        return qs

class MissiveRecipientPhoneManager(models.Manager):
    """Manager for the MissiveRecipientPhone model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(recipient_support=MissiveSupport.PHONE)
        return qs

class MissiveRecipientAddressManager(models.Manager):
    """Manager for the MissiveRecipientAddress model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(recipient_support=MissiveSupport.ADDRESS)
        return qs

class MissiveRecipientApplicationManager(models.Manager):
    """Manager for the MissiveRecipientApplication model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(recipient_support=MissiveSupport.APPLICATION)
        return qs
