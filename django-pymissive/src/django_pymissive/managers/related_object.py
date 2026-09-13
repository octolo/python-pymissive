"""Managers for the generic links between missives/campaigns and any model.

Beyond the two plain managers, this module exposes the pieces an integration
needs to annotate **its own** models with their missives:
:class:`MissiveRelatedQuerySetMixin` for the annotations,
:func:`missive_related_queryset` for the raw link rows, and
:func:`missive_link_q` to express "which missives am I talking about" once.
"""

from django.db import models
from django.db.models import Count, Min, Q, Value
from django.db.models.expressions import OuterRef, Subquery
from django.db.models.functions import Cast, Coalesce, JSONObject, Replace
from pymissive.config import SENT_EVENTS

from ..models.choices import missive_type_filter, pending_missive_q, sent_missive_q


#: Ordering of the link rows: newest missive first, most recent link as
#: tie-break. The link's own ``id`` is auto-incremented, so it breaks ties by
#: insertion order; ``missive_id`` is a UUID4, which would rank two missives
#: created in the same microsecond at random.
_NEWEST_FIRST = ("-missive__created_at", "-id")

#: Ids per ``IN`` clause in :func:`missive_summaries_by_object`.
#:
#: Every id is one bound parameter, and PostgreSQL's extended protocol counts
#: them on 16 bits: 65 535 per statement, a hard ceiling an export reaches well
#: before the database itself struggles. SQLite's own limit depends on the build
#: (999, 32 766 or more), so a batch that passes in tests can still fail in
#: production — hence a size that fits everywhere rather than the backend's max.
_ID_BATCH_SIZE = 5000


def _id_batches(values, size: int):
    """Slice *values* into lists of at most *size* ids."""
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def link_filters(filters: dict) -> dict:
    """Guard the ``**filters`` a caller hands to :func:`missive_link_q`.

    ``prefix`` is that function's lookup path to the missive, which the callers
    below own — a link row always reaches its missive through ``missive``. Left
    through, it either resolves against the wrong model (``FieldError``) or
    duplicates the keyword argument, both from deep inside the query builder.
    """
    if "prefix" in filters:
        raise TypeError(
            "prefix is not a filter: a link row always reaches its missive "
            "through 'missive'. Pass campaign, support, missive_type, "
            "thread_type, metadata or sent."
        )
    return filters


def object_id_value(pk) -> str:
    """Canonical ``object_id`` for a generic link: the pk as text, dashless.

    ``object_id`` is a ``CharField`` so an integration can be keyed by anything —
    an integer as well as a UUID. Dashes are stripped because a UUID has no
    single text spelling across backends: PostgreSQL renders it dashed, SQLite
    stores it as 32 hex characters. Normalising on write is what lets one stored
    value match :func:`object_id_expr` on both.
    """
    return str(pk).replace("-", "")


def object_id_expr(outer_field: str = "pk"):
    """:func:`object_id_value` of a correlated pk, computed by the database.

    Used instead of a bare ``OuterRef("pk")``: comparing the text column to an
    integer pk raises on PostgreSQL and silently matches nothing on SQLite.
    """
    return Replace(
        Cast(OuterRef(outer_field), output_field=models.CharField()),
        Value("-"),
        Value(""),
    )


class MissiveRelatedObjectManager(models.Manager):
    """Manager for the MissiveRelatedObject model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related("missive")
        return qs


class CampaignRelatedObjectManager(models.Manager):
    """Manager for the CampaignRelatedObject model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related("campaign")
        return qs


def content_type_q(model, prefix: str = "") -> Q:
    """``Q`` selecting the generic link rows pointing at ``model``.

    Matches on ``app_label`` + ``model`` instead of resolving a ``ContentType``
    row: ``ContentType.objects.get_for_model()`` issues a query, which makes it
    unusable from a manager's ``get_queryset()`` (admin autodiscovery builds
    those before ``django_content_type`` is guaranteed to be reachable, e.g. on
    a worker). Costs a join on a tiny table in exchange.
    """
    meta = model._meta.concrete_model._meta
    field = f"{prefix}__content_type" if prefix else "content_type"
    return Q(**{
        f"{field}__app_label": meta.app_label,
        f"{field}__model": meta.model_name,
    })


