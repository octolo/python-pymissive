"""Managers for the generic links between missives/campaigns and any model.

Beyond the two plain managers, this module exposes the pieces an integration
needs to annotate **its own** models with their missives:
:class:`MissiveRelatedQuerySetMixin` for the annotations,
:func:`missive_related_queryset` for the raw link rows, and
:func:`missive_link_q` to express "which missives am I talking about" once.
:func:`missive_breakdowns_by_object` and :func:`recipient_summaries_by_object`
are the batch counterparts used by statistics and recipient views.
"""

import re
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import models
from django.db.models import Count, F, Min, Q, Value
from django.db.models.expressions import OuterRef, Subquery
from django.db.models.functions import Cast, Coalesce, JSONObject, Replace
from pymissive.config import SENT_EVENTS, missive_support_for_type

from ..models.choices import error_missive_q, missive_type_filter, pending_missive_q, sent_missive_q

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

#: Dimensions :func:`missive_breakdowns_by_object` knows how to group on.
#: Anything else is refused: an arbitrary ORM path would let a caller widen
#: the contract without a test noticing.
_BREAKDOWN_FIELDS = {
    "campaign": "missive__campaign_step__campaign_id",
    "missive_type": "missive__missive_type",
    "status": "missive__status",
}

#: Final segment of a metadata lookup that Django applies as a JSON lookup
#: rather than as another key. Nested keys (``address__city``) stay exact.
_METADATA_LOOKUPS = frozenset(
    {
        "contained_by",
        "contains",
        "endswith",
        "exact",
        "gt",
        "gte",
        "has_any_keys",
        "has_key",
        "has_keys",
        "icontains",
        "iendswith",
        "iexact",
        "in",
        "iregex",
        "isnull",
        "istartswith",
        "startswith",
        "lt",
        "lte",
        "regex",
    }
)
_METADATA_KEY = re.compile(r"^[A-Za-z0-9_]+(?:__[A-Za-z0-9_]+)*$")


def _id_batches(values, size: int):
    """Slice *values* into lists of at most *size* ids."""
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start : start + size]


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


def object_id_value(pk, *, pk_field=None) -> str:
    """Canonical ``object_id`` for a generic link.

    ``object_id`` is a ``CharField`` so an integration can be keyed by anything —
    an integer, text, or UUID. UUID objects are stored without dashes because
    their database representation differs between PostgreSQL and SQLite. Text
    primary keys are preserved verbatim.
    """
    value = str(pk)
    is_uuid = isinstance(pk, UUID) or isinstance(pk_field, models.UUIDField)
    return value.replace("-", "") if is_uuid else value


