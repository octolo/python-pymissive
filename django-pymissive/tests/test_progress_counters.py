"""Grouped counters must not be inflated by the default manager's joins.

``Missive.objects`` annotates counts over reverse FKs (recipients, events,
attachments, related objects). Those LEFT JOINs survive a ``.values()`` added
downstream — it only drops the column, not the join — so a non-distinct
``Count`` stacked on top groups multiplied rows: one missive with 3 recipients
and 4 events is counted 12 times. Every grouped counter therefore has to start
from ``_base_manager``.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from django_pymissive.models import MissiveRecipientEmail, MissiveType
from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.choices import MissiveStatus
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive
from django_pymissive.models.scheduler import MissiveScheduledCampaign

pytestmark = pytest.mark.django_db

RECIPIENTS = 3
EVENTS = 4


def _fat_missive(campaign=None, *, status=MissiveStatus.SUCCESS, scheduler=None, events=EVENTS):
    """A missive carrying enough recipients and events to expose the join fanout."""
    missive = Missive.objects.create(
        campaign=campaign,
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


def test_run_status_breakdown_counts_each_missive_once():
    campaign = MissiveCampaign.objects.create(subject="Test campaign")
    sched = MissiveScheduledCampaign.objects.create(campaign=campaign)
    _fat_missive(campaign, status=MissiveStatus.SUCCESS, scheduler=sched)
    _fat_missive(campaign, status=MissiveStatus.FAILED, scheduler=sched)

    by_status = sched.progress_payload()["by_type"][MissiveType.EMAIL]["by_status"]

    assert by_status[MissiveStatus.SUCCESS] == 1
    assert by_status[MissiveStatus.FAILED] == 1


def test_sync_events_noevent_sees_the_real_event_count():
    """``--noevent`` selects on events only — recipients must not push it over the limit."""
    one_event = _fat_missive(events=1)
    one_event.external_id = "sync-one-event"
    one_event.save(update_fields=["external_id"])

    out = StringIO()
    call_command(
        "sync_events",
        "--date", timezone.now().date().isoformat(),
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
        "--date", timezone.now().date().isoformat(),
        "--noevent",
        stdout=StringIO(),
    )

    assert MissiveEvent.objects.filter(missive=busy).count() == EVENTS