def missive_link_q(
    *,
    prefix: str = "missive",
    campaign=None,
    support: str | None = None,
    missive_type=None,
    thread_type: str | None = None,
    metadata: dict | None = None,
    sent: bool | None = None,
) -> Q:
    """``Q`` narrowing a set of missives, whatever the model you start from.

    ``prefix`` is the lookup path leading to the missive: ``"missive"`` from a
    ``MissiveRelatedObject``, ``""`` on a ``Missive`` queryset.

    Args:
        campaign: A campaign instance or pk — only missives of that campaign.
        support: A support key, alias or missive type (see
            :func:`pymissive.config.normalize_support`); selects every missive
            type of that support, so ``"address"`` covers ``lre`` (registered or
            plain mail) and ``hand_delivery`` alike.
        missive_type: One type or an iterable of types, when a whole support is
            too broad.
        thread_type: Usually ``MissiveThreadType.MISSIVE`` to ignore the
            ``HISTORY`` rows a resend leaves behind.
        metadata: ``{key: value}`` pairs matched inside the missive ``metadata``
            JSON bag, for discriminators the lib knows nothing about.
        sent: ``True`` for missives that left the pending state, ``False`` for
            the ones still waiting. Prefer this over a raw ``status`` filter: it
            also covers the legacy empty status.
    """
    def field(name: str) -> str:
        return f"{prefix}__{name}" if prefix else name

    q = Q()
    if campaign is not None:
        q &= Q(**{field("campaign_id"): getattr(campaign, "pk", campaign)})
    if support is not None:
        q &= Q(**missive_type_filter(support, prefix=prefix))
    if missive_type is not None:
        if isinstance(missive_type, (list, tuple, set, frozenset)):
            q &= Q(**{f"{field('missive_type')}__in": list(missive_type)})
        else:
            q &= Q(**{field("missive_type"): missive_type})
    if thread_type is not None:
        q &= Q(**{field("thread_type"): thread_type})
    for key, value in (metadata or {}).items():
        q &= Q(**{f"{field('metadata')}__{key}": value})
    if sent is not None:
        q &= sent_missive_q(prefix) if sent else pending_missive_q(prefix)
    return q


def missive_related_queryset(instance, **filters):
    """``MissiveRelatedObject`` rows pointing at ``instance``, newest missive first.

    Saves every integration from rebuilding the same generic lookup (content
    type resolution, ``object_id`` cast, ordering). ``filters`` are those of
    :func:`missive_link_q`::

        rows = missive_related_queryset(participant, campaign=campaign, support="email")
        last_missive = rows.first().missive
    """
    from ..models.related_object import MissiveRelatedObject

    return (
        MissiveRelatedObject.objects.filter(
            content_type_q(type(instance)),
            missive_link_q(**link_filters(filters)),
            object_id=object_id_value(instance.pk),
        )
        .order_by(*_NEWEST_FIRST)
    )


