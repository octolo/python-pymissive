"""Manager for MissiveCampaign model."""

from functools import cache

from django.db import models
from django.db.models import Exists, F, Q, Value
from django.db.models.expressions import Subquery, OuterRef
from django.db.models.functions import Coalesce, NullIf
from pymissive.config import GENERIC_SUPPORT, MISSIVE_TYPES

from ..models.choices import (
    MissiveStatus,
    MissiveThreadType,
    error_missive_q,
    missive_type_filter,
    pending_missive_q,
    sent_missive_q,
)

#: Lookup path to the missives, from a campaign as well as from a run.
_M = "to_missive"


def support_count_name(support: str, suffix: str = "") -> str:
    """Annotation name for a per-support counter (``count_support_email_sent``)."""
    return f"count_support_{support}{f'_{suffix}' if suffix else ''}"


def missive_thread_q() -> Q:
    """``Q`` restricting the missive join to live sends (no history/message)."""
    return Q(**{f"{_M}__thread_type": MissiveThreadType.MISSIVE})


def count_missive_expr(*conditions: Q):
    """``Count`` of the live missives narrowed by ``conditions``.

    Shared by :class:`MissiveCampaignManager` and
    ``MissiveScheduledCampaignQuerySet.with_counts()`` so that a counter of the
    same name means the same thing on a campaign and on one of its runs. Both
    reach their missives through ``to_missive``.
    """
    missive_q = missive_thread_q()
    for condition in conditions:
        missive_q &= condition
    return models.Count(_M, filter=missive_q, distinct=True)


def pct_expr(cnt):
    """``cnt`` as a percentage of ``count_recipient``, ``0.0`` when there is none.

    ``NULLIF`` rather than a ``When(count_recipient=0)`` guard: the SQL compiler
    inlines an aggregate behind every reference to it, so testing the divisor
    separately would recompute ``count_recipient`` once more per percentage —
    eight times over the whole queryset.
    """
    return Coalesce(
        cnt * 100.0 / NullIf(F("count_recipient"), Value(0)),
        Value(0.0),
        output_field=models.FloatField(),
    )


def support_count_annotations() -> dict:
    """``count_support_<support>``, ``_sent`` and ``_error`` for each support.

    Derived from ``missive_type`` rather than the ``missive_support`` column: rows
    created before the column existed (or imported without it) still carry a type,
    and the type is what ``GENERIC_SUPPORT`` maps.
    """
    annotations = {}
    for support in GENERIC_SUPPORT:
        type_q = Q(**missive_type_filter(support, prefix=_M))
        annotations[support_count_name(support)] = count_missive_expr(type_q)
        annotations[support_count_name(support, "sent")] = count_missive_expr(
            type_q, sent_missive_q(prefix=_M),
        )
        annotations[support_count_name(support, "error")] = count_missive_expr(
            type_q, error_missive_q(prefix=_M),
        )
    return annotations


def missive_count_annotations() -> dict:
    """The counters reached through ``to_missive`` and nothing else.

    Two families, and the difference matters:

    * The historical ones — ``count_missive``, ``count_type_<type>``,
      ``count_missive_<status>`` — count **every** thread, including the
      ``HISTORY`` rows left behind by a resend and the ``MESSAGE`` rows of a
      conversation.
    * ``count_sent`` / ``count_pending`` / ``count_error`` and
      ``count_support_<support>`` count only ``thread_type=MISSIVE``, because a
      resend is not a new send. Use these unless you really want the archived
      threads too; ``count_thread_<type>`` exposes the per-thread breakdown.

    ``MissiveScheduledCampaignQuerySet.with_counts()`` shares both the names and
    the ``thread_type=MISSIVE`` scope through :func:`count_missive_expr`, so
    ``count_sent`` on a campaign and on one of its runs answer the same question.
    Only the historical family is campaign-specific.
    """
    return {
        "count_missive": models.Count(_M, distinct=True),
        "count_sent": count_missive_expr(sent_missive_q(prefix=_M)),
        "count_pending": count_missive_expr(pending_missive_q(prefix=_M)),
        "count_error": count_missive_expr(error_missive_q(prefix=_M)),
        **{
            f"count_thread_{thread.value.lower()}": models.Count(
                _M, filter=Q(**{f"{_M}__thread_type": thread}), distinct=True,
            )
            for thread in MissiveThreadType
        },
        **support_count_annotations(),
        **{
            f"count_missive_{status.value.lower()}": models.Count(
                _M, filter=Q(**{f"{_M}__status": status}), distinct=True,
            )
            for status in MissiveStatus
        },
        **{
            f"count_type_{type_key}": models.Count(
                _M, filter=Q(**{f"{_M}__missive_type": type_key}), distinct=True,
            )
            for type_key in MISSIVE_TYPES
        },
    }


