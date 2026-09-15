"""Tests for MissiveScheduledCampaign — runners, tracking, safety guards.

Covers:
- can_send (4 logical cases)
- get_missives + missive_type filter
- claim_missive / iter_claimed_missives (atomic anti-double-send)
- process_missives (best-effort: batch continues, failing missive → ERROR)
- run_with_tracking (atomic send_date claim, ended_at, last_error, processing flag)
- run_campaign dispatch: built-in / task_object / external_task_backend
- clean() validation: backend allowlist, private run_method, kwargs not a dict
- fakeapp runner (hook injected via external_task_backend)
- with_counts: per-status and per-type live annotations
- duplicate_missive does not copy the scheduler FK
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone

from django_pymissive.managers.scheduler import count_annotations
from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.scheduler import MissiveScheduledCampaign
from django_pymissive.models.choices import MissiveEventType, MissiveStatus, MissiveThreadType
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive
from tests.fakeapp.models import Contact

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _campaign(**kw) -> MissiveCampaign:
    return MissiveCampaign.objects.create(subject="Test campaign", **kw)


def _missive(campaign, *, missive_type="email", status=MissiveStatus.DRAFT, **kw) -> Missive:
    return Missive.objects.create(
        campaign=campaign,
        missive_type=missive_type,
        subject="Test missive",
        status=status,
        **kw,
    )


def _scheduled(campaign, **kw) -> MissiveScheduledCampaign:
    return MissiveScheduledCampaign.objects.create(campaign=campaign, **kw)


# ---------------------------------------------------------------------------
# can_send
# ---------------------------------------------------------------------------


def test_can_send_true_when_not_started_no_scheduled_date():
    sched = _scheduled(_campaign())
    assert sched.can_send is True


def test_can_send_true_when_scheduled_date_in_past():
    past = timezone.now() - timezone.timedelta(hours=1)
    sched = _scheduled(_campaign(), scheduled_send_date=past)
    assert sched.can_send is True


def test_can_send_false_when_scheduled_date_in_future():
    future = timezone.now() + timezone.timedelta(hours=1)
    sched = _scheduled(_campaign(), scheduled_send_date=future)
    assert sched.can_send is False


def test_can_send_false_when_already_started():
    sched = _scheduled(_campaign())
    MissiveScheduledCampaign.objects.filter(pk=sched.pk).update(send_date=timezone.now())
    sched.refresh_from_db()
    assert sched.can_send is False


def test_can_send_false_when_already_ended():
    sched = _scheduled(_campaign())
    MissiveScheduledCampaign.objects.filter(pk=sched.pk).update(ended_at=timezone.now())
    sched.refresh_from_db()
    assert sched.can_send is False


# ---------------------------------------------------------------------------
# get_missives
# ---------------------------------------------------------------------------


def test_get_missives_returns_only_draft():
    c = _campaign()
    sched = _scheduled(c)
    _missive(c, status=MissiveStatus.DRAFT)
    _missive(c, status=MissiveStatus.SUCCESS)
    _missive(c, status=MissiveStatus.PROCESSING)
    assert sched.get_missives().count() == 1


def test_get_missives_wildcard_returns_all_types():
    c = _campaign()
    sched = _scheduled(c)  # missive_type = "*" by default
    _missive(c, missive_type="email")
    _missive(c, missive_type="sms")
    assert sched.get_missives().count() == 2


def test_get_missives_filtered_by_type():
    c = _campaign()
    sched = _scheduled(c, missive_type="email")
    _missive(c, missive_type="email")
    _missive(c, missive_type="sms")
    qs = sched.get_missives()
    assert qs.count() == 1
    assert qs.first().missive_type == "email"


# ---------------------------------------------------------------------------
# claim_missive
# ---------------------------------------------------------------------------


def test_claim_missive_flips_draft_to_processing():
    c = _campaign()
    m = _missive(c)
    assert MissiveScheduledCampaign.claim_missive(m) is True
    m.refresh_from_db()
    assert m.status == MissiveStatus.PROCESSING


def test_claim_missive_returns_false_if_already_processing():
    c = _campaign()
    m = _missive(c, status=MissiveStatus.PROCESSING)
    assert MissiveScheduledCampaign.claim_missive(m) is False


def test_claim_missive_concurrent_safe():
    """Second claim on the same missive returns False."""
    c = _campaign()
    m = _missive(c)
    first = MissiveScheduledCampaign.claim_missive(m)
    second = MissiveScheduledCampaign.claim_missive(m)
    assert first is True
    assert second is False


# ---------------------------------------------------------------------------
# iter_claimed_missives
# ---------------------------------------------------------------------------


def test_iter_claimed_missives_yields_only_draft():
    c = _campaign()
    sched = _scheduled(c)
    draft = _missive(c)
    _missive(c, status=MissiveStatus.PROCESSING)
    claimed = list(sched.iter_claimed_missives())
    assert len(claimed) == 1
    assert claimed[0].pk == draft.pk


def test_iter_claimed_missives_skips_already_claimed():
    c = _campaign()
    sched = _scheduled(c)
    m = _missive(c)
    # Pre-claim as if another run took it.
    Missive.objects.filter(pk=m.pk).update(status=MissiveStatus.PROCESSING)
    claimed = list(sched.iter_claimed_missives())
    assert claimed == []


# ---------------------------------------------------------------------------
# process_missives — best-effort
# ---------------------------------------------------------------------------


def test_process_missives_calls_send_fn_for_each_missive():
    c = _campaign()
    sched = _scheduled(c)
    _missive(c)
    _missive(c)
    sent = []
    sched.process_missives(lambda m: sent.append(m.pk))
    assert len(sent) == 2


def test_process_missives_continues_after_failure():
    c = _campaign()
    sched = _scheduled(c)
    m1 = _missive(c)
    m2 = _missive(c)
    sent = []

    def _send(m):
        if m.pk == m1.pk:
            raise RuntimeError("provider timeout")
        sent.append(m.pk)

    failures = sched.process_missives(_send)
    # batch continues — m2 is sent
    assert m2.pk in sent
    assert len(failures) == 1
    assert failures[0][0] == m1.pk
    assert "provider timeout" in failures[0][1]


def test_process_missives_marks_failing_missive_error():
    c = _campaign()
    sched = _scheduled(c)
    m = _missive(c)

    sched.process_missives(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

    m.refresh_from_db()
    assert m.status == MissiveStatus.ERROR
    assert "boom" in (m.additional_config or {}).get("last_error", "")
    events = list(MissiveEvent.objects.filter(missive=m))
    assert len(events) == 1
    assert events[0].event == MissiveEventType.ERROR
    assert events[0].trace.get("error") == "boom"


def test_process_missives_default_send_fn_uses_send_missive():
    """Without a send_fn, process_missives calls missive.send_missive() on each claimed missive."""
    c = _campaign()
    sched = _scheduled(c)
    m = _missive(c, body_rich="<p>hi</p>", missive_type="email")
    called = []

    with patch.object(Missive, "send_missive", lambda self: called.append(self.pk)):
        sched.process_missives()

    assert m.pk in called


# ---------------------------------------------------------------------------
# run_with_tracking
# ---------------------------------------------------------------------------


def test_run_with_tracking_sets_send_date_and_ended_at():
    c = _campaign()
    sched = _scheduled(c)
    sched.process_missives = lambda send_fn=None: []  # no-op
    with patch.object(sched, "run_campaign"):
        sched.run_with_tracking()
    sched.refresh_from_db()
    assert sched.send_date is not None
    assert sched.ended_at is not None


def test_run_with_tracking_idempotent_on_double_call():
    """Second call does nothing — claim returns 0 rows."""
    c = _campaign()
    sched = _scheduled(c)
    call_count = []
    original = MissiveScheduledCampaign.run_campaign

    def _counting_run(self):
        call_count.append(1)

    with patch.object(MissiveScheduledCampaign, "run_campaign", _counting_run):
        sched.run_with_tracking()
        sched.run_with_tracking()  # second call — already claimed

    assert len(call_count) == 1


def test_campaign_snapshot_empty_until_run():
    sched = _scheduled(_campaign())
    assert sched.campaign_snapshot == {}


def test_campaign_snapshot_frozen_at_run():
    """The run stores the campaign as it was when sending started."""
    c = _campaign(
        email_body_text="Hello",
        additional_config={"watermark": True},
        additional_context={"offer": "spring"},
        body_processors=["some.processor"],
    )
    sched = _scheduled(c)
    with patch.object(sched, "run_campaign"):
        sched.run_with_tracking()

    sched.refresh_from_db()
    snap = sched.campaign_snapshot
    assert snap["subject"] == "Test campaign"
    assert snap["email_body_text"] == "Hello"
    assert snap["additional_config"] == {"watermark": True}
    assert snap["additional_context"] == {"offer": "spring"}
    assert snap["body_processors"] == ["some.processor"]
    assert snap["id"] == str(c.pk)
    assert "processing" not in (snap.get("metadata") or {})

    c.subject = "Changed subject"
    c.email_body_text = "Goodbye"
    c.save(update_fields=["subject", "email_body_text"])
    sched.run_with_tracking()
    sched.refresh_from_db()
    assert sched.campaign_snapshot["subject"] == "Test campaign"
    c.refresh_from_db()
    assert c.subject == "Changed subject"


def test_campaign_snapshot_json_safe():
    """Phone / address / UUID values round-trip through JSON."""
    import json

    c = _campaign(sender_phone="+33600000000")
    snap = c.to_snapshot()
    json.dumps(snap)
    assert isinstance(snap["id"], str)
    assert isinstance(snap["sender_phone"], str)
    assert isinstance(snap["sender_address"], dict)


def test_run_with_tracking_records_error_and_clears_processing():
    c = _campaign()
    c.metadata = {"processing": True}
    c.save(update_fields=["metadata"])
    sched = _scheduled(c)

    def _boom():
        raise RuntimeError("network error")

    with pytest.raises(RuntimeError):
        with patch.object(sched, "run_campaign", side_effect=RuntimeError("network error")):
            sched.run_with_tracking()

    sched.refresh_from_db()
    assert sched.ended_at is not None
    assert sched.campaign_snapshot.get("subject") == "Test campaign"
    assert "network error" in (sched.additional_config or {}).get("last_error", "")
    c.refresh_from_db()
    assert "processing" not in c.metadata


# ---------------------------------------------------------------------------
# run_campaign dispatch
# ---------------------------------------------------------------------------


def test_run_campaign_builtin_loop_sends_drafts():
    """Built-in loop claims and invokes send_missive on each DRAFT missive."""
    c = _campaign()
    sched = _scheduled(c)
    m1 = _missive(c, missive_type="email")
    m2 = _missive(c, missive_type="email")
    called = []

    with patch.object(Missive, "send_missive", lambda self: called.append(self.pk)):
        sched.run_campaign()

    assert set(called) == {m1.pk, m2.pk}


def test_run_campaign_task_object_calls_method():
    c = _campaign()
    contact = Contact.objects.create(
        first_name="Alice", last_name="Test", email="alice@test.com"
    )
    ct = ContentType.objects.get_for_model(Contact)
    sched = _scheduled(
        c,
        task_content_type=ct,
        task_object_id=contact.pk,
        task_object_arguments={"run_method": "run_campaign_contact"},
    )
    called = []
    with patch.object(Contact, "run_campaign_contact", lambda self, sid, **kw: called.append(sid)):
        sched.run_campaign()
    assert sched.id in called


def test_run_campaign_external_task_backend(settings):
    """external_task_backend is imported and called with scheduled.id."""
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = ["tests.fakeapp.run_campaign"]
    c = _campaign()
    sched = _scheduled(
        c,
        external_task_backend="tests.fakeapp.run_campaign.run_fakeapp_campaign",
    )
    _missive(c, missive_type="email")
    called_with = []

    with patch("tests.fakeapp.run_campaign.run_fakeapp_campaign", side_effect=lambda sid, **kw: called_with.append(sid)):
        sched.run_campaign()

    assert called_with == [sched.id]


def test_run_with_tracking_claims_drafts_left_by_an_ended_run():
    """A run created by hand claims what start_campaign would claim."""
    c = _campaign()
    ended = _scheduled(c, ended_at=timezone.now())
    orphan = _missive(c, scheduler=ended)
    free = _missive(c)

    sched = _scheduled(c)
    with patch.object(MissiveScheduledCampaign, "run_campaign"):
        sched.run_with_tracking()

    orphan.refresh_from_db()
    free.refresh_from_db()
    assert orphan.scheduler_id == sched.id
    assert free.scheduler_id == sched.id
    assert set(sched.get_missives().values_list("pk", flat=True)) == {orphan.pk, free.pk}


def test_run_with_tracking_leaves_the_drafts_of_an_open_run_alone():
    """Without the claim rule, the fallback swept another run's missives."""
    c = _campaign()
    open_run = _scheduled(c)
    claimed = _missive(c, scheduler=open_run)

    other = _scheduled(c)
    sent = []
    with patch.object(Missive, "send_missive", lambda self: sent.append(self.pk)):
        other.run_with_tracking()

    claimed.refresh_from_db()
    assert sent == []
    assert claimed.status == MissiveStatus.DRAFT
    assert claimed.scheduler_id == open_run.id


