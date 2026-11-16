"""QuerySet counters for campaign steps."""

from typing import cast

from django.db import models
from django.db.models import Exists, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from .campaign import (
    missive_count_annotations,
    missive_related_count_annotations,
    pct_annotations,
)

_MISSIVE_LOOKUP = "to_missive"
_SEND_SPEED_PARENT_LOOKUP = "campaign_step_id"


def target_count_expr(condition):
    from ..models.campaign_target import CampaignTarget

    return Coalesce(
        Subquery(
            CampaignTarget.objects.filter(condition, campaign_step_id=OuterRef("pk"))
            .order_by()
            .values("campaign_step_id")
            .annotate(n=models.Count("pk"))
            .values("n"),
            output_field=models.IntegerField(),
        ),
        Value(0),
    )


def target_count_annotations() -> dict:
    from ..models.campaign_target import CampaignTarget

    return {
        "count_target_pending": target_count_expr(CampaignTarget.active_q()),
        "count_target_abandoned": target_count_expr(models.Q(abandoned_at__isnull=False)),
    }


def count_annotations() -> dict:
    """Missive, recipient and event counters available on one campaign step."""
    return {
        **missive_count_annotations(
            _MISSIVE_LOOKUP,
            send_speed_parent_lookup=_SEND_SPEED_PARENT_LOOKUP,
        ),
        **missive_related_count_annotations(_MISSIVE_LOOKUP),
        **target_count_annotations(),
        **pct_annotations(),
    }


class CampaignStepQuerySet(models.QuerySet):
    def with_counts(self, *names):
        """Annotate all step counters, or only the requested names."""
        counters = {
            **missive_count_annotations(
                _MISSIVE_LOOKUP,
                send_speed_parent_lookup=_SEND_SPEED_PARENT_LOOKUP,
            ),
            **missive_related_count_annotations(_MISSIVE_LOOKUP),
            **target_count_annotations(),
        }
        derived = pct_annotations()
        if names:
            wanted = set(names)
            unknown = wanted - counters.keys() - derived.keys()
            if unknown:
                raise ValueError(
                    f"Unknown campaign step counters: {', '.join(sorted(unknown))}",
                )
            derived = {key: derived[key] for key in derived if key in wanted}
            for name in derived:
                wanted |= {"count_recipient", name.replace("pct_", "count_", 1)}
            counters = {key: value for key, value in counters.items() if key in wanted}
        return self.annotate(**counters).annotate(**derived)

    def with_last_run_dates(self):
        """Annotate the latest run dates among missives built from each step."""
        from ..models.scheduler import MissiveScheduledCampaign

        def latest(field):
            return Subquery(
                MissiveScheduledCampaign.objects.filter(
                    to_missive__campaign_step_id=OuterRef("pk"),
                    **{f"{field}__isnull": False},
                )
                .order_by(f"-{field}", "-pk")
                .values(field)[:1],
            )

        return self.annotate(
            last_send_date=latest("send_date"),
            last_ended_at=latest("ended_at"),
        )

    def delete(self):
        """Refuse when any selected step has a live missive past draft."""
        from django.db.models.deletion import ProtectedError
        from django.utils.translation import gettext as _

        from ..models.choices import MissiveThreadType, sent_missive_q
        from ..models.missive import Missive

        blocked = self.filter(
            Exists(
                Missive._base_manager.filter(
                    sent_missive_q(),
                    campaign_step_id=OuterRef("pk"),
                    thread_type=MissiveThreadType.MISSIVE,
                )
            )
        )
        if blocked.exists():
            protected = set(
                Missive._base_manager.filter(
                    campaign_step_id__in=self.values("pk"),
                    thread_type=MissiveThreadType.MISSIVE,
                ).filter(sent_missive_q())
            )
            raise ProtectedError(
                _("Cannot delete a campaign step that has missives which left the draft state."),
                cast(set[models.Model], protected or set(blocked)),
            )
        return super().delete()


class CampaignStepManager(models.Manager.from_queryset(CampaignStepQuerySet)):  # type: ignore[misc]
    pass