def related_count_annotations() -> dict:
    """The counters that each walk a relation of their own.

    Recipients, events, related objects and documents: four more joins, and they
    multiply each other. A campaign of 5 000 missives with 2 recipients and 8
    events each yields 80 000 intermediate rows for every ``COUNT(DISTINCT)`` to
    deduplicate.
    """
    return {
        "count_recipient": models.Count(f"{_M}__to_missiverecipient", distinct=True),
        "count_event": models.Count(f"{_M}__to_missiveevent", distinct=True),
        "count_related_object": models.Count("to_campaignrelatedobject", distinct=True),
        "count_attachment": models.Count("to_campaigndocument", distinct=True),
        **{
            f"count_recipient_{status.value.lower()}": models.Count(
                f"{_M}__to_missiverecipient",
                distinct=True,
                filter=Q(**{f"{_M}__to_missiverecipient__status": status}),
            )
            for status in MissiveStatus
        },
    }


def pct_annotations() -> dict:
    """``pct_recipient_<status>``, the share of the recipients in that status."""
    return {
        f"pct_recipient_{status.value.lower()}": pct_expr(
            F(f"count_recipient_{status.value.lower()}"),
        )
        for status in MissiveStatus
    }


@cache
def count_annotation_names() -> frozenset:
    """Names of the counters, without the expressions — computed once.

    ``MissiveCampaign.__getattr__`` tests every missing ``count_*`` attribute
    against this set, so building the ~60 expressions of
    :func:`count_annotations` just to read their keys would be paid on each
    lookup. The names only depend on module constants (``MISSIVE_TYPES``,
    ``GENERIC_SUPPORT``, the status enums), hence the cache.
    """
    return frozenset(count_annotations())


def count_annotations() -> dict:
    """Every counter :meth:`MissiveCampaignQuerySet.with_counts` produces.

    Single source for the queryset and for ``MissiveCampaign._count_fields()``,
    which serves them on a campaign the queryset did not annotate. Adding a
    counter here makes it readable both ways.
    """
    return {
        **missive_count_annotations(),
        **related_count_annotations(),
        **pct_annotations(),
    }


