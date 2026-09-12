"""Manager for MissiveScheduledCampaign model."""

import operator
from functools import reduce

from django.db import models
from django.db.models import Count, F, Q
from pymissive.config import MISSIVE_TYPES

from ..models.choices import MissiveStatus

ERROR_STATUSES = [
    MissiveStatus.FAILED,
    MissiveStatus.PARTIALLY_FAILED,
    MissiveStatus.ERROR,
]


def total_annotation_name(missive_type: str) -> str:
    return f"count_total_{missive_type}"


def sent_annotation_name(missive_type: str) -> str:
    return f"count_sent_{missive_type}"


def error_annotation_name(missive_type: str) -> str:
    return f"count_error_{missive_type}"


def status_annotation_name(status: str) -> str:
    """Overall count for one ``MissiveStatus`` (e.g. ``count_missive_success``)."""
    return f"count_missive_{status}"


class MissiveScheduledCampaignQuerySet(models.QuerySet):
    """QuerySet exposing the run counters as opt-in annotations.

    Counters are derived live from the related missives (``to_missive``), so
    they never drift from the actual missive statuses.

    Two layers of annotations are applied:
    1. Per-type total/sent/error ``Count`` filters, plus overall per-status
       ``count_missive_*`` (one JOIN, multiple conditional counts).
    2. A second ``annotate`` that sums the per-type results into
       ``count_total``, ``count_sent`` and ``count_error`` — no extra JOIN.

    They are opt-in (``with_counts``) and intentionally *not* applied in
    ``get_queryset`` so plain lookups and subqueries stay free of GROUP BY.
    """

    def with_counts(self):
        # Annotation names are deliberately distinct from the model properties
        # (total_count / sent_count / error_count) to avoid clashing with them.
        types = list(MISSIVE_TYPES)
        counts = {}
        for missive_type in types:
            type_q = Q(to_missive__missive_type=missive_type)
            counts[total_annotation_name(missive_type)] = Count(
                "to_missive",
                filter=type_q,
                distinct=True,
            )
            counts[sent_annotation_name(missive_type)] = Count(
                "to_missive",
                filter=type_q & ~Q(to_missive__status=MissiveStatus.DRAFT),
                distinct=True,
            )
            counts[error_annotation_name(missive_type)] = Count(
                "to_missive",
                filter=type_q & Q(to_missive__status__in=ERROR_STATUSES),
                distinct=True,
            )
        for status in MissiveStatus:
            counts[status_annotation_name(status)] = Count(
                "to_missive",
                filter=Q(to_missive__status=status),
                distinct=True,
            )

        # Second annotate: sum per-type annotations → no extra JOIN.
        totals = {
            "count_total": reduce(operator.add, [F(total_annotation_name(t)) for t in types]),
            "count_sent": reduce(operator.add, [F(sent_annotation_name(t)) for t in types]),
            "count_error": reduce(operator.add, [F(error_annotation_name(t)) for t in types]),
        }
        return self.annotate(**counts).annotate(**totals)


class MissiveScheduledCampaignManager(
    models.Manager.from_queryset(MissiveScheduledCampaignQuerySet)
):
    """Manager for MissiveScheduledCampaign (plain by default, counts opt-in)."""
