"""Send from the selection table.

:func:`start_selection` enqueues a scheduled run whose backend is
:func:`run_selection`. That task first builds a draft for every
:class:`~django_pymissive.models.campaign_target.CampaignTarget` row, then
sends the run's drafts through the scheduler's own loop. The request that
clicks "send" does not build the missives itself.

Missives are built by ``build_target_processors`` (target, then run, then
campaign, then the setting). An optional *build* dotted path
``(campaign, target, missive_type) -> Missive | None`` becomes the run's
chain. Campaign-sourced fields (subject, body, sender) are filled by
``Missive.send_missive`` from the campaign when the draft left them empty.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from pymissive.config import normalize_missive_type

from ..models.campaign import MissiveCampaign
from ..models.campaign_target import resolve_build_target_processors
from ..models.choices import MissiveStatus
from ..models.missive import Missive
from ..models.scheduler import SELECTION_TASK, MissiveScheduledCampaign
from ..utils import import_allowed_string
from . import drafts as draft_services
from . import targets as target_services

logger = logging.getLogger(__name__)


#: Reasons stored on an abandoned row; plain text so they read the same in
#: every language.
TARGET_DELETED = "Target deleted"
NO_REACHABLE_RECIPIENT = "No reachable recipient"


class CampaignAlreadySending(ValidationError):
    """Raised when a send is requested while one is already running."""


def build_send_preview(campaign, *, missive_types=None) -> dict:
    """Recap of what a send would do, counted on the selection table.

    ``selected`` counts the live checkboxes (no missive yet). Rows already
    linked to a draft are not counted again.
    """
    selected = target_services.counts(
        campaign,
        missive_types=missive_types,
        active_only=True,
    )
    return {
        "missive_types": {channel: {"selected": count} for channel, count in selected.items()},
        "total_selected": sum(selected.values()),
    }


def materialize_selection(
    campaign,
    missive_types,
    *,
    build=None,
    scheduler=None,
    on_row=None,
) -> int:
    """Build a draft for every live selection row of *missive_types*. Sends nothing.

    Returns the number of rows that received a missive. A row whose target
    was deleted, or that the build skips, is abandoned; one the build fails
    on stays a checkbox for the next run. :func:`selection_build` picks the
    build of each row. *scheduler*, when given, owns the drafts so its send
    loop picks them up. *on_row* ``(row) -> bool`` is called before each
    row; returning false stops the build.
    """
    attached = 0
    for channel in _channels(missive_types):
        for row in target_services.iter_targets(
            campaign,
            channel,
            active_only=True,
        ):
            if on_row is not None and on_row(row) is False:
                return attached
            attached += _materialize_target(
                row,
                campaign,
                channel,
                build=build,
                scheduler=scheduler,
            )
    return attached


def _materialize_target(row, campaign, channel, *, build=None, scheduler=None) -> int:
    """Build one active target while holding its database row lock."""
    try:
        with transaction.atomic():
            locked = type(row)._base_manager.select_for_update().get(pk=row.pk)
            if not locked.is_active():
                return 0
            recipient_targets = list(locked.to_campaignrecipienttarget.select_for_update())
            locked._prefetched_objects_cache = {
                "to_campaignrecipienttarget": recipient_targets,
            }
            target = locked.target
            if target is None:
                _abandon(locked, TARGET_DELETED)
                return 0
            missive, _created = draft_services.materialize_missive(
                campaign,
                target,
                channel,
                build=selection_build(
                    locked,
                    build=build,
                    scheduler=scheduler,
                    campaign=campaign,
                ),
                scheduler=scheduler,
            )
            if missive is None:
                _abandon(locked, NO_REACHABLE_RECIPIENT)
                return 0
            locked.attach_missive(missive)
            return 1
    except Exception:
        logger.exception(
            "Campaign %s: build failed for %s on %s",
            campaign.pk,
            row.object_id,
            channel,
        )
        return 0


def _abandon(row, reason: str) -> None:
    if row.abandon(reason):
        logger.warning(
            "Campaign %s: target %s (%s) on %s abandoned: %s",
            row.campaign_id,
            row.object_id,
            row.object_str,
            row.missive_type,
            reason,
        )


def send_target(campaign, target, missive_type: str, *, build=None) -> None:
    """Materialize and send one *target* outside of a scheduled run.

    Raises when a campaign send is already running, or when the build
    returns no missive. :func:`selection_build` picks the build.

    The draft is built, and the selection row pointed at it, under the
    campaign row lock that :func:`start_selection` takes: a run starting
    afterwards no longer sees the row as selected, so it cannot build or
    resend a second missive while this one is being delivered. The provider
    call happens after the lock is released.
    """
    channel = target_services.require_missive_type(missive_type)
    content_type, object_id = target_services.identity(target)
    with transaction.atomic():
        _lock_idle_campaign(campaign)
        row = (
            target_services.selection_qs(campaign, missive_type=channel, active_only=True)
            .filter(content_type=content_type, object_id=object_id)
            .first()
        )
        missive = _materialize_row(campaign, target, channel, row, build=build)
    if missive is None:
        raise ValidationError(
            _("This target has no reachable recipient on this channel."),
        )
    missive.send_missive()


def generate_target(row):
    """Build and attach the draft missive of one selection *row*, without sending it.

    Same campaign lock as :func:`send_target`. Returns the row's missive,
    which may have been attached meanwhile, or ``None`` when the build
    declines the target.
    """
    target = row.target
    if target is None:
        raise ValidationError(_("This target no longer exists."))
    with transaction.atomic():
        _lock_idle_campaign(row.campaign)
        row.refresh_from_db(fields=["missive"])
        if row.missive_id:
            return row.missive
        return _materialize_row(row.campaign, target, row.missive_type, row)


def _lock_idle_campaign(campaign) -> None:
    locked = MissiveCampaign.objects_plain.select_for_update().get(pk=campaign.pk)
    if locked.is_processing:
        raise CampaignAlreadySending(
            _("A campaign send is already in progress."),
        )


def _materialize_row(campaign, target, channel, row, *, build=None):
    chosen = selection_build(row, build=build, campaign=campaign)
    missive, _created = draft_services.materialize_missive(
        campaign,
        target,
        channel,
        build=chosen,
    )
    if missive is not None and row is not None:
        row.attach_missive(missive)
    return missive


def start_selection(campaign, missive_types, *, build: str | None = None):
    """Enqueue a run that sends from :class:`CampaignTarget`.

    *build* is a dotted path, because the worker imports it in another
    process. It becomes the run's ``build_target_processors``;
    without it the run copies the campaign's chain, and an empty one falls
    back to ``settings.PYMISSIVE_DEFAULT_BUILD_TARGET_PROCESSORS``. The
    processing flag is set here: ``start_campaign`` is the other place that
    does it, and calling it would claim draft missives that do not exist yet.
    """
    chosen = _channels(missive_types)
    if not chosen:
        raise ValidationError(_("At least one missive type is required."))
    if build is not None:
        _load_callable(build, "build")
    elif not resolve_build_target_processors(campaign=campaign):
        raise ValidationError(_("No build processor is configured for this target."))

    with transaction.atomic():
        locked = MissiveCampaign.objects_plain.select_for_update().get(pk=campaign.pk)
        locked.release_stale_processing()
        if locked.is_processing:
            raise CampaignAlreadySending(
                _("A campaign send is already in progress."),
            )
        scheduled = locked.to_missivecampaignsend.create(
            scheduled_send_date=timezone.now(),
            external_task_backend=SELECTION_TASK,
            additional_config={"missive_types": chosen},
            build_target_processors=[build] if build else [],
        )
    scheduled.start_scheduled_campaign()
    return scheduled


def run_selection(scheduled_id) -> None:
    """Scheduler entry point: ``callable(scheduled_id)``.

    Two phases. The build creates a draft for every selected target and
    sends nothing. The run's own send loop then sends every draft it owns,
    including the campaign drafts claimed when the run started. Reads
    ``missive_types`` written by :func:`start_selection`; each target's
    build comes from :func:`selection_build`.

    A cancelled run deletes the drafts it left unsent on selection rows,
    which checks those targets again: a row never shows unchecked while a
    draft of it is still waiting for another send.
    """
    scheduled = MissiveScheduledCampaign.objects.select_related("campaign").get(
        id=scheduled_id,
    )

    def on_row(_row) -> bool:
        return not scheduled.checkpoint()

    materialize_selection(
        scheduled.campaign,
        scheduled.selection_channels(),
        scheduler=scheduled,
        on_row=on_row,
    )
    if not scheduled.cancelled_at:
        scheduled.process_missives()
    if scheduled.cancelled_at:
        _release_unsent_targets(scheduled)


def _release_unsent_targets(scheduled) -> None:
    unsent = Missive.objects.filter(
        scheduler=scheduled,
        status=MissiveStatus.DRAFT,
        to_campaigntarget__isnull=False,
    )
    _deleted, per_model = unsent.delete()
    released = per_model.get(Missive._meta.label, 0)
    if released:
        logger.info(
            "Run %s cancelled: %s unsent draft(s) deleted, their targets are selected again",
            scheduled.pk,
            released,
        )


def _channels(missive_types) -> list[str]:
    chosen: list[str] = []
    unknown: list[str] = []
    for raw in missive_types or []:
        key = raw if isinstance(raw, str) else str(raw)
        canonical = normalize_missive_type(key)
        if not canonical:
            unknown.append(key)
            continue
        if canonical not in chosen:
            chosen.append(canonical)
    if unknown:
        raise ValidationError(
            _("Unknown missive types: %(types)s.") % {"types": ", ".join(unknown)},
        )
    return chosen


def selection_build(row, *, build=None, scheduler=None, campaign=None):
    """Return the build callable for one selection row (*row* may be ``None``).

    The chain comes from
    :func:`~django_pymissive.models.campaign_target.resolve_build_target_processors`.
    *build*, given by the caller, only gives way to the row's own chain.
    """
    from ..processors.build_target import build_from_processors

    if build is not None and not getattr(row, "build_target_processors", None):
        return build
    processors = resolve_build_target_processors(row, scheduler=scheduler, campaign=campaign)
    if not processors:
        raise ValidationError(
            _("No build processor is configured for this target."),
        )
    return build_from_processors(processors, row=row)


def _load_callable(path: str, label: str):
    if not isinstance(path, str) or not path.strip():
        raise ValidationError(
            _("%(label)s must be a dotted path.") % {"label": label},
        )
    try:
        found = import_allowed_string(path)
    except ImportError as exc:
        raise ValidationError(
            _("Cannot import %(label)s %(path)s.") % {"label": label, "path": path},
        ) from exc
    if not callable(found):
        raise ValidationError(
            _("%(path)s is not callable.") % {"path": path},
        )
    return found
