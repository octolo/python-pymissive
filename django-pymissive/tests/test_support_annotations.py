"""Tests for the support-level counters and the generic missive annotations.

Covers:
- ``pymissive.config`` support vocabulary (aliases, inverse map)
- ``missive_type_filter`` and the shared status predicates
- ``MissiveCampaignManager``: ``count_support_*``, ``count_sent`` / ``_pending``
  / ``_error``, thread scoping, ``has_sent_missives`` / ``has_open_run``
- ``MissiveCampaign``: ``is_processing``, ``can_remove``,
  ``send_preview_payload``, draft reclaim in ``start_campaign``
- ``MissiveQuerySet.with_counts`` / ``BaseMissiveManager.sent_at``
- ``MissiveRecipientManager.targets_by_missive``
- ``MissiveRelatedQuerySetMixin`` on a model of the integration (fakeapp), and
  its batch counterpart ``missive_summaries_by_object``
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from django.db import connection, models
from pymissive.config import GENERIC_SUPPORT

from django_pymissive.managers.campaign import (
    count_annotations as campaign_count_annotations,
    support_count_name,
)
from django_pymissive.managers import related_object as related_object_manager
from django_pymissive.managers.related_object import (
    MissiveRelatedQuerySetMixin,
    missive_related_queryset,
    missive_summaries_by_object,
    object_id_value,
)
from django_pymissive.managers.scheduler import (
    count_annotations as run_count_annotations,
)
from django.contrib.contenttypes.models import ContentType

from django_pymissive.models.attachment import MissiveBaseAttachment
from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.choices import (
    MissiveAttachmentType,
    MissiveStatus,
    MissiveThreadType,
    MissiveType,
    missive_type_filter,
    pending_missive_q,
    sent_missive_q,
)
from django_pymissive.models.missive import Missive
from django_pymissive.models.recipient import MissiveRecipient
from django_pymissive.models.related_object import MissiveRelatedObject
from django_pymissive.models.scheduler import MissiveScheduledCampaign
from tests.fakeapp.models import Contact

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _campaign(**kw) -> MissiveCampaign:
    return MissiveCampaign.objects.create(subject="Test campaign", **kw)


def _missive(campaign=None, *, missive_type="email", status=MissiveStatus.DRAFT, **kw) -> Missive:
    return Missive.objects.create(
        campaign=campaign,
        missive_type=missive_type,
        subject="Test missive",
        status=status,
        **kw,
    )


def _contact(**kw) -> Contact:
    defaults = {
        "last_name": "Martin",
        "first_name": "Alice",
        "email": f"{uuid.uuid4().hex}@example.com",
    }
    return Contact.objects.create(**{**defaults, **kw})


def _link(missive, contact) -> MissiveRelatedObject:
    return MissiveRelatedObject.objects.create(missive=missive, content_object=contact)


def _annotated(campaign) -> MissiveCampaign:
    return MissiveCampaign.objects.get(pk=campaign.pk)


def _with_counts(campaign) -> MissiveCampaign:
    return MissiveCampaign.objects.with_counts().get(pk=campaign.pk)


# ---------------------------------------------------------------------------
# Support vocabulary (pymissive.config)
# ---------------------------------------------------------------------------

def test_postal_is_neither_a_type_nor_a_support():
    """``postal`` is preview chrome; the simple-mail type is ``letter``."""
    from pymissive.config import MISSIVE_TYPES, normalize_support

    assert "postal" not in MISSIVE_TYPES
    assert normalize_support("postal") == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("address", "address"),
        ("registered_letter", "address"),
        ("letter", "address"),
        ("postal", ""),
        ("courrier", ""),
        ("hand-delivery", "address"),
        ("hand_delivery", "address"),
        ("sms", "phone"),
        ("ere", "email"),
        ("app", ""),
        ("notification", "application"),
        ("nope", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_support(value, expected):
    from pymissive.config import normalize_support

    assert normalize_support(value) == expected


def test_missive_types_for_support_covers_every_address_flavour():
    from pymissive.config import missive_types_for_support

    assert set(missive_types_for_support("address")) == {"letter", "registered_letter", "hand_delivery"}


def test_missive_type_filter_prefix_and_unknown_support():
    assert missive_type_filter("email") == {
        "missive_type__in": ["email", "email_marketing", "ere"],
    }
    assert missive_type_filter("sms", prefix="to_missive") == {
        "to_missive__missive_type__in": ["sms", "rcs", "voice_call"],
    }
    with pytest.raises(ValueError):
        missive_type_filter("carrier-pigeon")


def test_status_predicates_treat_empty_status_as_pending():
    """Legacy rows carry ``status=""``; they are pending, not sent."""
    legacy = _missive(status="")
    sent = _missive(status=MissiveStatus.SUCCESS)

    pending_pks = set(
        Missive.objects.filter(pending_missive_q()).values_list("pk", flat=True)
    )
    sent_pks = set(
        Missive.objects.filter(sent_missive_q()).values_list("pk", flat=True)
    )
    assert legacy.pk in pending_pks and legacy.pk not in sent_pks
    assert sent.pk in sent_pks and sent.pk not in pending_pks


# ---------------------------------------------------------------------------
# Campaign counters
# ---------------------------------------------------------------------------

def test_count_support_groups_every_type_of_the_channel():
    campaign = _campaign()
    _missive(campaign, missive_type=MissiveType.EMAIL)
    _missive(campaign, missive_type=MissiveType.ERE)
    _missive(campaign, missive_type=MissiveType.HAND_DELIVERY)
    _missive(campaign, missive_type=MissiveType.REGISTERED_LETTER)
    _missive(campaign, missive_type=MissiveType.SMS)

    annotated = _annotated(campaign)
    assert annotated.count_support_email == 2
    assert annotated.count_support_address == 2
    assert annotated.count_support_phone == 1
    assert annotated.count_support_application == 0


def test_count_type_distinguishes_letter_from_registered_letter():
    campaign = _campaign()
    _missive(campaign, missive_type=MissiveType.LETTER)
    _missive(campaign, missive_type=MissiveType.REGISTERED_LETTER)
    _missive(campaign, missive_type=MissiveType.REGISTERED_LETTER)

    annotated = _annotated(campaign)
    assert annotated.count_support_address == 3
    assert annotated.count_type_letter == 1
    assert annotated.count_type_registered_letter == 2


def test_count_support_sent_ignores_pending_missives():
    campaign = _campaign()
    _missive(campaign, missive_type=MissiveType.EMAIL, status=MissiveStatus.SUCCESS)
    _missive(campaign, missive_type=MissiveType.EMAIL, status=MissiveStatus.PROCESSING)
    _missive(campaign, missive_type=MissiveType.EMAIL, status=MissiveStatus.DRAFT)
    _missive(campaign, missive_type=MissiveType.EMAIL, status="")

    annotated = _annotated(campaign)
    assert annotated.count_support_email == 4
    assert annotated.count_support_email_sent == 2


def test_campaign_sent_pending_error_counters():
    campaign = _campaign()
    _missive(campaign, status=MissiveStatus.SUCCESS)
    _missive(campaign, status=MissiveStatus.FAILED)
    _missive(campaign, status=MissiveStatus.ERROR)
    _missive(campaign, status=MissiveStatus.DRAFT)

    annotated = _annotated(campaign)
    assert annotated.count_sent == 3
    assert annotated.count_pending == 1
    assert annotated.count_error == 2


def test_count_support_error_is_the_failures_of_the_channel():
    campaign = _campaign()
    _missive(campaign, missive_type=MissiveType.EMAIL, status=MissiveStatus.FAILED)
    _missive(campaign, missive_type=MissiveType.EMAIL, status=MissiveStatus.SUCCESS)
    _missive(campaign, missive_type=MissiveType.REGISTERED_LETTER, status=MissiveStatus.ERROR)

    annotated = _annotated(campaign)
    assert annotated.count_support_email_error == 1
    assert annotated.count_support_address_error == 1
    assert annotated.count_support_phone_error == 0


def test_the_run_and_the_campaign_expose_the_same_counter_names():
    """Neither side may be missing a counter the other has.

    A UI that switches between a campaign and one of its runs reads the same
    names; ``count_pending`` used to exist only on the campaign and
    ``count_support_<support>_error`` only on the run.
    """
    shared = {"count_sent", "count_pending", "count_error"}
    shared |= {
        support_count_name(support, suffix)
        for support in GENERIC_SUPPORT
        for suffix in ("", "sent", "error")
    }
    assert shared <= set(campaign_count_annotations())
    assert shared <= set(run_count_annotations())


def test_campaign_without_missive_counts_zero_not_null():
    """The LEFT JOIN must not let the NULL row through the sent predicate."""
    annotated = _annotated(_campaign())
    assert annotated.count_sent == 0
    assert annotated.count_support_email == 0
    assert annotated.has_sent_missives is False


def test_new_counters_ignore_history_threads_legacy_ones_do_not():
    campaign = _campaign()
    _missive(campaign, status=MissiveStatus.SUCCESS)
    _missive(
        campaign,
        status=MissiveStatus.SUCCESS,
        thread_type=MissiveThreadType.HISTORY,
    )

    annotated = _annotated(campaign)
    assert annotated.count_sent == 1
    assert annotated.count_support_email == 1
    assert annotated.count_thread_history == 1
    # Documented behaviour of the historical counters: every thread counts.
    assert annotated.count_missive == 2
    assert annotated.count_missive_success == 2


def test_run_counters_share_the_campaign_thread_scope():
    """``count_sent`` must answer the same question on a campaign and on a run."""
    campaign = _campaign()
    run = MissiveScheduledCampaign.objects.create(campaign=campaign)
    _missive(campaign, scheduler=run, status=MissiveStatus.SUCCESS)
    _missive(
        campaign,
        scheduler=run,
        status=MissiveStatus.SUCCESS,
        thread_type=MissiveThreadType.HISTORY,
    )

    annotated_campaign = _annotated(campaign)
    annotated_run = MissiveScheduledCampaign.objects.with_counts().get(pk=run.pk)

    assert annotated_run.count_sent == annotated_campaign.count_sent == 1
    assert annotated_run.count_total == 1
    assert (
        annotated_run.count_support_email
        == annotated_campaign.count_support_email
        == 1
    )
    # The historical family agrees too, and there the archived thread counts.
    assert (
        annotated_run.count_missive_success
        == annotated_campaign.count_missive_success
        == 2
    )
    assert (
        annotated_run.count_thread_history
        == annotated_campaign.count_thread_history
        == 1
    )


def test_pct_recipient_divides_by_the_recipients_or_stays_at_zero():
    """The divisor is guarded by ``NULLIF``, so a campaign with none reads 0.0."""
    empty = _with_counts(_campaign())
    assert empty.pct_recipient_success == 0.0

    campaign = _campaign()
    for status in (MissiveStatus.SUCCESS, MissiveStatus.SUCCESS, MissiveStatus.FAILED):
        _missive(campaign).to_missiverecipient.create(
            name="Alice", email=f"{uuid.uuid4().hex}@example.com", status=status,
        )

    annotated = _with_counts(campaign)
    assert annotated.count_recipient == 3
    assert annotated.pct_recipient_success == pytest.approx(200 / 3)
    assert annotated.pct_recipient_failed == pytest.approx(100 / 3)
    assert annotated.pct_recipient_draft == 0.0


def test_the_default_queryset_aggregates_nothing():
    """Doctrine: the counters are opt-in, a plain lookup stays a plain lookup.

    Aggregates force a ``GROUP BY`` on every column of the campaign, and the
    default queryset is paid by every lookup, including a ``.get(pk=…)`` that
    reads no counter at all.
    """
    default = MissiveCampaign.objects.all()
    default_sql = str(default.query)
    assert "COUNT(" not in default_sql
    assert "GROUP BY" not in default_sql
    assert default_sql.count("JOIN") == 0
    # What is left: two ORDER BY … LIMIT 1 subqueries and two EXISTS.
    assert set(default.query.annotations) == {
        "last_send_date", "last_ended_at", "has_sent_missives", "has_open_run",
    }

    # The joins and aggregates every campaign lookup used to pay for.
    opted_in = str(MissiveCampaign.objects.with_counts().query)
    assert opted_in.count("JOIN") == 5
    assert opted_in.count("COUNT(DISTINCT") == 67


def test_with_counts_annotates_only_the_names_it_is_given():
    """Naming the counters a list displays is what makes the opt-in worth it.

    The cost of the query follows the number of aggregates — they all share one
    scan of the joined rows — so the fifty a changelist never reads are pure
    overhead. Selecting must not change a single value.
    """
    campaign = _campaign()
    _missive(campaign, status=MissiveStatus.SUCCESS).to_missiverecipient.create(
        name="Alice", email="alice@example.com", status=MissiveStatus.SUCCESS,
    )
    wanted = ("count_missive", "count_type_email", "pct_recipient_success")
    selected = MissiveCampaign.objects.with_counts(*wanted)

    # A percentage divides a recipient counter by count_recipient, so both come
    # along; nothing else does.
    assert set(selected.query.annotations) - set(
        MissiveCampaign.objects.all().query.annotations
    ) == {*wanted, "count_recipient", "count_recipient_success"}
    assert str(selected.query).count("COUNT(DISTINCT") < 66

    full = _with_counts(campaign)
    narrow = selected.get(pk=campaign.pk)
    for name in wanted:
        assert getattr(narrow, name) == getattr(full, name), name

    with pytest.raises(ValueError, match="count_nope"):
        MissiveCampaign.objects.with_counts("count_nope")


def test_campaign_changelist_only_annotates_what_its_columns_read():
    """Every name the admin asks for must exist, and cover every column."""
    from django_pymissive.admin.campaign import MissiveCampaignAdmin

    counters = MissiveCampaignAdmin.changelist_counters
    # Would raise ValueError on a stale name — a renamed counter must not
    # degrade the changelist to the one-query-per-row fallback.
    annotations = MissiveCampaign.objects.with_counts(*counters).query.annotations
    assert set(counters) <= set(annotations)
    assert set(annotations) < set(campaign_count_annotations()) | {
        "last_send_date", "last_ended_at", "has_sent_missives", "has_open_run",
    }


def test_campaign_changelist_still_renders_the_opt_in_counters():
    """The admin is the caller that needs them, so it opts in on its queryset."""
    campaign = _campaign()
    _missive(campaign, status=MissiveStatus.SUCCESS).to_missiverecipient.create(
        name="Alice", email="alice@example.com", status=MissiveStatus.SUCCESS,
    )
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x",
    )
    client = Client()
    client.force_login(user)

    response = client.get(
        reverse("admin:django_pymissive_missivecampaign_changelist"),
    )
    assert response.status_code == 200
    assert b"1 recipient(s)" in response.content
    assert b"100% success" in response.content


def test_a_counter_read_without_with_counts_costs_one_query_for_all():
    """Opt-in does not mean unreadable: the fallback fetches the whole set once.

    A template reading ``campaign.count_missive`` keeps working; what it must not
    do is pay one query per counter.
    """
    campaign = _campaign()
    _missive(campaign, status=MissiveStatus.SUCCESS).to_missiverecipient.create(
        name="Alice", email="alice@example.com", status=MissiveStatus.SUCCESS,
    )
    plain = _annotated(campaign)

    with CaptureQueriesContext(connection) as first:
        assert plain.count_missive == 1
    assert len(first.captured_queries) == 1

    with CaptureQueriesContext(connection) as more:
        assert plain.count_sent == 1
        assert plain.count_recipient == 1
        assert plain.count_support_email == 1
        assert plain.pct_recipient_success == 100.0
    assert len(more.captured_queries) == 0

    # Annotated, the same reads query nothing at all.
    with CaptureQueriesContext(connection) as annotated:
        assert _with_counts(campaign).count_missive == 1
    assert len(annotated.captured_queries) == 1


def test_the_fallback_only_answers_for_known_counters():
    """A typo stays an ``AttributeError``, it does not become a silent 0."""
    campaign = _annotated(_campaign())

    with pytest.raises(AttributeError):
        campaign.count_missives  # noqa: B018 — the plural does not exist
    with pytest.raises(AttributeError):
        campaign.does_not_exist  # noqa: B018


def test_has_sent_missives_and_can_remove():
    campaign = _campaign()
    _missive(campaign, status=MissiveStatus.DRAFT)

    annotated = _annotated(campaign)
    assert annotated.has_sent_missives is False
    assert annotated.can_remove is True

    _missive(campaign, status=MissiveStatus.SUCCESS)
    annotated = _annotated(campaign)
    assert annotated.has_sent_missives is True
    assert annotated.can_remove is False


def test_can_remove_falls_back_without_annotation():
    campaign = _campaign()
    _missive(campaign, status=MissiveStatus.SUCCESS)

    assert MissiveCampaign.objects_plain.get(pk=campaign.pk).can_remove is False


def test_has_open_run_and_is_processing():
    campaign = _campaign()
    assert _annotated(campaign).is_processing is False

    run = MissiveScheduledCampaign.objects.create(campaign=campaign)
    annotated = _annotated(campaign)
    assert annotated.has_open_run is True
    assert annotated.is_processing is True

    run.ended_at = timezone.now()
    run.save(update_fields=["ended_at"])
    assert _annotated(campaign).is_processing is False


def test_is_processing_from_metadata_flag():
    campaign = _campaign(metadata={"processing": True})
    assert _annotated(campaign).is_processing is True


def test_unannotated_campaign_queries_once_per_property():
    """A campaign reached from a missive carries no annotation — memoise instead.

    ``select_related("campaign")`` cannot bring the annotations along, so both
    properties fall back to an ``EXISTS``; without memoisation, every read of
    either was one more query per row of the list.
    """
    campaign = _campaign()
    _missive(campaign, status=MissiveStatus.SUCCESS)
    MissiveScheduledCampaign.objects.create(campaign=campaign)
    plain = MissiveCampaign.objects_plain.get(pk=campaign.pk)

    with CaptureQueriesContext(connection) as captured:
        assert plain.is_processing is True
        assert plain.can_remove is False
        assert plain.is_processing is True
        assert plain.can_remove is False

    assert len(captured.captured_queries) == 2


# ---------------------------------------------------------------------------
# Send preview + draft reclaim
# ---------------------------------------------------------------------------

def test_send_preview_payload_groups_by_support():
    campaign = _campaign()
    _missive(campaign, missive_type=MissiveType.EMAIL)
    _missive(campaign, missive_type=MissiveType.HAND_DELIVERY)
    _missive(campaign, missive_type=MissiveType.REGISTERED_LETTER)
    _missive(campaign, missive_type=MissiveType.SMS)
    _missive(campaign, missive_type=MissiveType.EMAIL, status=MissiveStatus.SUCCESS)

    payload = campaign.send_preview_payload()
    assert payload["total"] == 4
    assert payload["by_support"] == {
        "email": 1, "phone": 1, "address": 2, "application": 0,
    }
    assert payload["by_type"] == {
        "email": 1, "hand_delivery": 1, "registered_letter": 1, "sms": 1,
    }


def test_conversation_drafts_stay_out_of_the_send():
    """A reply being composed lives in the same table with the same default."""
    campaign = _campaign()
    message = _missive(campaign, thread_type=MissiveThreadType.MESSAGE)
    real = _missive(campaign)

    payload = campaign.send_preview_payload()
    assert payload["total"] == 1
    assert payload["total"] == _annotated(campaign).count_pending

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            MissiveScheduledCampaign, "start_scheduled_campaign", lambda self: None,
        )
        campaign.start_campaign()

    message.refresh_from_db()
    real.refresh_from_db()
    assert message.scheduler_id is None
    assert real.scheduler_id is not None

    run = MissiveScheduledCampaign.objects.get(pk=real.scheduler_id)
    assert list(run.get_missives()) == [real]


def test_start_campaign_reclaims_drafts_of_an_ended_run():
    """A resend duplicate keeps the FK of the run that produced it."""
    campaign = _campaign()
    ended = MissiveScheduledCampaign.objects.create(
        campaign=campaign, ended_at=timezone.now(),
    )
    orphan = _missive(campaign, scheduler=ended)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            MissiveScheduledCampaign, "start_scheduled_campaign", lambda self: None,
        )
        campaign.start_campaign()

    orphan.refresh_from_db()
    assert orphan.scheduler_id not in (None, ended.pk)


def test_start_campaign_leaves_drafts_of_a_running_run_alone():
    campaign = _campaign()
    running = MissiveScheduledCampaign.objects.create(campaign=campaign)
    claimed = _missive(campaign, scheduler=running)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            MissiveScheduledCampaign, "start_scheduled_campaign", lambda self: None,
        )
        campaign.start_campaign()

    claimed.refresh_from_db()
    assert claimed.scheduler_id == running.pk


# ---------------------------------------------------------------------------
# Missive.sent_at / with_counts
# ---------------------------------------------------------------------------

def test_sent_at_comes_from_the_oldest_send_event():
    missive = _missive(status=MissiveStatus.SUCCESS)
    first = timezone.now() - timezone.timedelta(hours=2)
    missive.to_missiveevent.create(event="request", occurred_at=first)
    sent = timezone.now() - timezone.timedelta(hours=1)
    missive.to_missiveevent.create(event="sent", occurred_at=sent)
    missive.to_missiveevent.create(event="delivered", occurred_at=timezone.now())

    assert Missive.objects.with_counts().get(pk=missive.pk).sent_at == sent


def test_sent_at_is_null_while_nothing_left():
    missive = _missive()
    missive.to_missiveevent.create(event="request", occurred_at=timezone.now())

    assert Missive.objects.with_counts().get(pk=missive.pk).sent_at is None


def test_missive_default_queryset_aggregates_nothing():
    """Doctrine: the counters are opt-in, a plain lookup stays a plain lookup."""
    default_sql = str(Missive.objects.all().query)
    assert "COUNT(" not in default_sql
    assert "GROUP BY" not in default_sql
    assert default_sql.count("JOIN") == 0
    assert Missive.objects.all().query.annotations == {}

    opted_in = str(Missive.objects.with_counts().query)
    assert "GROUP BY" in opted_in
    assert "COUNT(" in opted_in


def test_reverse_missive_relation_stays_a_plain_lookup():
    """``campaign.to_missive`` inherits the lean manager, not the admin annotations."""
    campaign = _campaign()
    _missive(campaign)
    sql = str(campaign.to_missive.all().query)
    assert "GROUP BY" not in sql
    assert "COUNT(" not in sql


def test_a_missive_counter_read_without_with_counts_costs_one_query_for_all():
    """Opt-in does not mean unreadable: the fallback fetches the whole set once."""
    missive = _missive()
    missive.to_missiverecipient.create(name="Alice", email="alice@example.com")
    missive.to_missiveevent.create(event="sent", occurred_at=timezone.now())
    plain = Missive.objects.get(pk=missive.pk)

    with CaptureQueriesContext(connection) as first:
        assert plain.count_recipient == 1
        assert plain.last_event == "sent"
    assert len(first.captured_queries) == 1

    with CaptureQueriesContext(connection) as more:
        assert plain.count_event == 1
        assert plain.sent_at is not None
        assert plain.is_billable is False
    assert len(more.captured_queries) == 0

    with CaptureQueriesContext(connection) as annotated:
        loaded = Missive.objects.with_counts().get(pk=missive.pk)
        assert loaded.count_recipient == 1
        assert loaded.last_event == "sent"
    assert len(annotated.captured_queries) == 1


def test_the_missive_fallback_only_answers_for_known_counters():
    missive = Missive.objects.get(pk=_missive().pk)

    with pytest.raises(AttributeError):
        missive.count_recipients  # noqa: B018
    with pytest.raises(AttributeError):
        missive.does_not_exist  # noqa: B018


def test_missive_changelist_still_renders_the_opt_in_counters():
    missive = _missive()
    missive.to_missiverecipient.create(name="Alice", email="alice@example.com")
    missive.to_missiveevent.create(event="sent", occurred_at=timezone.now())
    user = get_user_model().objects.create_superuser(
        username="missive-admin", email="missive-admin@example.com", password="x",
    )
    client = Client()
    client.force_login(user)

    response = client.get(reverse("admin:django_pymissive_missive_changelist"))
    assert response.status_code == 200
    assert b"1 event(s)" in response.content


# ---------------------------------------------------------------------------
# Recipient targets
# ---------------------------------------------------------------------------

def test_targets_by_missive_returns_the_value_of_each_support():
    email_missive = _missive(missive_type=MissiveType.EMAIL)
    email_missive.to_missiverecipient.create(name="Alice", email="alice@example.com")
    postal_missive = _missive(missive_type=MissiveType.REGISTERED_LETTER)
    postal_missive.to_missiverecipient.create(
        name="Bob", address={"address_line1": "1 rue Test", "city": "Lyon"},
    )

    targets = MissiveRecipient.objects.targets_by_missive(
        [email_missive.pk, postal_missive.pk],
    )
    assert targets[str(email_missive.pk)] == ["alice@example.com"]
    assert targets[str(postal_missive.pk)] == [
        {"address_line1": "1 rue Test", "city": "Lyon"},
    ]


def test_targets_by_missive_reads_the_recipients_alone():
    """One flat query: no join to the events, no ``GROUP BY``.

    The manager annotates ``count_event``, and ``.values()`` drops the column but
    keeps its ``LEFT JOIN``, so the rows to group used to be multiplied by the
    events — 12 here instead of 3.
    """
    missive = _missive(missive_type=MissiveType.EMAIL)
    for index in range(3):
        recipient = missive.to_missiverecipient.create(
            name=f"Alice {index}", email=f"alice{index}@example.com",
        )
        for _ in range(4):
            missive.to_missiveevent.create(event="request", recipient=recipient)

    with CaptureQueriesContext(connection) as captured:
        targets = MissiveRecipient.objects.targets_by_missive([missive.pk])

    assert len(targets[str(missive.pk)]) == 3
    assert len(captured.captured_queries) == 1
    sql = captured.captured_queries[0]["sql"]
    assert "JOIN" not in sql
    assert "GROUP BY" not in sql


def test_targets_by_missive_scoped_to_one_support():
    missive = _missive(missive_type=MissiveType.EMAIL)
    missive.to_missiverecipient.create(name="Alice", email="alice@example.com")
    missive.to_missiverecipient.create(
        name="Bob", address={"address_line1": "1 rue Test"},
    )

    assert MissiveRecipient.objects.targets_by_missive(
        [missive.pk], support="email",
    ) == {str(missive.pk): ["alice@example.com"]}


def test_targets_by_missive_falls_back_to_the_name():
    """A hand delivery may be recorded from a name only."""
    missive = _missive(missive_type=MissiveType.HAND_DELIVERY)
    missive.to_missiverecipient.create(name="Bob", recipient_support="address")

    assert MissiveRecipient.objects.targets_by_missive([missive.pk]) == {
        str(missive.pk): ["Bob"],
    }


def test_targets_by_missive_empty_input_and_unknown_support():
    assert MissiveRecipient.objects.targets_by_missive([]) == {}
    with pytest.raises(ValueError):
        MissiveRecipient.objects.targets_by_missive([1], support="carrier-pigeon")


# ---------------------------------------------------------------------------
# Generic annotations on an integration model
# ---------------------------------------------------------------------------

def test_with_last_missive_returns_the_newest_one():
    contact = _contact()
    older = _missive(status=MissiveStatus.SUCCESS)
    newer = _missive(status=MissiveStatus.DRAFT)
    _link(older, contact)
    _link(newer, contact)

    row = Contact.objects.with_last_missive().get(pk=contact.pk)
    assert uuid.UUID(str(row.last_missive["uid"])) == newer.pk
    assert row.last_missive["status"] == MissiveStatus.DRAFT
    assert row.last_missive["missive_type"] == MissiveType.EMAIL


def test_with_last_missive_is_an_empty_dict_without_missive():
    contact = _contact()

    row = Contact.objects.with_last_missive().get(pk=contact.pk)
    assert row.last_missive == {}
    assert row.last_missive.get("uid") is None


def test_with_last_missive_carries_the_send_date():
    contact = _contact()
    missive = _missive(status=MissiveStatus.SUCCESS)
    sent = timezone.now() - timezone.timedelta(hours=1)
    missive.to_missiveevent.create(event="sent", occurred_at=sent)
    _link(missive, contact)

    row = Contact.objects.with_last_missive().get(pk=contact.pk)
    assert row.last_missive["sent_at"] is not None


def test_with_last_missive_scoped_per_support():
    contact = _contact()
    email = _missive(missive_type=MissiveType.EMAIL)
    courrier = _missive(missive_type=MissiveType.REGISTERED_LETTER)
    _link(email, contact)
    _link(courrier, contact)

    row = (
        Contact.objects
        .with_last_missive(prefix="last_email", support="email")
        .with_last_missive(prefix="last_courrier", support="address")
        .get(pk=contact.pk)
    )
    assert uuid.UUID(str(row.last_email["uid"])) == email.pk
    assert uuid.UUID(str(row.last_courrier["uid"])) == courrier.pk


def test_with_last_missive_scoped_per_campaign_and_metadata():
    contact = _contact()
    campaign = _campaign()
    other = _campaign()
    mine = _missive(campaign, metadata={"channel": "hand_delivery"})
    _link(mine, contact)
    _link(_missive(other), contact)
    _link(_missive(campaign, metadata={"channel": "address"}), contact)

    row = (
        Contact.objects
        .with_last_missive(campaign=campaign, metadata={"channel": "hand_delivery"})
        .get(pk=contact.pk)
    )
    assert uuid.UUID(str(row.last_missive["uid"])) == mine.pk


def test_with_missive_count_per_support_and_sent_flag():
    contact = _contact()
    other_contact = _contact(email="other@example.com")
    _link(_missive(missive_type=MissiveType.EMAIL, status=MissiveStatus.SUCCESS), contact)
    _link(_missive(missive_type=MissiveType.EMAIL), contact)
    _link(_missive(missive_type=MissiveType.REGISTERED_LETTER), contact)
    _link(_missive(missive_type=MissiveType.EMAIL), other_contact)

    row = (
        Contact.objects
        .with_missive_count(name="email_count", support="email")
        .with_missive_count(name="courrier_count", support="address")
        .with_missive_count(name="sent_count", sent=True)
        .get(pk=contact.pk)
    )
    assert (row.email_count, row.courrier_count, row.sent_count) == (2, 1, 1)


def test_with_missive_count_is_zero_without_missive():
    contact = _contact()

    assert Contact.objects.with_missive_count().get(pk=contact.pk).missive_count == 0


def test_with_missive_counts_packs_missives_and_events():
    contact = _contact()
    missive = _missive()
    missive.to_missiveevent.create(event="request", occurred_at=timezone.now())
    missive.to_missiveevent.create(event="sent", occurred_at=timezone.now())
    _link(missive, contact)
    _link(_missive(), contact)

    row = Contact.objects.with_missive_counts().get(pk=contact.pk)
    assert row.missive_counts == {"missives": 2, "events": 2}


def test_with_missive_counts_is_zeroed_without_missive():
    contact = _contact()

    row = Contact.objects.with_missive_counts().get(pk=contact.pk)
    assert row.missive_counts == {"missives": 0, "events": 0}


def test_with_campaign_missive_count_walks_the_campaign_link():
    contact = _contact()
    campaign = _campaign()
    campaign.to_campaignrelatedobject.create(content_object=contact)
    _missive(campaign, status=MissiveStatus.DRAFT)
    _missive(campaign, status=MissiveStatus.SUCCESS)
    _missive(_campaign(), status=MissiveStatus.DRAFT)

    row = (
        Contact.objects
        .with_campaign_missive_count(name="pending", sent=False)
        .with_campaign_missive_count(name="total")
        .get(pk=contact.pk)
    )
    assert (row.pending, row.total) == (1, 2)


class _UUIDTargetQuerySet(MissiveRelatedQuerySetMixin, models.QuerySet):
    """Stands in for an integration queryset whose model has a UUID pk."""


def test_generic_link_accepts_a_uuid_pk():
    """``object_id`` is text, so a UUID target is linkable — it used to raise."""
    target = _campaign()
    link = _link(_missive(missive_type=MissiveType.EMAIL), target)

    link.refresh_from_db()
    assert link.object_id == target.pk.hex
    assert link.content_object == target

    rows = missive_related_queryset(target, support="email")
    assert [row.pk for row in rows] == [link.pk]


def test_virtual_attachment_accepts_a_uuid_target():
    """``attachment_object_id`` is text as well, so a UUID-keyed model is reachable.

    It carries its own ``GenericForeignKey``, and being an integer column it used
    to reject any target whose pk is a UUID.
    """
    target = _campaign()
    attachment = MissiveBaseAttachment.objects.create(
        missive=_missive(),
        attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT,
        attachment_content_type=ContentType.objects.get_for_model(MissiveCampaign),
        attachment_object_id=target.pk,
        attachment_object_arguments={"method": "retrieve_attachment"},
    )

    attachment.refresh_from_db()
    assert attachment.attachment_object_id == target.pk.hex
    assert attachment.attachment_object == target
    assert attachment.can_access_document() is True


def test_mixin_annotates_a_uuid_pk_model():
    """The correlated lookup matches a UUID pk as well as an integer one.

    Comparing the text column to the raw pk would raise on PostgreSQL and match
    nothing on SQLite, where a UUID is stored without dashes.
    """
    target = _campaign()
    courrier = _missive(missive_type=MissiveType.REGISTERED_LETTER)
    _link(_missive(missive_type=MissiveType.EMAIL, status=MissiveStatus.SUCCESS), target)
    _link(courrier, target)
    _link(_missive(missive_type=MissiveType.EMAIL), _campaign())

    row = (
        _UUIDTargetQuerySet(model=MissiveCampaign)
        .with_missive_count(name="email_count", support="email")
        .with_last_missive(prefix="last_courrier", support="address")
        .get(pk=target.pk)
    )
    assert row.email_count == 1
    assert uuid.UUID(str(row.last_courrier["uid"])) == courrier.pk


def test_missive_related_queryset_orders_newest_first():
    contact = _contact()
    older = _missive(missive_type=MissiveType.EMAIL)
    newer = _missive(missive_type=MissiveType.EMAIL)
    courrier = _missive(missive_type=MissiveType.REGISTERED_LETTER)
    for missive in (older, newer, courrier):
        _link(missive, contact)

    rows = missive_related_queryset(contact, support="email")
    assert [row.missive_id for row in rows] == [newer.pk, older.pk]


def test_equally_dated_missives_are_ranked_by_their_link():
    """Same ``created_at`` on both: the most recent link wins, not a random pk.

    ``missive_id`` is a UUID4, so using it as the tie-break made the winner —
    and hence ``with_last_missive`` — depend on which uuid happened to sort
    higher.
    """
    contact = _contact()
    first = _missive(missive_type=MissiveType.EMAIL)
    second = _missive(missive_type=MissiveType.EMAIL)
    same_date = timezone.now()
    Missive.objects.filter(pk__in=[first.pk, second.pk]).update(created_at=same_date)
    for missive in (first, second):
        _link(missive, contact)

    rows = missive_related_queryset(contact, support="email")
    assert [row.missive_id for row in rows] == [second.pk, first.pk]

    row = Contact.objects.with_last_missive(support="email").get(pk=contact.pk)
    assert uuid.UUID(str(row.last_missive["uid"])) == second.pk


@pytest.mark.parametrize(
    "call",
    [
        lambda qs: qs.with_missive_count(prefix="email"),
        lambda qs: qs.with_campaign_missive_count(prefix="email"),
        lambda qs: missive_related_queryset(_contact(), prefix="email"),
    ],
)
def test_prefix_is_refused_as_a_filter(call):
    """``prefix`` is the lookup path to the missive, never a caller's filter.

    Passing it used to reach the query builder and blow up there, either on an
    unknown field or on a duplicated keyword argument.
    """
    with pytest.raises(TypeError, match="prefix is not a filter"):
        call(Contact.objects.all())


# ---------------------------------------------------------------------------
# Batch pass: missive_summaries_by_object
# ---------------------------------------------------------------------------

def test_summaries_by_object_costs_two_queries_per_batch_not_per_row():
    """The point of the helper: a flat cost, where the mixin pays per row.

    Each ``with_*`` is a correlated subquery, re-run for every row it annotates;
    fine for a page, ruinous on an export.
    """
    contacts = [_contact() for _ in range(5)]
    for contact in contacts:
        for _ in range(3):
            missive = _missive(status=MissiveStatus.SUCCESS)
            missive.to_missiveevent.create(event="sent", occurred_at=timezone.now())
            _link(missive, contact)

    with CaptureQueriesContext(connection) as captured:
        summaries = missive_summaries_by_object(Contact, [c.pk for c in contacts])

    assert len(captured.captured_queries) == 2
    assert len(summaries) == 5
    assert all(row["missives"] == 3 and row["events"] == 3 for row in summaries.values())
    assert "GROUP BY" not in captured.captured_queries[0]["sql"]


def test_summaries_by_object_agrees_with_the_annotations():
    contact = _contact()
    older = _missive(status=MissiveStatus.SUCCESS)
    older.to_missiveevent.create(event="request", occurred_at=timezone.now())
    older.to_missiveevent.create(event="sent", occurred_at=timezone.now())
    newer = _missive(status=MissiveStatus.DRAFT)
    _link(older, contact)
    _link(newer, contact)

    row = (
        Contact.objects.with_missive_counts().with_last_missive().get(pk=contact.pk)
    )
    summary = missive_summaries_by_object(Contact, [contact.pk])[
        object_id_value(contact.pk)
    ]

    assert summary["missives"] == row.missive_counts["missives"] == 2
    assert summary["events"] == row.missive_counts["events"] == 2
    assert uuid.UUID(summary["last"]["uid"]) == uuid.UUID(str(row.last_missive["uid"]))
    assert summary["last"]["status"] == row.last_missive["status"] == MissiveStatus.DRAFT
    assert summary["last"]["sent_at"] is None  # the newest one, still a draft


def test_summaries_by_object_dates_the_send_of_the_last_missive():
    contact = _contact()
    missive = _missive(status=MissiveStatus.SUCCESS)
    sent = timezone.now() - timezone.timedelta(hours=1)
    missive.to_missiveevent.create(event="request", occurred_at=timezone.now())
    missive.to_missiveevent.create(event="sent", occurred_at=sent)
    _link(missive, contact)

    summary = missive_summaries_by_object(Contact, [contact.pk])[
        object_id_value(contact.pk)
    ]
    assert summary["last"]["sent_at"] == sent


def test_summaries_by_object_zeroes_an_object_without_missive():
    """Every requested object answers, so a template reads it like an annotation."""
    linked, bare = _contact(), _contact()
    _link(_missive(), linked)

    summaries = missive_summaries_by_object(Contact, [linked.pk, bare.pk])
    assert summaries[object_id_value(bare.pk)] == {
        "missives": 0, "events": 0, "last": {},
    }
    assert summaries[object_id_value(linked.pk)]["missives"] == 1


def test_summaries_by_object_takes_the_link_filters():
    contact = _contact()
    email = _missive(missive_type=MissiveType.EMAIL)
    _link(email, contact)
    _link(_missive(missive_type=MissiveType.REGISTERED_LETTER), contact)

    summaries = missive_summaries_by_object(Contact, [contact.pk], support="email")
    summary = summaries[object_id_value(contact.pk)]
    assert summary["missives"] == 1
    assert uuid.UUID(summary["last"]["uid"]) == email.pk

    with pytest.raises(TypeError, match="prefix is not a filter"):
        missive_summaries_by_object(Contact, [contact.pk], prefix="email")


def test_summaries_by_object_accepts_instances_and_a_uuid_pk():
    """Keyed by the canonical ``object_id``, so a UUID target works untouched."""
    target = _campaign()
    _link(_missive(), target)

    summaries = missive_summaries_by_object(MissiveCampaign, [target])
    assert summaries[object_id_value(target.pk)]["missives"] == 1


def test_summaries_by_object_splits_the_id_lists_into_batches(monkeypatch):
    """Every id in an ``IN`` clause is a bound parameter, and backends cap them.

    PostgreSQL's protocol counts them on 16 bits — 65 535 per statement — so an
    export has to be cut up, and the missive pass is cut on its own since an
    object may carry any number of them. Cutting must not change an answer: an
    ``object_id`` lands in a single batch, which is what the newest-first pass
    over the ordered rows relies on.
    """
    contacts = [_contact() for _ in range(5)]
    for contact in contacts:
        for _ in range(2):
            missive = _missive(status=MissiveStatus.SUCCESS)
            missive.to_missiveevent.create(event="sent", occurred_at=timezone.now())
            _link(missive, contact)

    ids = [contact.pk for contact in contacts]
    reference = missive_summaries_by_object(Contact, ids)
    assert all(row["missives"] == 2 for row in reference.values())

    monkeypatch.setattr(related_object_manager, "_ID_BATCH_SIZE", 2)
    with CaptureQueriesContext(connection) as captured:
        assert missive_summaries_by_object(Contact, ids) == reference

    # Five objects two at a time, then their ten missives two at a time.
    assert len(captured.captured_queries) == 3 + 5
    for query in captured.captured_queries:
        assert query["sql"].count("%s") <= 2 + 2  # ids, plus the content type


def test_summaries_by_object_queries_nothing_for_an_empty_batch():
    with CaptureQueriesContext(connection) as captured:
        assert missive_summaries_by_object(Contact, []) == {}
    assert captured.captured_queries == []