def test_run_with_tracking_retry_leaves_send_error_on_its_own_run():
    """retry_failed: a send-time ERROR is archived where it happened, not moved.

    Rewriting ``scheduler`` would hand the failure to the retrying run — which
    never sent it — and wipe it from the report of the run that did.
    """
    c = _campaign()
    old_run = _scheduled(c, ended_at=timezone.now())
    failed = _missive(c, status=MissiveStatus.ERROR, missive_type="email")
    failed.scheduler = old_run
    failed.save(update_fields=["scheduler"])

    sched = _scheduled(c, retry_failed=True)
    with patch.object(MissiveScheduledCampaign, "run_campaign"):
        sched.run_with_tracking()

    failed.refresh_from_db()
    assert failed.thread_type == MissiveThreadType.HISTORY
    assert failed.status == MissiveStatus.ERROR
    assert failed.scheduler_id == old_run.id

    dups = Missive.objects.filter(campaign=c, status=MissiveStatus.DRAFT, scheduler=sched)
    assert dups.count() == 1
    assert dups.first().thread_id == failed.thread_id

    annotated = MissiveScheduledCampaign.objects.with_counts().get(pk=old_run.pk)
    assert annotated.count_missive_error == 1
    assert annotated.count_thread_history == 1


def test_run_with_tracking_retry_duplicates_error_missives_at_claim():
    """retry_failed: error missives are duplicated as fresh DRAFTs at claim time."""
    c = _campaign()
    # A previous run that dispatched the failed missive.
    old_run = _scheduled(c)
    failed = _missive(c, status=MissiveStatus.FAILED, missive_type="email")
    failed.scheduler = old_run
    failed.save(update_fields=["scheduler"])

    sched = _scheduled(c, retry_failed=True)
    with patch.object(MissiveScheduledCampaign, "run_campaign"):
        sched.run_with_tracking()

    # original is archived as HISTORY, its (old) scheduler FK untouched
    failed.refresh_from_db()
    assert failed.thread_type == MissiveThreadType.HISTORY
    assert failed.scheduler_id == old_run.id

    # a fresh DRAFT duplicate is attached to the NEW scheduler
    dups = Missive.objects.filter(
        campaign=c, status=MissiveStatus.DRAFT, scheduler=sched
    )
    assert dups.count() == 1
    assert dups.first().thread_id == failed.thread_id


