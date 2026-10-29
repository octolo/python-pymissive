"""Who receives a campaign, without building missives.

Selecting 1500 targets is one ``bulk_create`` of lightweight rows. The
missive is built at send time by
:func:`django_pymissive.services.drafts.materialize_missive`.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models import Count, Q
from django.db.models.signals import pre_delete
from pymissive.config import normalize_missive_type

from ..managers.related_object import object_id_value
from ..models.campaign_target import CampaignTarget

#: Rows per ``bulk_create`` batch. A full campaign is a couple of round-trips,
#: and each statement stays under the database parameter limit.
BATCH_SIZE = 1000

#: Rows loaded at a time while streaming a selection. Generic foreign keys
#: cannot be ``select_related``, so each chunk is prefetched on its own.
CHUNK_SIZE = 500

_suppress_target_cleanup = ContextVar("pymissive_suppress_target_cleanup", default=False)


def require_missive_type(missive_type: str) -> str:
    """Return the canonical missive type, or raise ``ValueError``."""
    key = normalize_missive_type(missive_type)
    if not key:
        raise ValueError(f"Unknown missive type: {missive_type!r}")
    return key


def selection_qs(
    campaign,
    *,
    missive_type: str | None = None,
    active_only: bool = False,
):
    """Return the selection rows of *campaign*.

    ``active_only`` keeps rows with no missive yet and not abandoned, which
    is what the checkbox lists.
    """
    qs = CampaignTarget.objects.filter(campaign=campaign)
    if missive_type is not None:
        qs = qs.filter(missive_type=require_missive_type(missive_type))
    if active_only:
        qs = qs.filter(CampaignTarget.active_q())
    return qs


def select(campaign, missive_type: str, targets) -> int:
    """Select *targets* for ``(campaign, missive_type)``.

    *targets* is a saved instance, an iterable of them, or a queryset.
    Already-selected targets (a live row, missive still null) are skipped,
    so the call is idempotent. A target whose previous row already points at
    a missive is selected again: that is a new send.

    Returns how many targets were missing a live row. A concurrent selection
    can still make ``bulk_create`` drop a duplicate; that row stays in the
    count.
    """
    channel = require_missive_type(missive_type)
    grouped = group_targets(targets)
    if not grouped:
        return 0

    created = 0
    for model, pairs in grouped.items():
        content_type = ContentType.objects.get_for_model(model)
        for start in range(0, len(pairs), BATCH_SIZE):
            batch = pairs[start : start + BATCH_SIZE]
            # ignore_conflicts alone would keep the rows safe, but not the
            # count: the database does not say which rows it dropped.
            already = set(
                selection_qs(campaign, missive_type=channel, active_only=True)
                .filter(
                    content_type=content_type,
                    object_id__in=[object_id for object_id, _target in batch],
                )
                .values_list("object_id", flat=True)
            )
            rows = [
                CampaignTarget(
                    campaign=campaign,
                    missive_type=channel,
                    content_type=content_type,
                    object_id=object_id,
                    object_str=_label(target),
                )
                for object_id, target in batch
                if object_id not in already
            ]
            if not rows:
                continue
            CampaignTarget.objects.bulk_create(rows, ignore_conflicts=True)
            created += len(rows)
    return created


def unselect(campaign, missive_type: str, targets=None) -> int:
    """Remove live selection rows for ``(campaign, missive_type)``.

    Sent rows stay. Pass *targets* to uncheck those objects only; omit it
    to clear the whole channel. An empty list removes nothing.

    Returns the number of rows deleted.
    """
    qs = selection_qs(campaign, missive_type=missive_type, active_only=True)
    if targets is not None:
        grouped = group_targets(targets)
        if not grouped:
            return 0
        window = Q()
        for model, pairs in grouped.items():
            content_type = ContentType.objects.get_for_model(model)
            window |= Q(
                content_type=content_type,
                object_id__in=[object_id for object_id, _target in pairs],
            )
        qs = qs.filter(window)
    _total, per_model = qs.delete()
    return per_model.get(CampaignTarget._meta.label, 0)


def delete_pending_targets(targets, *, using: str | None = None) -> int:
    """Delete selections without a missive for the supplied business objects.

    This grouped form is intended for bulk cleanup. Rows already linked to a
    missive remain as history, with their saved ``object_str``.
    """
    grouped = group_targets(targets)
    deleted = 0
    manager = CampaignTarget._base_manager.db_manager(using) if using else CampaignTarget._base_manager
    content_types = ContentType.objects.db_manager(using)
    for model, pairs in grouped.items():
        content_type = content_types.get_for_model(model)
        object_ids = [object_id for object_id, _target in pairs]
        for start in range(0, len(object_ids), BATCH_SIZE):
            _total, per_model = manager.filter(
                content_type=content_type,
                object_id__in=object_ids[start : start + BATCH_SIZE],
                missive__isnull=True,
            ).delete()
            deleted += per_model.get(CampaignTarget._meta.label, 0)
    return deleted


def delete_pending_targets_on_delete(sender, instance, using, **kwargs) -> None:
    """``pre_delete`` handler for a model used as a campaign target."""
    if _suppress_target_cleanup.get():
        return
    delete_pending_targets([instance], using=using)


@contextmanager
def suppress_target_cleanup():
    """Skip the per-instance handler while grouped cleanup is in progress."""
    token = _suppress_target_cleanup.set(True)
    try:
        yield
    finally:
        _suppress_target_cleanup.reset(token)


def delete_target_objects(queryset):
    """Delete a queryset and its pending selections with grouped queries.

    Use this instead of ``queryset.delete()`` for a large deletion on a model
    registered with :func:`connect_target_cleanup`.
    """
    using = queryset.db
    with transaction.atomic(using=using):
        targets = list(queryset)
        delete_pending_targets(targets, using=using)
        with suppress_target_cleanup():
            return queryset.delete()


def connect_target_cleanup(*models_to_connect) -> None:
    """Delete pending selections when instances of these models are deleted."""
    for model in models_to_connect:
        pre_delete.connect(
            delete_pending_targets_on_delete,
            sender=model,
            weak=False,
            dispatch_uid=f"django_pymissive.target_cleanup.{model._meta.label_lower}",
        )


def disconnect_target_cleanup(*models_to_disconnect) -> None:
    """Disconnect cleanup previously installed by :func:`connect_target_cleanup`."""
    for model in models_to_disconnect:
        pre_delete.disconnect(
            sender=model,
            dispatch_uid=f"django_pymissive.target_cleanup.{model._meta.label_lower}",
        )


def is_selected(campaign, target, missive_type: str) -> bool:
    """True when *target* has a live (not-yet-materialized) selection row."""
    content_type, object_id = identity(target)
    return (
        selection_qs(
            campaign,
            missive_type=missive_type,
            active_only=True,
        )
        .filter(content_type=content_type, object_id=object_id)
        .exists()
    )


def counts(
    campaign,
    *,
    missive_types=None,
    active_only: bool = False,
) -> dict[str, int]:
    """Return the number of selection rows per missive type.

    One ``GROUP BY``. *missive_types*, when given, is filled with zeroes for
    the types that have no row, in the order it was passed.
    """
    rows = selection_qs(campaign, active_only=active_only).values("missive_type").order_by().annotate(total=Count("id"))
    if missive_types is None:
        return {row["missive_type"]: row["total"] for row in rows}
    result = {require_missive_type(value): 0 for value in missive_types}
    for row in rows:
        if row["missive_type"] in result:
            result[row["missive_type"]] = row["total"]
    return result


def iter_targets(
    campaign,
    missive_type: str,
    *,
    active_only: bool = False,
    chunk_size: int = CHUNK_SIZE,
):
    """Yield selection rows, prefetching the generic target per chunk."""
    qs = selection_qs(campaign, missive_type=missive_type, active_only=active_only)
    yield from iter_chunks(qs, chunk_size=chunk_size)


def iter_chunks(qs, *, chunk_size: int = CHUNK_SIZE):
    """Walk *qs* by primary key and prefetch contacts on each chunk.

    The generic object and the sub-targets are loaded once per chunk, not
    once per row.
    """
    last_pk = 0
    ordered = qs.order_by("pk")
    if hasattr(ordered, "with_contacts"):
        ordered = ordered.with_contacts()
    else:
        ordered = ordered.prefetch_related("target", "to_campaignrecipienttarget")
    while True:
        chunk = list(ordered.filter(pk__gt=last_pk)[:chunk_size])
        if not chunk:
            break
        last_pk = chunk[-1].pk
        yield from chunk


def identity(target):
    """Return ``(content_type, object_id)`` for a saved model instance."""
    model = _require_instance(target)
    return (
        ContentType.objects.get_for_model(model),
        object_id_value(target.pk),
    )


def group_targets(targets) -> dict:
    """Group saved instances by concrete model.

    Each value is a list of ``(object_id, instance)``, deduplicated on the
    primary key. A single instance is accepted, as is a queryset. No label
    is computed here: ``str()`` may hit the database, and only
    :func:`select` stores it.
    """
    grouped: dict = {}
    seen: set = set()
    for target in _iterate(targets):
        model = _require_instance(target)
        object_id = object_id_value(target.pk)
        key = (model._meta.label_lower, object_id)
        if key in seen:
            continue
        seen.add(key)
        grouped.setdefault(model, []).append((object_id, target))
    return grouped


def _iterate(targets):
    if targets is None:
        return []
    if isinstance(targets, models.Model):
        return [targets]
    return targets


def _require_instance(target):
    meta = getattr(target, "_meta", None)
    if meta is None or not getattr(target, "pk", None):
        raise ValueError("targets must be saved model instances")
    return meta.concrete_model


def _label(target) -> str:
    try:
        return str(target)[:500]
    except Exception:
        return ""