def missive_summaries_by_object(model, object_ids, **filters) -> dict:
    """``{object_id: {"missives", "events", "last"}}`` for a batch of objects.

    The batch counterpart of :class:`MissiveRelatedQuerySetMixin`, whose
    annotations are correlated subqueries — re-evaluated for every row they
    annotate, which is the right trade on a paginated page and the wrong one on a
    full export. This runs **two grouped queries per batch of
    :data:`_ID_BATCH_SIZE` ids** — the link rows, then the events of their
    missives — so the work stays linear in the number of objects instead of
    super-linear, and no single statement carries an unbounded ``IN``.

    Values reuse the names the annotations produce, so a template can read either
    source::

        {"missives": 2, "events": 5, "last": {
            "uid": "…", "status": "success", "missive_type": "email",
            "sent_at": datetime(…),
        }}

    Every requested object gets an entry, zeroed (and ``last`` empty) when it has
    no matching missive. Keys are the canonical ``object_id``, so look them up
    with ``object_id_value(obj.pk)``::

        summaries = missive_summaries_by_object(Participant, [p.pk for p in page])
        summaries[object_id_value(participant.pk)]["missives"]

    Unlike :meth:`MissiveRelatedQuerySetMixin.with_last_missive`, ``uid`` is always
    the dashed ``str(UUID)`` and ``sent_at`` a ``datetime``: nothing goes through
    JSON here, so there is no per-backend rendering to normalise. ``filters`` are
    those of :func:`missive_link_q`.
    """
    from ..models.event import MissiveEvent
    from ..models.related_object import MissiveRelatedObject

    summaries = {
        object_id_value(getattr(pk, "pk", pk)): {"missives": 0, "events": 0, "last": {}}
        for pk in object_ids or []
    }
    if not summaries:
        return {}

    type_q = content_type_q(model)
    link_q = missive_link_q(**link_filters(filters))

    # One pass over the ordered rows: the first row of an object_id is its newest
    # missive, and the set of ids does the deduplication a COUNT(DISTINCT) would.
    # An object_id belongs to a single batch, so the ordering it relies on holds.
    missives_by_object: dict[str, set] = {}
    last_missive: dict[str, object] = {}
    for object_ids_batch in _id_batches(summaries, _ID_BATCH_SIZE):
        rows = (
            MissiveRelatedObject.objects.filter(
                type_q,
                link_q,
                object_id__in=object_ids_batch,
            )
            .order_by("object_id", *_NEWEST_FIRST)
            .values("object_id", "missive_id", "missive__status", "missive__missive_type")
        )
        for row in rows:
            object_id = row["object_id"]
            missives = missives_by_object.setdefault(object_id, set())
            if not missives:
                last_missive[object_id] = row["missive_id"]
                summaries[object_id]["last"] = {
                    "uid": str(row["missive_id"]),
                    "status": row["missive__status"],
                    "missive_type": row["missive__missive_type"],
                    "sent_at": None,
                }
            missives.add(row["missive_id"])

    every_missive = {mid for mids in missives_by_object.values() for mid in mids}
    if not every_missive:
        return summaries

    # Grouped by missive rather than joined to the links: joining would multiply
    # the link rows by the events, which is what makes the annotated counters scan
    # more than they report. Batched on its own: an object may carry any number of
    # missives, so this pass is not bounded by the one above.
    events = {}
    for missive_ids in _id_batches(every_missive, _ID_BATCH_SIZE):
        events.update({
            row["missive_id"]: row
            for row in MissiveEvent.objects.filter(missive_id__in=missive_ids)
            .order_by()  # the model orders by date, which would land in the GROUP BY
            .values("missive_id")
            .annotate(
                _events=Count("id"),
                _sent_at=Min("occurred_at", filter=Q(event__in=SENT_EVENTS)),
            )
        })
    for object_id, missives in missives_by_object.items():
        summary = summaries[object_id]
        summary["missives"] = len(missives)
        summary["events"] = sum(
            events.get(mid, {}).get("_events", 0) for mid in missives
        )
        summary["last"]["sent_at"] = events.get(last_missive[object_id], {}).get(
            "_sent_at"
        )
    return summaries


def _sent_at_subquery():
    """Correlated subquery dating the send of the enclosing link row's missive.

    Same definition as the ``sent_at`` annotation of ``BaseMissiveManager``
    (oldest :data:`pymissive.config.SENT_EVENTS` event) but expressed as an
    ``ORDER BY … LIMIT 1``, so it can live inside another subquery where an
    aggregate would force a ``GROUP BY``.
    """
    from ..models.event import MissiveEvent

    return Subquery(
        MissiveEvent.objects.filter(
            missive_id=OuterRef("missive_id"),
            event__in=SENT_EVENTS,
        )
        .order_by("occurred_at", "id")
        .values("occurred_at")[:1],
        output_field=models.DateTimeField(),
    )