def test_run_with_tracking_retry_also_sends_the_pending_drafts():
    """``retry_failed`` adds the retries, it does not replace the payload.

    The claim used to be skipped as soon as the run had missives — and
    ``_retry_error_missives`` had just given it some, so a run with the option on
    sent only its retries and left the campaign's fresh drafts with no run at
    all: never sent, and no error to show for it.
    """
    c = _campaign()
    ended = _scheduled(c, ended_at=timezone.now())
    failed = _missive(c, status=MissiveStatus.FAILED, missive_type="email")
    failed.scheduler = ended
    failed.save(update_fields=["scheduler"])
    fresh = [_missive(c, missive_type="email") for _ in range(2)]

    sched = _scheduled(c, retry_failed=True)
    sent = []
    with patch.object(Missive, "send_missive", lambda self: sent.append(self.pk)):
        sched.run_with_tracking()

    # The two drafts and the retry of the failure, all three dispatched.
    assert len(sent) == 3
    for missive in fresh:
        missive.refresh_from_db()
        assert missive.scheduler_id == sched.id
    assert not Missive.objects.filter(
        campaign=c, status=MissiveStatus.DRAFT, scheduler__isnull=True,
    ).exists()


def test_run_with_tracking_retry_does_not_reclaim_its_own_retry_drafts():
    """The unconditional claim is idempotent: an open run's drafts are its own."""
    c = _campaign()
    _missive(c, status=MissiveStatus.FAILED, missive_type="email")

    sched = _scheduled(c, retry_failed=True)
    with patch.object(MissiveScheduledCampaign, "run_campaign"):
        sched.run_with_tracking()

    # One archived attempt, one duplicate — the claim did not duplicate again.
    assert Missive.objects.filter(campaign=c).count() == 2
    assert sched.to_missive.count() == 1


