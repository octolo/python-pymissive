"""Manager for MissiveScheduledCampaign model."""

from django.db import models
from django.db.models import Exists, F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from pymissive.config import GENERIC_SUPPORT, MISSIVE_TYPES

from ..models.choices import (
    ERROR_STATUSES,
    MissiveStatus,
    MissiveThreadType,
    error_missive_q,
    missive_type_filter,
    pending_missive_q,
    sent_missive_q,
)
from .campaign import count_missive_expr, support_count_name

__all__ = [
    "ATTEMPT_THREADS",
    "ERROR_STATUSES",
    "MissiveScheduledCampaignQuerySet",
    "MissiveScheduledCampaignManager",
    "count_annotations",
    "count_attempt_expr",
    "total_annotation_name",
    "sent_annotation_name",
    "error_annotation_name",
    "status_annotation_name",
    "thread_annotation_name",
]

#: Lookup path from a run to its missives.
_M = "to_missive"

#: Thread types a run answers for: what it pushed out, archived attempts included.
ATTEMPT_THREADS = (MissiveThreadType.MISSIVE, MissiveThreadType.HISTORY)


def total_annotation_name(missive_type: str) -> str:
    return f"count_total_{missive_type}"


def sent_annotation_name(missive_type: str) -> str:
    return f"count_sent_{missive_type}"


def error_annotation_name(missive_type: str) -> str:
    return f"count_error_{missive_type}"


def status_annotation_name(status: str) -> str:
    """Overall count for one ``MissiveStatus`` (e.g. ``count_missive_success``)."""
    return f"count_missive_{status}"


def thread_annotation_name(thread: str) -> str:
    """Count for one thread type (e.g. ``count_thread_history``)."""
    return f"count_thread_{thread}"


def live_error_count_expr():
    """Live failures this run would requeue, on its selected steps.

    ``ERROR``, ``FAILED`` and ``PARTIALLY_FAILED`` with ``thread_type=MISSIVE``.
    An empty step selection means every step of the campaign. Archived attempts
    and conversation messages stay out, and the count is not limited to missives
    already attached to this run: a failure still belongs to the run that
    produced it until the retry archives it.
    """
    from ..models.missive import Missive
    from ..models.scheduler import MissiveScheduledCampaign

    through = MissiveScheduledCampaign.campaign_steps.through
    selected_for_this_step = through.objects.filter(
        missivescheduledcampaign_id=OuterRef(OuterRef("pk")),
        campaignstep_id=OuterRef("campaign_step_id"),
    )
    any_selected_step = through.objects.filter(
        missivescheduledcampaign_id=OuterRef(OuterRef("pk")),
    )
    rows = (
        Missive._base_manager.filter(
            campaign_step__campaign_id=OuterRef("campaign_id"),
            thread_type=MissiveThreadType.MISSIVE,
            status__in=ERROR_STATUSES,
        )
        .filter(~Exists(any_selected_step) | Exists(selected_for_this_step))
        .order_by()
        .values("campaign_step__campaign_id")
        .annotate(n=models.Count("pk"))
        .values("n")
    )
    return Coalesce(Subquery(rows, output_field=models.IntegerField()), Value(0))


def count_attempt_expr(*conditions: Q):
    """``Count`` of the run's send attempts — live rows *and* archived ones.

    A run is a log of what it pushed out: when a later run retries one of its
    missives, the row is archived as ``HISTORY`` but keeps pointing here, and
    must stay in this run's tally. Nothing is double-counted, because the
    replacement is always attached to the newer run. Conversation messages are
    left out — they are not sends.
    """
    attempt_q = Q(**{f"{_M}__thread_type__in": ATTEMPT_THREADS})
    for condition in conditions:
        attempt_q &= condition
    return models.Count(_M, filter=attempt_q, distinct=True)


