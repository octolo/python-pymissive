"""Grouped counters must not be inflated by leftover reverse-FK joins.

A ``.values()`` added downstream drops annotation columns but keeps their
LEFT JOINs, so a non-distinct ``Count`` stacked on top groups multiplied
rows: one missive with 3 recipients and 4 events is counted 12 times.
Every grouped counter therefore has to start from ``_base_manager``.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django_pymissive.models import MissiveRecipientEmail, MissiveType
from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.campaign_step import CampaignStep
from django_pymissive.models.choices import MissiveStatus, MissiveThreadType
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive
from django_pymissive.models.scheduler import MissiveScheduledCampaign

pytestmark = pytest.mark.django_db

RECIPIENTS = 3
EVENTS = 4


def _fat_missive(campaign=None, *, status=MissiveStatus.SUCCESS, scheduler=None, events=EVENTS):
    """A missive carrying enough recipients and events to expose the join fanout."""
    campaign_step = None
    if campaign is not None:
        campaign_step, _created = CampaignStep.objects.get_or_create(
            campaign=campaign,
            missive_type=MissiveType.EMAIL,
            defaults={"position": 1},
        )
    missive = Missive.objects.create(
        campaign_step=campaign_step,
        scheduler=scheduler,
        missive_type=MissiveType.EMAIL,
        subject="Test missive",
        status=status,
    )
    for i in range(RECIPIENTS):
        MissiveRecipientEmail.objects.create(
            missive=missive,
            name=f"Recipient {i}",
            email=f"recipient{i}@example.com",
        )
    for i in range(events):
        MissiveEvent.objects.create(
            missive=missive,
            event="delivered",
            occurred_at=timezone.now(),
        )
    return missive


def test_campaign_progress_counts_each_missive_once():
    campaign = MissiveCampaign.objects.create(subject="Test campaign")
    _fat_missive(campaign, status=MissiveStatus.SUCCESS)
    _fat_missive(campaign, status=MissiveStatus.SUCCESS)
    _fat_missive(campaign, status=MissiveStatus.DRAFT)
    # sent_missive_q() means "left the pending state", so an error is sent too.
    _fat_missive(campaign, status=MissiveStatus.ERROR)

    payload = campaign.progress_payload()

    assert payload["total_count"] == 4
    assert payload["sent_count"] == 3
    assert payload["error_count"] == 1
    assert payload["progress"] == 75
    by_type = payload["by_type"][MissiveType.EMAIL]
    assert by_type["total"] == 4
    assert by_type["sent"] == 3
    assert by_type["error"] == 1
    assert by_type["progress"] == 75
    assert by_type["by_status"][MissiveStatus.SUCCESS] == 2
    assert by_type["by_status"][MissiveStatus.ERROR] == 1
    assert by_type["by_status"][MissiveStatus.DRAFT] == 1
    assert campaign.counts_by_type(only_active=True)[MissiveType.EMAIL]["sent"] == 3


def test_run_status_breakdown_counts_each_missive_once():
    campaign = MissiveCampaign.objects.create(subject="Test campaign")
    sched = MissiveScheduledCampaign.objects.create(campaign=campaign)
    _fat_missive(campaign, status=MissiveStatus.SUCCESS, scheduler=sched)
    _fat_missive(campaign, status=MissiveStatus.FAILED, scheduler=sched)

    by_status = sched.progress_payload()["by_type"][MissiveType.EMAIL]["by_status"]

    assert by_status[MissiveStatus.SUCCESS] == 1
    assert by_status[MissiveStatus.FAILED] == 1


def test_counts_by_type_matches_the_live_with_counts_counters():
    """The breakdown is ``count_sent`` / ``count_error`` split by type.

    Archived attempts and conversation messages stay in the historical
    counters and out of this one. A legacy empty status counts in the total
    only. A type absent from the registry keeps its own bucket.
    """
    campaign = MissiveCampaign.objects.create(subject="Test campaign")
    _fat_missive(campaign, status=MissiveStatus.SUCCESS)
    _fat_missive(campaign, status=MissiveStatus.FAILED)
    empty = _fat_missive(campaign, status=MissiveStatus.DRAFT)
    empty.status = ""
    empty.save(update_fields=["status"])
    history = _fat_missive(campaign, status=MissiveStatus.FAILED)
    history.thread_type = MissiveThreadType.HISTORY
    history.save(update_fields=["thread_type"])
    message = _fat_missive(campaign, status=MissiveStatus.SUCCESS)
    message.thread_type = MissiveThreadType.MESSAGE
    message.save(update_fields=["thread_type"])
    sms = _fat_missive(campaign, status=MissiveStatus.ERROR)
    sms.missive_type = MissiveType.SMS
    sms.campaign_step, _created = CampaignStep.objects.get_or_create(
        campaign=campaign,
        missive_type=MissiveType.SMS,
        defaults={"position": 2},
    )
    sms.save(update_fields=["missive_type", "campaign_step"])
    unknown = _fat_missive(campaign, status=MissiveStatus.SUCCESS)
    unknown.missive_type = "lre"
    unknown.save(update_fields=["missive_type"])

    annotated = MissiveCampaign.objects.with_counts().get(pk=campaign.pk)
    counts = annotated.counts_by_type()
    # Unknown types still count globally but have no configured annotation.
    assert sum(item["sent"] for item in counts.values()) == annotated.count_sent - 1
    assert sum(item["error"] for item in counts.values()) == annotated.count_error
    email = counts[MissiveType.EMAIL]
    assert email["total"] == 3
    assert email["sent"] == 2
    assert email["error"] == 1
    assert email["by_status"][MissiveStatus.SUCCESS] == 1
    assert email["by_status"][MissiveStatus.FAILED] == 1
    assert email["by_status"][MissiveStatus.DRAFT] == 0
    active = annotated.counts_by_type(only_active=True)
    assert MissiveStatus.DRAFT not in active[MissiveType.EMAIL]["by_status"]
    assert active[MissiveType.EMAIL]["total"] == 3
    assert active[MissiveType.SMS]["error"] == 1
    assert "lre" not in active
    assert "letter" not in active

    with CaptureQueriesContext(connection) as again:
        assert annotated.counts_by_type(only_active=True)[MissiveType.SMS]["error"] == 1
    assert len(again.captured_queries) == 0


def test_prefetch_type_counts_is_one_query_for_the_page():
    first = MissiveCampaign.objects.create(subject="First")
    second = MissiveCampaign.objects.create(subject="Second")
    _fat_missive(first, status=MissiveStatus.SUCCESS)
    _fat_missive(second, status=MissiveStatus.FAILED)
    campaigns = list(
        MissiveCampaign.objects.with_counts(*MissiveCampaign.type_count_fields()).filter(pk__in=(first.pk, second.pk))
    )

    with CaptureQueriesContext(connection) as captured:
        MissiveCampaign.prefetch_type_counts(campaigns)
        assert campaigns[0].counts_by_type(only_active=True)
        assert campaigns[1].counts_by_type(only_active=True)
    assert len(captured.captured_queries) == 1


def test_sync_events_noevent_sees_the_real_event_count():
    """``--noevent`` selects on events only — recipients must not push it over the limit."""
    one_event = _fat_missive(events=1)
    one_event.external_id = "sync-one-event"
    one_event.save(update_fields=["external_id"])

    out = StringIO()
    call_command(
        "sync_events",
        "--date",
        timezone.now().date().isoformat(),
        "--noevent",
        stdout=out,
    )

    assert "1 synced" in out.getvalue()
    assert not MissiveEvent.objects.filter(missive=one_event).exists()


def test_sync_events_noevent_still_skips_a_busy_missive():
    busy = _fat_missive(events=EVENTS)
    busy.external_id = "sync-busy"
    busy.save(update_fields=["external_id"])

    call_command(
        "sync_events",
        "--date",
        timezone.now().date().isoformat(),
        "--noevent",
        stdout=StringIO(),
    )

    assert MissiveEvent.objects.filter(missive=busy).count() == EVENTS