def test_run_with_tracking_retry_processed_generically_by_backend():
    """The duplicated DRAFT is sent by run_campaign (built-in loop) like any draft."""
    c = _campaign()
    _missive(c, status=MissiveStatus.FAILED, missive_type="email")
    sched = _scheduled(c, retry_failed=True)

    called = []
    with patch.object(Missive, "send_missive", lambda self: called.append(self.pk)):
        sched.run_with_tracking()

    # the retry duplicate was claimed and sent
    assert len(called) == 1


def test_run_with_tracking_retry_generic_via_external_backend(settings):
    """Retry duplicates are sent by ANY backend, not just the built-in loop.

    The duplication happens in run_with_tracking before run_campaign dispatches,
    so an external_task_backend (here the fakeapp runner) processes the retry
    duplicate generically — proven by the hook processor the runner injects.
    """
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = ["tests.fakeapp.run_campaign"]
    c = _campaign()
    _missive(c, status=MissiveStatus.FAILED, missive_type="email")
    sched = _scheduled(
        c,
        retry_failed=True,
        external_task_backend="tests.fakeapp.run_campaign.run_fakeapp_campaign",
    )

    sent = []
    with patch.object(Missive, "send_missive", lambda self: sent.append(self.pk)):
        sched.run_with_tracking()

    # the retry duplicate flowed through the external backend and got sent
    assert len(sent) == 1
    dup = Missive.objects.get(pk=sent[0])
    assert dup.scheduler_id == sched.id
    # the fakeapp runner injected its hook processor before sending
    assert "tests.fakeapp.hook.add_fake_text" in (dup.body_processors or [])