def count_annotations() -> dict:
    """The run counters, enumerated once.

    Single source for both :meth:`MissiveScheduledCampaignQuerySet.with_counts`
    and ``MissiveScheduledCampaign._count_fields()``, which feeds the counters to
    a non-annotated instance. Adding a counter here makes it readable both ways;
    listing them twice is how one ends up silently returning 0 on the other path.

    Names are deliberately distinct from the model properties (``total_count`` /
    ``sent_count`` / ``error_count``) to avoid clashing with them.
    """
    counts = {}
    for missive_type in MISSIVE_TYPES:
        type_q = Q(**{f"{_M}__missive_type": missive_type})
        counts[total_annotation_name(missive_type)] = count_missive_expr(type_q, lookup=_M)
        counts[sent_annotation_name(missive_type)] = count_missive_expr(
            type_q,
            sent_missive_q(prefix=_M),
            lookup=_M,
        )
        counts[error_annotation_name(missive_type)] = count_missive_expr(
            type_q,
            error_missive_q(prefix=_M),
            lookup=_M,
        )
    for support in GENERIC_SUPPORT:
        support_q = Q(**missive_type_filter(support, prefix=_M))
        counts[support_count_name(support)] = count_missive_expr(support_q, lookup=_M)
        counts[support_count_name(support, "sent")] = count_missive_expr(
            support_q,
            sent_missive_q(prefix=_M),
            lookup=_M,
        )
        counts[support_count_name(support, "error")] = count_missive_expr(
            support_q,
            error_missive_q(prefix=_M),
            lookup=_M,
        )
    for status in MissiveStatus:
        counts[status_annotation_name(status)] = count_attempt_expr(
            Q(**{f"{_M}__status": status}),
        )
    for thread in ATTEMPT_THREADS:
        counts[thread_annotation_name(thread)] = count_attempt_expr(
            Q(**{f"{_M}__thread_type": thread}),
        )
    # Direct aggregates rather than a sum of the per-type buckets: a missive
    # whose type is not in MISSIVE_TYPES — never set, or left behind by a
    # renamed type — belongs to no bucket and would vanish from the run.
    counts["count_total"] = count_missive_expr(lookup=_M)
    counts["count_sent"] = count_missive_expr(sent_missive_q(prefix=_M), lookup=_M)
    counts["count_pending"] = count_missive_expr(pending_missive_q(prefix=_M), lookup=_M)
    counts["count_error"] = count_missive_expr(error_missive_q(prefix=_M), lookup=_M)
    counts["count_live_error"] = live_error_count_expr()
    return counts


class MissiveScheduledCampaignQuerySet(models.QuerySet):
    """QuerySet exposing the run counters as opt-in annotations.

    Counters are derived live from the related missives (``to_missive``), so
    they never drift from the actual missive statuses.

    Two families coexist, mirroring :class:`MissiveCampaignManager`:

    * **Where the payload stands now** — ``count_total*``, ``count_sent*``,
      ``count_pending``, ``count_error*``, ``count_support_*`` — goes through
      :func:`django_pymissive.managers.campaign.count_missive_expr` and covers
      ``thread_type=MISSIVE`` only, so a counter of that name means the same
      thing on a campaign and on one of its runs. It drives the progress bar,
      and it moves when a row leaves the live set (a draft reclaimed by a newer
      run, an attempt archived by a retry). ``count_live_error`` is the live
      failures on the steps this run would send, including those still attached
      to an earlier run. ``with_counts`` adds it to ``count_pending`` when
      ``retry_failed`` is set.
    * **What the run dispatched** — ``count_missive_<status>`` and
      ``count_thread_<type>`` — goes through :func:`count_attempt_expr` and
      keeps the archived attempts, so a finished run never loses the failures it
      produced. Per-status counts may therefore sum above ``count_total``.

    Everything :func:`count_annotations` enumerates lands in one ``annotate`` on
    a single JOIN: the overall ``count_total`` / ``count_sent`` /
    ``count_pending`` / ``count_error``, their per-type and per-support
    breakdowns, the per-status and per-thread counts. The overall ones are
    aggregated in their own right rather than summed from the per-type ones, so
    a missive carrying a type absent from
    ``MISSIVE_TYPES`` still counts — comparing ``count_total`` to the sum of
    ``count_total_<type>`` is in fact how you spot those rows.

    They are opt-in (``with_counts``) and intentionally *not* applied in
    ``get_queryset`` so plain lookups and subqueries stay free of GROUP BY.
    """

    def with_counts(self):
        pending = F("count_pending") + models.Case(
            models.When(
                retry_failed=True,
                send_date__isnull=True,
                ended_at__isnull=True,
                cancelled_at__isnull=True,
                then=F("count_live_error"),
            ),
            default=Value(0),
            output_field=models.IntegerField(),
        )
        return self.annotate(
            **count_annotations(),
            send_speed=models.Avg(f"{_M}__send_speed"),
        ).annotate(count_pending=pending)

    def sending(self) -> list:
        """Runs a live worker is sending (see ``MissiveScheduledCampaign.is_sending``).

        Filtered in Python to reuse ``is_stale``; only open runs are loaded.
        """
        open_runs = self.filter(send_date__isnull=False, ended_at__isnull=True)
        return [run for run in open_runs if getattr(run, "is_sending", False)]

    def delete(self):
        """Refuse while any selected run is being sent."""
        from django.db.models.deletion import ProtectedError

        from ..models.scheduler import SENDING_RUN_DELETE_MESSAGE

        sending = self.sending()
        if sending:
            raise ProtectedError(str(SENDING_RUN_DELETE_MESSAGE), set(sending))
        return super().delete()


class MissiveScheduledCampaignManager(
    models.Manager.from_queryset(MissiveScheduledCampaignQuerySet)  # type: ignore[misc]
):
    """Manager for MissiveScheduledCampaign (plain by default, counts opt-in)."""