class MissiveRelatedQuerySetMixin:
    """Annotate a model with the missives linked to it through ``MissiveRelatedObject``.

    Mix this into the queryset of **your** model — the one missives point at —
    not into a pymissive queryset::

        class ParticipantQuerySet(MissiveRelatedQuerySetMixin, models.QuerySet):
            pass

        Participant.objects.with_last_missive(campaign=campaign, support="email")

    Every method takes the :func:`missive_link_q` filters, so the same call
    shape scopes to a campaign, a support, a thread or a metadata
    discriminator. Each annotation is one correlated subquery: name them
    explicitly (``prefix`` / ``name``) when you need several at once, e.g. one
    per support.
    """

    def _missive_links(self, **filters):
        """Link rows of the row being annotated, newest missive first."""
        from ..models.related_object import MissiveRelatedObject

        return (
            MissiveRelatedObject.objects.filter(
                content_type_q(self.model),
                missive_link_q(**link_filters(filters)),
                object_id=object_id_expr(),
            )
            .order_by(*_NEWEST_FIRST)
        )

    def with_last_missive(self, *, prefix: str = "last_missive", **filters):
        """Annotate ``prefix`` with the newest matching missive, as a JSON dict.

        ``{"uid", "status", "missive_type", "sent_at"}``, or ``{}`` when the row
        has no matching missive — so callers can always ``.get()`` without
        guarding for ``None``. Packed into one ``ORDER BY … LIMIT 1`` scan
        rather than one subquery per value.

        ``uid`` comes back as the database renders it inside JSON: dashed on
        PostgreSQL, 32-char hex on SQLite. Normalise with ``uuid.UUID`` if you
        compare it to a ``str(missive.pk)``.

        ``thread_type`` is deliberately not filtered by default: the newest
        missive wins, draft or archived, so deleting a draft does not erase the
        visible history of past sends.
        """
        last = self._missive_links(**filters).annotate(
            _data=JSONObject(
                uid="missive_id",
                status="missive__status",
                missive_type="missive__missive_type",
                sent_at=_sent_at_subquery(),
            ),
        )
        return self.annotate(**{
            prefix: Coalesce(
                Subquery(last.values("_data")[:1], output_field=models.JSONField()),
                Value({}, output_field=models.JSONField()),
            ),
        })

    def with_missive_count(self, *, name: str = "missive_count", **filters):
        """Annotate ``name`` with how many missives match (``0``, never ``NULL``).

        Call it once per counter you need::

            qs.with_missive_count(name="missive_email_count", support="email")
              .with_missive_count(name="missive_sent_count", sent=True)
        """
        counted = (
            self._missive_links(**filters)
            .order_by()
            .values("object_id")
            .annotate(_n=Count("missive_id", distinct=True))
            .values("_n")
        )
        return self.annotate(**{
            name: Coalesce(
                Subquery(counted, output_field=models.IntegerField()),
                Value(0),
            ),
        })

    def with_missive_counts(self, *, prefix: str = "missive_counts", **filters):
        """Annotate ``prefix`` with ``{"missives": N, "events": E}`` as JSON.

        One correlated subquery for the two counters, where two
        ``with_missive_count`` calls would make two. The rows it groups are still
        links × events, though — the join to the events multiplies them, and the
        ``DISTINCT`` of each counter is what keeps the numbers right. On missives
        carrying many events, one subquery does not mean less scanning.

        Zeros rather than ``NULL`` when the row has no missive at all.
        """
        counted = (
            self._missive_links(**filters)
            .order_by()
            .values("object_id")
            .annotate(
                _n_missives=Count("missive_id", distinct=True),
                _n_events=Count("missive__to_missiveevent", distinct=True),
            )
            .annotate(_data=JSONObject(missives="_n_missives", events="_n_events"))
            .values("_data")
        )
        return self.annotate(**{
            prefix: Coalesce(
                Subquery(counted, output_field=models.JSONField()),
                Value({"missives": 0, "events": 0}, output_field=models.JSONField()),
            ),
        })

    def with_campaign_missive_count(
        self, *, name: str = "campaign_missive_count", **filters
    ):
        """Annotate ``name`` with the missives of the campaigns linked to the row.

        The counterpart of :meth:`with_missive_count` for objects attached to a
        whole campaign through ``CampaignRelatedObject`` (a meeting, a company)
        instead of to individual missives::

            Meeting.objects.with_campaign_missive_count(
                name="count_missive_pending", sent=False,
                thread_type=MissiveThreadType.MISSIVE,
            )
        """
        from ..models.missive import Missive

        rel = "campaign__to_campaignrelatedobject"
        counted = (
            Missive._base_manager.filter(
                content_type_q(self.model, prefix=rel),
                missive_link_q(prefix="", **link_filters(filters)),
                **{f"{rel}__object_id": object_id_expr()},
            )
            .order_by()
            .values(f"{rel}__object_id")
            .annotate(_n=Count("pk", distinct=True))
            .values("_n")
        )
        return self.annotate(**{
            name: Coalesce(
                Subquery(counted, output_field=models.IntegerField()),
                Value(0),
            ),
        })