def test_run_with_tracking_retry_generic_via_task_object():
    """Retry duplicates are also processed via a task_object delegate (fakeapp Contact)."""
    c = _campaign()
    _missive(c, status=MissiveStatus.FAILED, missive_type="email")
    contact = Contact.objects.create(
        first_name="Carol", last_name="Test", email="carol@test.com"
    )
    ct = ContentType.objects.get_for_model(Contact)
    sched = _scheduled(
        c,
        retry_failed=True,
        task_content_type=ct,
        task_object_id=contact.pk,
        task_object_arguments={"run_method": "run_campaign_contact"},
    )

    sent = []
    with patch.object(Missive, "send_missive", lambda self: sent.append(self.pk)):
        sched.run_with_tracking()

    assert len(sent) == 1
    dup = Missive.objects.get(pk=sent[0])
    assert dup.scheduler_id == sched.id
    assert "tests.fakeapp.hook.add_fake_text" in (dup.body_processors or [])


def test_run_with_tracking_no_retry_leaves_errors_untouched():
    """Without retry_failed, error missives are not duplicated."""
    c = _campaign()
    failed = _missive(c, status=MissiveStatus.FAILED, missive_type="email")
    sched = _scheduled(c)  # retry_failed defaults to False
    with patch.object(MissiveScheduledCampaign, "run_campaign"):
        sched.run_with_tracking()

    failed.refresh_from_db()
    assert failed.thread_type == MissiveThreadType.MISSIVE
    assert Missive.objects.filter(campaign=c).count() == 1


