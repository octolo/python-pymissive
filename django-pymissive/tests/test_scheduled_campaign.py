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
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone

from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.scheduler import MissiveScheduledCampaign
from django_pymissive.models.choices import MissiveStatus, MissiveThreadType
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


def test_process_missives_default_send_fn_uses_send_missive():
    """Without a send_fn, process_missives calls missive.send_missive() on each claimed missive."""
    c = _campaign()
    sched = _scheduled(c)
    m = _missive(c, body_html="<p>hi</p>", missive_type="email")
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
