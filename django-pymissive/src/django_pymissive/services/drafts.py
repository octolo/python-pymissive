"""Build the missive of one selected target, at send time.

Order, same as a hand-prepared campaign:

1. a draft already linked to this target is returned untouched, so content
   edited in the admin is never overwritten;
2. a missive that already left draft is duplicated, keeping the thread;
3. otherwise *build* creates a fresh draft.

*build* is the project's hook. It receives ``(campaign, target,
missive_type)`` and returns a saved :class:`~django_pymissive.models.Missive`,
or ``None`` when the target has no usable contact on that channel.
:func:`build_draft` covers the common case (one recipient, campaign content
filled in at send time).
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q

from ..models.choices import MissiveStatus, MissiveThreadType
from ..models.missive import Missive
from ..models.related_object import MissiveRelatedObject
from .targets import group_targets, identity, require_missive_type


def link_target(missive, target, *, new: bool = False) -> MissiveRelatedObject:
    """Link *missive* to *target*. A second call returns the existing row.

    The link is remembered on the instance, so a build that already linked
    costs no second lookup. *new* skips the lookup for a missive just
    created, which cannot have a link yet.
    """
    content_type, object_id = identity(target)
    links = missive.__dict__.setdefault("_target_links", {})
    key = (content_type.pk, object_id)
    if key in links:
        return links[key]
    link = None
    if not new:
        link = missive.to_missiverelatedobject.filter(
            content_type=content_type,
            object_id=object_id,
        ).first()
    if link is None:
        link = missive.to_missiverelatedobject.create(content_object=target)
    links[key] = link
    return link


def missive_links(target, *, campaign, missive_type: str):
    """``MissiveRelatedObject`` rows of *target* for this campaign and channel.

    Live sends only: a ``HISTORY`` row left by a resend is not a draft to
    reuse, and not the missive to duplicate again.
    """
    content_type, object_id = identity(target)
    return MissiveRelatedObject.objects.filter(
        content_type=content_type,
        object_id=object_id,
        missive__campaign_id=campaign.pk,
        missive__missive_type=require_missive_type(missive_type),
        missive__thread_type=MissiveThreadType.MISSIVE,
    )


def _in_flight_q() -> Q:
    """Claimed by a worker but not handed to the provider yet.

    A submitted missive stays ``processing`` until the provider reports its
    outcome, possibly for days; with an ``external_id`` it already left.
    """
    return Q(missive__status=MissiveStatus.PROCESSING) & (
        Q(missive__external_id__isnull=True) | Q(missive__external_id="")
    )


def existing_draft(campaign, target, missive_type: str) -> Missive | None:
    """Return the draft already prepared for ``(target, missive_type)``."""
    link = (
        missive_links(target, campaign=campaign, missive_type=missive_type)
        .filter(missive__status=MissiveStatus.DRAFT)
        .select_related("missive")
        .order_by("-missive__created_at", "-id")
        .first()
    )
    return link.missive if link else None


def last_sent(campaign, target, missive_type: str) -> Missive | None:
    """Return the most recent missive of ``(target, missive_type)`` that left draft."""
    link = (
        missive_links(target, campaign=campaign, missive_type=missive_type)
        .exclude(missive__status=MissiveStatus.DRAFT)
        .exclude(_in_flight_q())
        .select_related("missive")
        .order_by("-missive__created_at", "-id")
        .first()
    )
    return link.missive if link else None


def materialize_missive(
    campaign,
    target,
    missive_type: str,
    *,
    build,
    scheduler=None,
) -> tuple[Missive | None, bool]:
    """Return the missive to send, building it when none exists yet.

    Returns ``(missive, created)``. ``missive`` is ``None`` when *build*
    declines the target (no reachable contact). ``created`` is false when an
    existing draft was reused. *scheduler*, when given, owns the missive.
    """
    channel = require_missive_type(missive_type)

    draft, previous = _draft_and_last_sent(campaign, target, channel)
    if draft is not None:
        _attach(draft, scheduler=scheduler)
        return draft, False
    if previous is not None:
        return resend_draft(previous, scheduler=scheduler), True

    # The link to the target is what existing_draft finds next time: a
    # missive saved without it would be built a second time.
    with transaction.atomic():
        missive = build(campaign, target, channel)
        if missive is None:
            return None, False
        if missive._state.adding:
            raise ValueError("build() must return a saved missive, or None to skip")
        if missive.missive_type != channel:
            raise ValueError(f"build() returned a {missive.missive_type!r} missive for {channel!r}")
        _attach(missive, campaign=campaign, scheduler=scheduler)
        link_target(missive, target)
    return missive, True


def _draft_and_last_sent(campaign, target, channel) -> tuple[Missive | None, Missive | None]:
    """:func:`existing_draft` and :func:`last_sent` in one query.

    A draft wins over a more recent sent missive, as when they are called
    one after the other.
    """
    links = (
        missive_links(target, campaign=campaign, missive_type=channel)
        .exclude(_in_flight_q())
        .select_related("missive")
        .order_by("-missive__created_at", "-id")
    )
    previous = None
    for link in links:
        if link.missive.status == MissiveStatus.DRAFT:
            return link.missive, None
        if previous is None:
            previous = link.missive
    return None, previous


def _attach(missive, *, campaign=None, scheduler=None) -> None:
    """Give *missive* its campaign and scheduler when missing, in one save."""
    fields = []
    if campaign is not None and not missive.campaign_id:
        missive.campaign = campaign
        fields.append("campaign")
    if scheduler is not None and missive.scheduler_id != scheduler.pk:
        missive.scheduler = scheduler
        fields.append("scheduler")
    if fields:
        missive.save(update_fields=[*fields, "updated_at"])


def resend_draft(missive: Missive, *, scheduler=None) -> Missive:
    """Duplicate a sent *missive* into a fresh draft of the same thread.

    The source becomes ``HISTORY``. ``resend=True`` with ``sync_campaign``
    rebases the duplicate on the campaign's current configuration.
    ``duplicate_missive`` copies the previous run's scheduler; the draft
    belongs to *scheduler* instead, or to no run so the next one claims it.
    """
    with transaction.atomic():
        missive.thread_type = MissiveThreadType.HISTORY
        missive.save(update_fields=["thread_type"])
        duplicate = missive.duplicate_missive(
            thread_type=MissiveThreadType.MISSIVE,
            thread_id=missive.thread_id,
            resend=True,
            sync_campaign=True,
        )
        wanted = scheduler.pk if scheduler is not None else None
        if duplicate.scheduler_id != wanted:
            duplicate.scheduler = scheduler
            duplicate.save(update_fields=["scheduler"])
    return duplicate


def build_draft(
    campaign,
    target,
    missive_type: str,
    *,
    name: str = "",
    email: str | None = None,
    phone: str | None = None,
    address=None,
    notification_id: str | None = None,
    recipient_type: str | None = None,
    subject: str | None = None,
    body_rich: str | None = None,
    body_text: str | None = None,
    provider: str | None = None,
    metadata: dict | None = None,
    extra_missive_fields: dict | None = None,
) -> Missive | None:
    """Create one draft missive with a single recipient, linked to *target*.

    Returns ``None`` when the contact field of this channel is empty. Subject
    and body may stay empty: ``Missive.send_missive`` copies them from the
    campaign when the missive itself has none.

    The caller (usually the *build* hook of :func:`materialize_missive`) owns
    where the address, phone or email comes from.
    """
    from ..shortcuts import send_missive
    from pymissive.config import missive_support_for_type

    channel = require_missive_type(missive_type)
    support = missive_support_for_type(channel)
    contact = {
        "email": email,
        "phone": phone,
        "address": address,
        "application": notification_id,
    }.get(support)
    if contact in (None, ""):
        return None

    missive = send_missive(
        channel,
        name=name,
        email=email,
        phone=phone,
        address=address,
        notification_id=notification_id,
        subject=subject,
        body_rich=body_rich,
        body_text=body_text,
        campaign=campaign,
        provider=provider,
        extra_missive_fields=extra_missive_fields,
        extra_recipient_fields={"recipient_type": recipient_type} if recipient_type else None,
        and_send=False,
    )
    if metadata:
        missive.metadata = {**(missive.metadata or {}), **metadata}
        missive.save(update_fields=["metadata"])
    link_target(missive, target, new=True)
    return missive


def delete_drafts(campaign, missive_type: str, *, targets=None) -> int:
    """Delete the draft missives of a campaign channel.

    Selection rows that pointed at them become checkboxes again, through
    :func:`~django_pymissive.models.campaign_target.release_or_delete_target`.

    Returns the number of missives deleted.
    """
    channel = require_missive_type(missive_type)
    qs = MissiveRelatedObject.objects.filter(
        missive__campaign_id=campaign.pk,
        missive__status=MissiveStatus.DRAFT,
        missive__missive_type=channel,
        missive__thread_type=MissiveThreadType.MISSIVE,
    )
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

    missive_ids = list(qs.values_list("missive_id", flat=True).distinct())
    if not missive_ids:
        return 0

    Missive.objects.filter(pk__in=missive_ids).delete()
    return len(missive_ids)