def test_run_campaign_raises_if_task_object_deleted():
    c = _campaign()
    contact = Contact.objects.create(
        first_name="Bob", last_name="Test", email="bob@test.com"
    )
    ct = ContentType.objects.get_for_model(Contact)
    sched = _scheduled(c, task_content_type=ct, task_object_id=contact.pk)
    contact.delete()
    with pytest.raises(ValidationError, match="no longer exists"):
        sched.run_campaign()


# ---------------------------------------------------------------------------
# clean() validation
# ---------------------------------------------------------------------------


def test_clean_rejects_disallowed_backend(settings):
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = ["myapp.tasks"]
    sched = MissiveScheduledCampaign(
        campaign=_campaign(),
        external_task_backend="evilapp.run",
    )
    with pytest.raises(ValidationError, match="not allowed"):
        sched.clean()


def test_clean_allows_backend_by_prefix(settings):
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = ["myapp.tasks"]
    sched = MissiveScheduledCampaign(
        campaign=_campaign(),
        external_task_backend="myapp.tasks.send_campaign",
    )
    sched.clean()  # must not raise


def test_clean_allows_any_backend_when_setting_is_none(settings):
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = None
    sched = MissiveScheduledCampaign(
        campaign=_campaign(),
        external_task_backend="anything.goes",
    )
    sched.clean()  # must not raise


def test_clean_rejects_private_run_method():
    sched = MissiveScheduledCampaign(
        campaign=_campaign(),
        task_object_arguments={"run_method": "_delete"},
    )
    with pytest.raises(ValidationError, match="private"):
        sched.clean()


def test_clean_rejects_kwargs_not_dict():
    sched = MissiveScheduledCampaign(
        campaign=_campaign(),
        task_object_arguments={"kwargs": "not-a-dict"},
    )
    with pytest.raises(ValidationError, match="dict"):
        sched.clean()


def test_clean_passes_with_valid_kwargs():
    sched = MissiveScheduledCampaign(
        campaign=_campaign(),
        task_object_arguments={"run_method": "run_campaign", "kwargs": {"key": "val"}},
    )
    sched.clean()  # must not raise


# ---------------------------------------------------------------------------
# with_counts / duplicate scheduler
# ---------------------------------------------------------------------------


def test_with_counts_by_status_and_type():
    c = _campaign()
    sched = _scheduled(c)
    _missive(c, missive_type="email", status=MissiveStatus.SUCCESS, scheduler=sched)
    _missive(c, missive_type="email", status=MissiveStatus.DRAFT, scheduler=sched)
    _missive(c, missive_type="sms", status=MissiveStatus.FAILED, scheduler=sched)
    _missive(c, missive_type="sms", status=MissiveStatus.ERROR, scheduler=sched)
    other = _scheduled(c)
    _missive(c, missive_type="email", status=MissiveStatus.SUCCESS, scheduler=other)
    _missive(c, missive_type="email", status=MissiveStatus.SUCCESS)

    annotated = MissiveScheduledCampaign.objects.with_counts().get(pk=sched.pk)
    assert annotated.count_total == 4
    assert annotated.count_sent == 3
    assert annotated.count_error == 2
    assert annotated.count_missive_success == 1
    assert annotated.count_missive_draft == 1
    assert annotated.count_missive_failed == 1
    assert annotated.count_missive_error == 1
    assert annotated.count_total_email == 2
    assert annotated.count_sent_email == 1
    assert annotated.count_error_email == 0
    assert annotated.count_total_sms == 2
    assert annotated.count_error_sms == 2

    counts = sched.counts_by_type(only_active=True)
    assert set(counts) == {"email", "sms"}
    assert counts["sms"]["error"] == 2
    assert sched.counts_by_status(only_active=True) == {
        MissiveStatus.SUCCESS: 1,
        MissiveStatus.DRAFT: 1,
        MissiveStatus.FAILED: 1,
        MissiveStatus.ERROR: 1,
    }

    payload = sched.progress_payload()
    assert payload["by_status"][MissiveStatus.SUCCESS]["count"] == 1
    assert "label" in payload["by_status"][MissiveStatus.SUCCESS]
    assert payload["by_type"]["email"]["by_status"][MissiveStatus.SUCCESS] == 1
    assert payload["by_type"]["sms"]["by_status"][MissiveStatus.FAILED] == 1