class MissiveCampaignQuerySet(models.QuerySet):
    """QuerySet exposing the campaign counters as opt-in annotations."""

    def with_counts(self, *names):
        """Annotate the counters :func:`count_annotations` enumerates.

        Without arguments, all of them; with names, only those. The query pays
        one deduplication pass per aggregate over the rows the joins multiplied,
        and they all share a single scan — so the cost follows the *number* of
        counters, not the number of relations. Naming the handful a list
        displays, instead of taking the fifty-odd others along, measured three
        times faster for the same values.

        Opt-in, and deliberately not applied in ``get_queryset()``: the aggregates
        force a ``GROUP BY`` on all of the campaign's columns, which a plain
        lookup — a ``.get(pk=…)`` reading a subject — would pay for nothing.
        Reading a counter without this call still works (see
        :meth:`MissiveCampaign._count`), at one query per instance; annotate here
        as soon as a list displays them.

        Raises:
            ValueError: for a name no counter answers to. Left through, the
                column would silently fall back to one query per row.
        """
        counters = {**missive_count_annotations(), **related_count_annotations()}
        percentages = pct_annotations()
        if names:
            wanted = set(names)
            unknown = wanted - counters.keys() - percentages.keys()
            if unknown:
                raise ValueError(
                    f"Unknown campaign counters: {', '.join(sorted(unknown))}",
                )
            percentages = {key: percentages[key] for key in percentages if key in wanted}
            # A percentage divides its own recipient counter by count_recipient,
            # so asking for one has to bring both along.
            for name in percentages:
                wanted |= {"count_recipient", name.replace("pct_", "count_", 1)}
            counters = {key: value for key, value in counters.items() if key in wanted}
        return self.annotate(
            **counters,
        # Second annotate: a percentage reads the counter declared above, and an
        # annotation cannot be referenced from the call that declares it.
        ).annotate(**percentages)

    def delete(self):
        """Refuse if any selected campaign has a live missive past draft."""
        from django.db.models.deletion import ProtectedError
        from django.utils.translation import gettext as _

        from ..models.missive import Missive

        blocked = self.filter(
            Exists(
                Missive._base_manager.filter(
                    sent_missive_q(),
                    campaign_id=OuterRef("pk"),
                    thread_type=MissiveThreadType.MISSIVE,
                )
            )
        )
        if blocked.exists():
            protected = set(
                Missive._base_manager.filter(
                    campaign_id__in=self.values("pk"),
                    thread_type=MissiveThreadType.MISSIVE,
                ).filter(sent_missive_q())
            )
            raise ProtectedError(
                _("Cannot delete a campaign that has missives which left the draft state."),
                protected or set(blocked),
            )
        return super().delete()


class MissiveCampaignManager(models.Manager.from_queryset(MissiveCampaignQuerySet)):
    """Manager for MissiveCampaign: two dates, two booleans, counters on demand.

    ``get_queryset()`` only annotates what a plain lookup can afford — the last
    run's dates as ``ORDER BY … LIMIT 1`` subqueries, ``has_sent_missives`` and
    ``has_open_run`` as ``EXISTS``. None of them aggregates, so no ``GROUP BY``:
    a ``.get(pk=…)`` stays a primary key lookup.

    The counters live in :meth:`MissiveCampaignQuerySet.with_counts`, like the
    run's in ``MissiveScheduledCampaignQuerySet.with_counts()``. They remain
    readable on a campaign nobody annotated, through
    :meth:`MissiveCampaign._count`.
    """

    def last_scheduled_subquery(self, field: str = "event"):
        from ..models.scheduler import MissiveScheduledCampaign

        return Subquery(
            MissiveScheduledCampaign.objects.filter(
                campaign=OuterRef("pk"),
            )
            .order_by(f"-{field}", "-id")
            .values(field)[:1],
            output_field=models.CharField(),
        )

    def has_sent_missives_expr(self) -> Exists:
        """``Exists`` on a live missive that left the pending state.

        An ``EXISTS`` rather than ``count_sent > 0``: it needs no aggregate, so it
        can stay in the default queryset, and it stops at the first matching row.
        """
        from ..models.missive import Missive

        return Exists(
            Missive._base_manager.filter(
                sent_missive_q(),
                campaign_id=OuterRef("pk"),
                thread_type=MissiveThreadType.MISSIVE,
            ),
        )

    def open_run_exists(self) -> Exists:
        """``Exists`` on a scheduled run that has not ended yet."""
        from ..models.scheduler import MissiveScheduledCampaign

        return Exists(
            MissiveScheduledCampaign.objects.filter(
                campaign_id=OuterRef("pk"),
                ended_at__isnull=True,
            ),
        )

    def get_queryset(self):
        return super().get_queryset().annotate(
            last_send_date=self.last_scheduled_subquery("send_date"),
            last_ended_at=self.last_scheduled_subquery("ended_at"),
            has_sent_missives=self.has_sent_missives_expr(),
            has_open_run=self.open_run_exists(),
        )