def object_id_expr(outer_field: str = "pk", *, pk_field=None):
    """:func:`object_id_value` of a correlated pk, computed by the database.

    Used instead of a bare ``OuterRef("pk")``: comparing the text column to an
    integer pk raises on PostgreSQL and silently matches nothing on SQLite.
    """
    value = Cast(OuterRef(outer_field), output_field=models.CharField())
    if isinstance(pk_field, models.UUIDField):
        return Replace(value, Value("-"), Value(""))
    return value


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
    return Q(
        **{
            f"{field}__app_label": meta.app_label,
            f"{field}__model": meta.model_name,
        }
    )


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
        support: A support key or missive type (see
            :func:`pymissive.config.normalize_support`); selects every missive
            type of that support, so ``"address"`` covers ``letter``, ``registered_letter``
            and ``hand_delivery`` alike.
        missive_type: One type or an iterable of types, when a whole support is
            too broad.
        thread_type: Usually ``MissiveThreadType.MISSIVE`` to ignore the
            ``HISTORY`` rows a resend leaves behind.
        metadata: ``{key: value}`` pairs matched inside the missive ``metadata``
            JSON bag, for discriminators the lib knows nothing about. A key may
            end with one JSON lookup, so ``{"channel__in": ("letter", "address")}``
            matches either value. A nested key such as ``address__city`` stays an
            exact match. Keys that are not identifiers are rejected.
        sent: ``True`` for missives that left the pending state, ``False`` for
            the ones still waiting. Prefer this over a raw ``status`` filter: it
            also covers the legacy empty status.
    """

    def field(name: str) -> str:
        return f"{prefix}__{name}" if prefix else name

    q = Q()
    if campaign is not None:
        q &= Q(
            **{
                field("campaign_step__campaign_id"): getattr(campaign, "pk", campaign),
            }
        )
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
        q &= Q(**{f"{field('metadata')}__{_metadata_lookup_key(key)}": value})
    if sent is not None:
        q &= sent_missive_q(prefix) if sent else pending_missive_q(prefix)
    return q


def _metadata_lookup_key(key: str) -> str:
    """Return *key* when it is a JSON key, optionally ending in one JSON lookup.

    ``channel__in`` is the ``in`` lookup. ``address__city`` is a nested key:
    a trailing segment that is not a known lookup is left untouched. Only keys
    that are not identifiers are rejected, so an ordinary JSON key cannot be
    turned into a join or a raw expression.
    """
    if isinstance(key, str) and _METADATA_KEY.fullmatch(key):
        return key
    allowed = ", ".join(sorted(_METADATA_LOOKUPS))
    raise ValueError(f"Unsupported metadata lookup: {key!r}. Use a JSON key or a key plus one of: {allowed}.")


def _breakdown_dimensions(group_by) -> tuple[str, ...]:
    if isinstance(group_by, str) or not isinstance(group_by, (list, tuple)):
        raise TypeError("group_by must be a sequence of dimension names.")
    names = tuple(group_by)
    if not names:
        raise ValueError("group_by must name at least one dimension.")
    unknown = [name for name in names if name not in _BREAKDOWN_FIELDS]
    if unknown:
        known = ", ".join(_BREAKDOWN_FIELDS)
        raise ValueError(f"Unknown breakdown dimension: {unknown[0]!r}. Expected one of {known}.")
    if len(set(names)) != len(names):
        raise ValueError("group_by dimensions must be unique.")
    return names


def _store_breakdown(bucket: dict, dimensions: tuple[str, ...], row: dict) -> None:
    node = bucket
    for index, name in enumerate(dimensions):
        value = row[name]
        if value is None:
            return
        key = str(value)
        if index == len(dimensions) - 1:
            node[key] = {"errors": int(row["errors"] or 0), "total": int(row["total"] or 0)}
            return
        node = node.setdefault(key, {})


def missive_related_queryset(instance, **filters):
    """``MissiveRelatedObject`` rows pointing at ``instance``, newest missive first.

    Saves every integration from rebuilding the same generic lookup (content
    type resolution, ``object_id`` cast, ordering). ``filters`` are those of
    :func:`missive_link_q`::

        rows = missive_related_queryset(participant, campaign=campaign, support="email")
        last_missive = rows.first().missive
    """
    from ..models.related_object import MissiveRelatedObject

    return MissiveRelatedObject.objects.filter(
        content_type_q(type(instance)),
        missive_link_q(**link_filters(filters)),
        object_id=object_id_value(instance.pk),
    ).order_by(*_NEWEST_FIRST)


def _collect_linked_missives(model, summaries, link_q, related_model):
    missives_by_object: dict[str, set] = {}
    last_missive: dict[str, object] = {}
    type_q = content_type_q(model)
    for object_ids_batch in _id_batches(summaries, _ID_BATCH_SIZE):
        rows = (
            related_model.objects.filter(
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
    return missives_by_object, last_missive


def _event_summaries(event_model, missive_ids):
    events = {}
    for missive_ids_batch in _id_batches(missive_ids, _ID_BATCH_SIZE):
        events.update(
            {
                row["missive_id"]: row
                for row in event_model.objects.filter(missive_id__in=missive_ids_batch)
                .order_by()
                .values("missive_id")
                .annotate(
                    _events=Count("id"),
                    _sent_at=Min("occurred_at", filter=Q(event__in=SENT_EVENTS)),
                )
            }
        )
    return events


def _populate_summaries(summaries, missives_by_object, last_missive, events):
    for object_id, missives in missives_by_object.items():
        summary = summaries[object_id]
        summary["missives"] = len(missives)
        summary["events"] = sum(events.get(mid, {}).get("_events", 0) for mid in missives)
        summary["last"]["sent_at"] = events.get(last_missive[object_id], {}).get("_sent_at")


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
        object_id_value(getattr(pk, "pk", pk)): {"missives": 0, "events": 0, "last": {}} for pk in object_ids or []
    }
    if not summaries:
        return {}

    link_q = missive_link_q(**link_filters(filters))
    missives_by_object, last_missive = _collect_linked_missives(model, summaries, link_q, MissiveRelatedObject)

    every_missive = {mid for mids in missives_by_object.values() for mid in mids}
    if not every_missive:
        return summaries

    events = _event_summaries(MissiveEvent, every_missive)
    _populate_summaries(summaries, missives_by_object, last_missive, events)
    return summaries


def missive_breakdowns_by_object(
    model,
    object_ids,
    *,
    group_by=("campaign", "missive_type"),
    campaign=None,
    support: str | None = None,
    missive_type=None,
    thread_type: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """``{object_id: {dimension: …}}`` counts for a batch of objects.

    Groups linked missives in the database, then nests the buckets in Python
    in the order of *group_by*. Accepted dimensions are ``campaign``,
    ``missive_type`` and ``status``. Each leaf is ``{"errors", "total"}``:

    * ``total`` counts missives that left the pending state
      (:func:`sent_missive_q`), so a draft or a legacy empty status contributes
      nothing;
    * ``errors`` counts missives matching :func:`error_missive_q`.

    A missive linked several times, or carrying several events or recipients,
    is still counted once. ``thread_type`` defaults to no filter, so ``HISTORY``
    rows are included until the caller says otherwise. Every requested object
    gets an entry; a dimension value with no missive is simply absent. An empty
    id list issues no query. Filters are those of :func:`missive_link_q` except
    ``sent``, which would hide the draft rows the zero ``total`` is about.

    Keys are text. A campaign id is ``str(pk)`` (dashed for a UUID) and an
    object id is :func:`object_id_value`.
    """
    from ..models.related_object import MissiveRelatedObject

    dimensions = _breakdown_dimensions(group_by)
    summaries: dict[str, dict] = {object_id_value(getattr(pk, "pk", pk)): {} for pk in object_ids or []}
    if not summaries:
        return {}

    link_q = missive_link_q(
        **link_filters(
            {
                "campaign": campaign,
                "support": support,
                "missive_type": missive_type,
                "thread_type": thread_type,
                "metadata": metadata,
            }
        )
    )
    aliases = {name: F(_BREAKDOWN_FIELDS[name]) for name in dimensions}
    type_q = content_type_q(model)
    for object_ids_batch in _id_batches(summaries, _ID_BATCH_SIZE):
        rows = (
            MissiveRelatedObject.objects.filter(type_q, link_q, object_id__in=object_ids_batch)
            .values("object_id", **aliases)
            .annotate(
                errors=Count("missive_id", distinct=True, filter=error_missive_q("missive")),
                total=Count("missive_id", distinct=True, filter=sent_missive_q("missive")),
            )
        )
        for row in rows:
            bucket = summaries.get(row["object_id"])
            if bucket is None:
                continue
            _store_breakdown(bucket, dimensions, row)
    return summaries


def recipient_summaries_by_object(
    model,
    object_ids,
    *,
    campaign=None,
    support: str | None = None,
    missive_type=None,
    thread_type: str | None = None,
) -> dict:
    """``{object_id: [missive, …]}`` recipient rows for a batch of objects.

    Each missive entry carries the ids needed to regroup it (``missive_id``,
    ``campaign_id``, ``missive_type``, ``support``) and the recipients resolved
    by :meth:`MissiveRecipientManager.details_by_missive` — the same contact
    value as :meth:`MissiveRecipientManager.targets_by_missive`, plus the
    recipient status, ``sent_at`` and role.

    Every requested object gets a list, empty when nothing matches. Missives
    are newest first and are not repeated when several links point at them.
    An empty id list issues no query. Two queries run per id batch: the links,
    then the recipients of those missives.
    """
    from ..models.recipient import MissiveRecipient
    from ..models.related_object import MissiveRelatedObject

    summaries: dict[str, list] = {object_id_value(getattr(pk, "pk", pk)): [] for pk in object_ids or []}
    if not summaries:
        return {}

    link_q = missive_link_q(
        **link_filters(
            {
                "campaign": campaign,
                "support": support,
                "missive_type": missive_type,
                "thread_type": thread_type,
            }
        )
    )
    type_q = content_type_q(model)
    for object_ids_batch in _id_batches(summaries, _ID_BATCH_SIZE):
        linked: dict[str, list] = {}
        seen: dict[str, set] = {}
        rows = (
            MissiveRelatedObject.objects.filter(type_q, link_q, object_id__in=object_ids_batch)
            .order_by("object_id", *_NEWEST_FIRST)
            .values(
                "object_id",
                "missive_id",
                "missive__missive_type",
                "missive__campaign_step__campaign_id",
            )
        )
        for row in rows:
            object_id = row["object_id"]
            missive_ids = seen.setdefault(object_id, set())
            if row["missive_id"] in missive_ids:
                continue
            missive_ids.add(row["missive_id"])
            linked.setdefault(object_id, []).append(row)
        details = MissiveRecipient.objects.details_by_missive(
            [row["missive_id"] for entries in linked.values() for row in entries],
            support=support,
        )
        for object_id, entries in linked.items():
            summaries[object_id] = [_recipient_summary(row, details) for row in entries]
    return summaries


def _recipient_summary(row: dict, details: dict) -> dict:
    missive_type = row["missive__missive_type"]
    campaign_id = row["missive__campaign_step__campaign_id"]
    return {
        "missive_id": str(row["missive_id"]),
        "campaign_id": None if campaign_id is None else str(campaign_id),
        "missive_type": missive_type,
        "support": missive_support_for_type(missive_type) or "",
        "recipients": list(details.get(str(row["missive_id"]), ())),
    }


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


if TYPE_CHECKING:

    class _QuerySetMixinBase(models.QuerySet):
        pass
else:

    class _QuerySetMixinBase:
        pass


class MissiveRelatedQuerySetMixin(_QuerySetMixinBase):
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

        return MissiveRelatedObject.objects.filter(
            content_type_q(self.model),
            missive_link_q(**link_filters(filters)),
            object_id=object_id_expr(pk_field=self.model._meta.pk),
        ).order_by(*_NEWEST_FIRST)

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
        return self.annotate(
            **{
                prefix: Coalesce(
                    Subquery(last.values("_data")[:1], output_field=models.JSONField()),
                    Value({}, output_field=models.JSONField()),
                ),
            }
        )

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
        return self.annotate(
            **{
                name: Coalesce(
                    Subquery(counted, output_field=models.IntegerField()),
                    Value(0),
                ),
            }
        )

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
        return self.annotate(
            **{
                prefix: Coalesce(
                    Subquery(counted, output_field=models.JSONField()),
                    Value({"missives": 0, "events": 0}, output_field=models.JSONField()),
                ),
            }
        )

    def with_campaign_missive_count(self, *, name: str = "campaign_missive_count", **filters):
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

        rel = "campaign_step__campaign__to_campaignrelatedobject"
        counted = (
            Missive._base_manager.filter(
                content_type_q(self.model, prefix=rel),
                missive_link_q(prefix="", **link_filters(filters)),
                **{f"{rel}__object_id": object_id_expr(pk_field=self.model._meta.pk)},
            )
            .order_by()
            .values(f"{rel}__object_id")
            .annotate(_n=Count("pk", distinct=True))
            .values("_n")
        )
        return self.annotate(
            **{
                name: Coalesce(
                    Subquery(counted, output_field=models.IntegerField()),
                    Value(0),
                ),
            }
        )