def test_every_counter_reaches_a_non_annotated_instance():
    """The fallback reads the very enumeration ``with_counts()`` applies.

    Listing those names a second time is how ``count_support_*`` used to answer 0
    on an instance fetched without ``with_counts()`` — a plausible zero, not an
    error.
    """
    c = _campaign()
    sched = _scheduled(c)
    _missive(c, missive_type="email", status=MissiveStatus.SUCCESS, scheduler=sched)
    _missive(c, missive_type="sms", status=MissiveStatus.DRAFT, scheduler=sched)

    plain = MissiveScheduledCampaign.objects.get(pk=sched.pk)
    assert plain._count("count_support_email") == 1
    assert plain._count("count_support_email_sent") == 1
    assert plain._count("count_support_phone_sent") == 0

    annotated = MissiveScheduledCampaign.objects.with_counts().get(pk=sched.pk)
    names = MissiveScheduledCampaign._count_fields()
    assert set(names) == set(count_annotations())
    for name in names:
        assert plain._count(name) == getattr(annotated, name), name


def test_with_counts_sees_a_missive_whose_type_is_off_the_registry():
    """The overall counters are aggregated, not summed from the per-type buckets.

    A type never set — or left behind by a renamed one in ``MISSIVE_TYPES`` —
    belongs to no bucket, and used to make the missive invisible to the run
    while the campaign still counted it.
    """
    c = _campaign()
    sched = _scheduled(c)
    _missive(c, missive_type="", status=MissiveStatus.SUCCESS, scheduler=sched)
    _missive(c, missive_type="email", status=MissiveStatus.DRAFT, scheduler=sched)

    annotated = MissiveScheduledCampaign.objects.with_counts().get(pk=sched.pk)
    assert annotated.count_total == 2
    assert annotated.count_sent == 1
    assert annotated.progress == 50
    assert MissiveCampaign.objects.get(pk=c.pk).count_missive == 2
    # The breakdown only knows the configured types — that gap is the detector.
    assert annotated.count_total_email == 1


def test_finished_run_keeps_the_failures_a_later_retry_archived():
    """The report of a run is a log: a retry elsewhere must not empty it."""
    c = _campaign()
    ended = _scheduled(c, ended_at=timezone.now())
    _missive(c, status=MissiveStatus.SUCCESS, scheduler=ended)
    _missive(c, status=MissiveStatus.FAILED, scheduler=ended)

    before = MissiveScheduledCampaign.objects.with_counts().get(pk=ended.pk)
    assert (before.count_total, before.count_sent, before.count_missive_failed) == (2, 2, 1)

    retry = _scheduled(c, retry_failed=True)
    with patch.object(MissiveScheduledCampaign, "run_campaign"):
        retry.run_with_tracking()

    after = MissiveScheduledCampaign.objects.with_counts().get(pk=ended.pk)
    # The archived attempt leaves the live set — it is the retry's job now...
    assert after.count_total == 1
    # ...but the run that produced the failure still reports it.
    assert after.count_missive_failed == 1
    assert after.count_thread_history == 1
    assert after.counts_by_status(only_active=True)[MissiveStatus.FAILED] == 1
    assert MissiveScheduledCampaign.objects.get(pk=ended.pk).history_count == 1


def test_ended_run_emptied_by_a_newer_one_reads_as_complete():
    """A finished run whose leftover draft was reclaimed is done, not at 0%."""
    c = _campaign()
    ended = _scheduled(c, ended_at=timezone.now())
    leftover = _missive(c, status=MissiveStatus.DRAFT, scheduler=ended)

    assert MissiveScheduledCampaign.objects.get(pk=ended.pk).progress == 0

    newer = _scheduled(c)
    with patch.object(MissiveScheduledCampaign, "run_campaign"):
        newer.run_with_tracking()

    leftover.refresh_from_db()
    assert leftover.scheduler_id == newer.id
    reloaded = MissiveScheduledCampaign.objects.get(pk=ended.pk)
    assert (reloaded.total_count, reloaded.progress) == (0, 100)


def test_duplicate_missive_clears_scheduler():
    c = _campaign()
    sched = _scheduled(c)
    source = _missive(c, status=MissiveStatus.SUCCESS, scheduler=sched)

    dup = source.duplicate_missive()

    assert dup.scheduler_id is None
    source.refresh_from_db()
    assert source.scheduler_id == sched.id
    assert MissiveScheduledCampaign.objects.with_counts().get(pk=sched.pk).count_total == 1


# ---------------------------------------------------------------------------
# Stale PROCESSING / crashed run bail
# ---------------------------------------------------------------------------


def _age(obj, **fields):
    """Backdate ``updated_at`` (and any extra fields) past the heartbeat timeout."""
    past = timezone.now() - timezone.timedelta(hours=2)
    fields.setdefault("updated_at", past)
    type(obj).objects.filter(pk=obj.pk).update(**fields)
    obj.refresh_from_db()
    return past


def test_get_missives_reclaims_stale_processing_without_external_id():
    c = _campaign()
    sched = _scheduled(c)
    stuck = _missive(c, status=MissiveStatus.PROCESSING, scheduler=sched)
    _age(stuck)
    assert sched.get_missives().filter(pk=stuck.pk).exists()
    stuck.refresh_from_db()
    assert stuck.status == MissiveStatus.DRAFT


def test_get_missives_leaves_fresh_processing_alone():
    c = _campaign()
    sched = _scheduled(c)
    live = _missive(c, status=MissiveStatus.PROCESSING, scheduler=sched)
    assert not sched.get_missives().filter(pk=live.pk).exists()
    live.refresh_from_db()
    assert live.status == MissiveStatus.PROCESSING


def test_stale_processing_with_external_id_is_not_reset_to_draft():
    c = _campaign()
    sched = _scheduled(c)
    sent = _missive(
        c, status=MissiveStatus.PROCESSING, scheduler=sched, external_id="prov-1"
    )
    _age(sent)
    assert not sched.get_missives().filter(pk=sent.pk).exists()
    sent.refresh_from_db()
    assert sent.status == MissiveStatus.PROCESSING


def test_start_campaign_rejects_a_live_processing_run():
    c = _campaign(metadata={"processing": True})
    _scheduled(c, send_date=timezone.now())
    with pytest.raises(ValidationError, match="already"):
        c.start_campaign()


def test_start_campaign_bails_a_stale_run_and_reopens_missives():
    c = _campaign(metadata={"processing": True})
    past = timezone.now() - timezone.timedelta(hours=2)
    run = _scheduled(c, send_date=past)
    _age(run, send_date=past)
    stuck = _missive(c, status=MissiveStatus.PROCESSING, scheduler=run)
    _age(stuck)

    with patch.object(MissiveScheduledCampaign, "start_scheduled_campaign"):
        c.start_campaign()

    run.refresh_from_db()
    assert run.ended_at is not None
    assert "heartbeat" in (run.additional_config or {}).get("last_error", "")
    stuck.refresh_from_db()
    assert stuck.status == MissiveStatus.DRAFT
    c.refresh_from_db()
    assert c.metadata.get("processing") is True
    assert c.to_missivecampaignsend.exclude(pk=run.pk).exists()


def test_run_with_tracking_finalizes_when_reentered_stale():
    c = _campaign(metadata={"processing": True})
    past = timezone.now() - timezone.timedelta(hours=2)
    sched = _scheduled(c, send_date=past)
    _age(sched, send_date=past)
    with patch.object(MissiveScheduledCampaign, "run_campaign") as run_campaign:
        sched.run_with_tracking()
    run_campaign.assert_not_called()
    sched.refresh_from_db()
    assert sched.ended_at is not None
    c.refresh_from_db()
    assert "processing" not in (c.metadata or {})


def test_process_missives_heartbeats():
    c = _campaign()
    sched = _scheduled(c)
    _missive(c)
    with patch.object(sched, "heartbeat") as heartbeat:
        sched.process_missives(lambda missive: None)
    heartbeat.assert_called()


def test_future_scheduled_run_is_not_stale():
    future = timezone.now() + timezone.timedelta(hours=3)
    sched = _scheduled(_campaign(), scheduled_send_date=future)
    _age(sched)
    assert sched.is_stale is False

