"""CampaignTarget stores the checkbox; the missive is built at send time."""

from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

import pytest

from django_pymissive.models import (
    CampaignTarget,
    Missive,
    MissiveCampaign,
    MissiveScheduledCampaign,
    MissiveStatus,
    MissiveType,
)
from django_pymissive.models.campaign_target import resolve_build_target_processors
from django_pymissive.models.choices import MissiveThreadType
from django_pymissive.models.related_object import MissiveRelatedObject
from django_pymissive.services import (
    CampaignAlreadySending,
    build_send_preview,
    counts,
    delete_drafts,
    is_selected,
    materialize_missive,
    materialize_selection,
    select,
    send_target,
    start_selection,
    unselect,
)
from tests.fakeapp.campaign_targets import build_campaign_contact, build_contact_email
from tests.fakeapp.generators import create_campaign_contact, generate_campaign_contacts
from tests.fakeapp.models import CampaignContact, Contact, PdfDocument

BUILD = "tests.fakeapp.campaign_targets.build_contact_email"


def build_marked(campaign, target, missive_type):
    """Build hook whose subject shows the target's own processor ran."""
    missive = build_campaign_contact(campaign, target, missive_type)
    if missive is not None:
        missive.subject = "from-target-processor"
        missive.save(update_fields=["subject"])
    return missive


def _campaign():
    return MissiveCampaign.objects.create(
        subject="Assemblée générale",
        email_body_text="Bonjour",
        email_body_rich="<p>Bonjour</p>",
    )


def _contact(email, first="Ada"):
    return Contact.objects.create(
        first_name=first,
        last_name="Lovelace",
        email=email,
    )


@pytest.mark.django_db
def test_select_is_idempotent_and_one_row_per_channel():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    grace = _contact("grace@example.com", first="Grace")

    assert select(campaign, "email", [ada, ada, grace]) == 2
    assert select(campaign, MissiveType.EMAIL, [ada]) == 0
    assert select(campaign, "sms", ada) == 1

    assert CampaignTarget.objects.filter(campaign=campaign).count() == 3
    assert is_selected(campaign, ada, "email") is True
    assert is_selected(campaign, ada, "letter") is False
    assert counts(campaign, missive_types=["email", "sms", "letter"], active_only=True) == {
        "email": 2,
        "sms": 1,
        "letter": 0,
    }
    preview = build_send_preview(campaign, missive_types=["email", "sms"])
    assert preview["total_selected"] == 3
    assert preview["missive_types"]["email"] == {"selected": 2}


@pytest.mark.django_db
def test_unselect_keeps_rows_that_already_have_a_missive():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)
    row = CampaignTarget.objects.get(campaign=campaign)
    missive = Missive.objects.create(
        campaign=campaign,
        missive_type=MissiveType.EMAIL,
        subject="Hi",
        body_text="Hi",
        status=MissiveStatus.SUCCESS,
    )
    row.attach_missive(missive)

    assert unselect(campaign, "email", [ada]) == 0
    assert CampaignTarget.objects.filter(pk=row.pk).exists()
    assert is_selected(campaign, ada, "email") is False

    assert select(campaign, "email", ada) == 1
    assert CampaignTarget.objects.filter(campaign=campaign).count() == 2
    assert is_selected(campaign, ada, "email") is True
    assert unselect(campaign, "email") == 1
    row.refresh_from_db()
    assert row.missive_id == missive.pk


@pytest.mark.django_db
def test_pending_unique_constraint_preserves_text_object_id():
    campaign = _campaign()
    content_type = ContentType.objects.get_for_model(Contact)
    CampaignTarget.objects.create(
        campaign=campaign,
        missive_type=MissiveType.EMAIL,
        content_type=content_type,
        object_id="550e8400-e29b-41d4-a716-446655440000",
        object_str="ghost",
    )
    stored = CampaignTarget.objects.get()
    assert stored.object_id == "550e8400-e29b-41d4-a716-446655440000"

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CampaignTarget.objects.create(
                campaign=campaign,
                missive_type=MissiveType.EMAIL,
                content_type=content_type,
                object_id="550e8400-e29b-41d4-a716-446655440000",
                object_str="ghost",
            )


@pytest.mark.django_db
def test_materialize_reuses_a_draft_and_duplicates_a_sent_missive():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    calls = []

    def build(campaign, target, missive_type):
        calls.append(target.pk)
        return build_contact_email(campaign, target, missive_type)

    first, created = materialize_missive(campaign, ada, "email", build=build)
    assert created is True
    assert calls == [ada.pk]
    assert first.status == MissiveStatus.DRAFT
    assert MissiveRelatedObject.objects.filter(missive=first).count() == 1

    again, created = materialize_missive(campaign, ada, "email", build=build)
    assert created is False
    assert again.pk == first.pk
    assert calls == [ada.pk]

    first.status = MissiveStatus.SUCCESS
    first.save(update_fields=["status"])
    resent, created = materialize_missive(campaign, ada, "email", build=build)
    assert created is True
    assert resent.pk != first.pk
    assert resent.status == MissiveStatus.DRAFT
    assert resent.thread_id == first.thread_id
    first.refresh_from_db()
    assert first.thread_type == MissiveThreadType.HISTORY
    assert calls == [ada.pk]


@pytest.mark.django_db
def test_materialize_prefers_an_older_draft_over_a_newer_sent_missive():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    draft, _created = materialize_missive(campaign, ada, "email", build=build_contact_email)
    sent = build_contact_email(campaign, ada, "email")
    Missive.objects.filter(pk=sent.pk).update(status=MissiveStatus.SUCCESS)

    missive, created = materialize_missive(campaign, ada, "email", build=build_contact_email)

    assert created is False
    assert missive.pk == draft.pk
    sent.refresh_from_db()
    assert sent.thread_type == MissiveThreadType.MISSIVE


@pytest.mark.django_db
def test_materialize_replaces_a_legacy_empty_status_with_a_real_draft():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    legacy, _created = materialize_missive(campaign, ada, "email", build=build_contact_email)
    Missive.objects.filter(pk=legacy.pk).update(status="")

    missive, created = materialize_missive(campaign, ada, "email", build=build_contact_email)

    assert created is True
    assert missive.pk != legacy.pk
    assert missive.status == MissiveStatus.DRAFT
    legacy.refresh_from_db()
    assert legacy.thread_type == MissiveThreadType.HISTORY


@pytest.mark.django_db
def test_materialize_leaves_no_missive_when_the_build_fails_midway():
    campaign = _campaign()
    ada = _contact("ada@example.com")

    def build(campaign, target, missive_type):
        build_contact_email(campaign, target, missive_type)
        raise RuntimeError("crash after the missive was saved")

    with pytest.raises(RuntimeError):
        materialize_missive(campaign, ada, "email", build=build)
    assert Missive.objects.count() == 0
    assert MissiveRelatedObject.objects.count() == 0


@pytest.mark.django_db
def test_delete_drafts_turns_the_row_back_into_a_checkbox():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)
    missive, _created = materialize_missive(
        campaign,
        ada,
        "email",
        build=build_contact_email,
    )
    CampaignTarget.objects.get().attach_missive(missive)

    assert delete_drafts(campaign, "email") == 1
    assert not Missive.objects.filter(pk=missive.pk).exists()
    row = CampaignTarget.objects.get()
    assert row.missive_id is None
    assert is_selected(campaign, ada, "email") is True


@pytest.mark.django_db
def test_deleting_a_draft_gives_the_checkbox_back():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)
    missive, _created = materialize_missive(campaign, ada, "email", build=build_contact_email)
    CampaignTarget.objects.get().attach_missive(missive)

    missive.delete()

    assert CampaignTarget.objects.get().missive_id is None
    assert is_selected(campaign, ada, "email") is True


@pytest.mark.django_db
def test_deleting_a_sent_missive_removes_its_row():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)
    sent, _created = materialize_missive(campaign, ada, "email", build=build_contact_email)
    CampaignTarget.objects.get().attach_missive(sent)
    Missive.objects.filter(pk=sent.pk).update(status=MissiveStatus.SUCCESS)

    Missive.objects.get(pk=sent.pk).delete()

    assert not CampaignTarget.objects.filter(campaign=campaign).exists()
    assert is_selected(campaign, ada, "email") is False


@pytest.mark.django_db
def test_deleting_a_sent_missive_keeps_a_new_selection_of_the_same_target():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)
    sent, _created = materialize_missive(campaign, ada, "email", build=build_contact_email)
    CampaignTarget.objects.get().attach_missive(sent)
    Missive.objects.filter(pk=sent.pk).update(status=MissiveStatus.SUCCESS)
    select(campaign, "email", ada)

    Missive.objects.get(pk=sent.pk).delete()

    assert CampaignTarget.objects.filter(campaign=campaign).count() == 1
    assert is_selected(campaign, ada, "email") is True


@pytest.mark.django_db
def test_deleting_a_draft_when_the_target_is_selected_again_drops_the_old_row():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)
    draft, _created = materialize_missive(campaign, ada, "email", build=build_contact_email)
    CampaignTarget.objects.get().attach_missive(draft)
    select(campaign, "email", ada)

    draft.delete()

    assert CampaignTarget.objects.filter(campaign=campaign).count() == 1
    assert is_selected(campaign, ada, "email") is True


@pytest.mark.django_db
def test_materialize_selection_abandons_a_target_without_a_contact():
    campaign = _campaign()
    document = PdfDocument.objects.create(name="notice.pdf")
    select(campaign, "email", document)

    assert materialize_selection(campaign, ["email"], build=build_contact_email) == 0

    assert Missive.objects.count() == 0
    assert is_selected(campaign, document, "email") is False
    row = CampaignTarget.objects.get(campaign=campaign)
    assert row.abandoned_at is not None
    assert row.abandon_reason == "No reachable recipient"


@pytest.mark.django_db
def test_materialize_selection_abandons_a_deleted_target_and_it_can_be_selected_again():
    campaign = _campaign()
    gone = _contact("gone@example.com")
    select(campaign, "email", gone)
    Contact.objects.filter(pk=gone.pk).delete()

    assert materialize_selection(campaign, ["email"], build=build_contact_email) == 0

    row = CampaignTarget.objects.get(campaign=campaign)
    assert row.abandon_reason == "Target deleted"
    assert campaign.__class__.objects.get(pk=campaign.pk).count_target_pending == 0

    gone.save()
    assert select(campaign, "email", gone) == 1
    assert CampaignTarget.objects.filter(campaign=campaign).count() == 2


@pytest.mark.django_db
def test_materialize_selection_keeps_a_target_whose_build_fails():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)

    def broken(campaign, target, missive_type):
        raise RuntimeError("provider down")

    assert materialize_selection(campaign, ["email"], build=broken) == 0
    assert is_selected(campaign, ada, "email") is True


@pytest.mark.django_db
def test_abandon_only_applies_to_a_waiting_row():
    campaign = _campaign()
    select(campaign, "email", _contact("ada@example.com"))
    row = CampaignTarget.objects.get(campaign=campaign)

    assert row.abandon("wrong list") is True
    assert row.abandon("again") is False
    row.refresh_from_db()
    assert row.abandon_reason == "wrong list"
    assert row.is_active() is False


@pytest.mark.django_db
def test_materialize_selection_keeps_going_when_a_build_fails():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    grace = _contact("grace@example.com", first="Grace")
    select(campaign, "email", [ada, grace])

    def build(campaign, target, missive_type):
        if target.pk == ada.pk:
            raise RuntimeError("broken build")
        return build_contact_email(campaign, target, missive_type)

    assert materialize_selection(campaign, ["email"], build=build) == 1

    assert is_selected(campaign, ada, "email") is True
    assert is_selected(campaign, grace, "email") is False


@pytest.mark.django_db
def test_materialize_selection_rechecks_a_stale_target_before_building():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)
    stale_row = CampaignTarget.objects.get(campaign=campaign)
    existing = Missive.objects.create(
        campaign=campaign,
        missive_type=MissiveType.EMAIL,
        status=MissiveStatus.DRAFT,
    )
    CampaignTarget.objects.filter(pk=stale_row.pk).update(missive=existing)
    build_calls = []

    def build(campaign, target, missive_type):
        build_calls.append(target.pk)
        return build_contact_email(campaign, target, missive_type)

    with patch(
        "django_pymissive.services.send.target_services.iter_targets",
        return_value=iter([stale_row]),
    ):
        assert materialize_selection(campaign, ["email"], build=build) == 0

    assert build_calls == []
    assert Missive.objects.filter(campaign=campaign).count() == 1


@pytest.mark.django_db
def test_start_selection_materializes_during_the_run(settings, django_capture_on_commit_callbacks):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    campaign = _campaign()
    ada = _contact("ada@example.com")
    grace = _contact("grace@example.com", first="Grace")
    select(campaign, "email", [ada, grace])
    assert Missive.objects.count() == 0

    with django_capture_on_commit_callbacks(execute=True):
        start_selection(campaign, ["email"], build=BUILD)

    campaign.refresh_from_db()
    assert campaign.is_processing is False
    assert Missive.objects.filter(campaign=campaign).count() == 2
    assert CampaignTarget.objects.filter(campaign=campaign, missive__isnull=True).count() == 0
    for row in CampaignTarget.objects.filter(campaign=campaign):
        assert row.missive_id is not None
        assert row.missive.external_id.startswith("dry-run:")
        assert row.missive.scheduler_id is not None
        assert row.is_active() is False

    with django_capture_on_commit_callbacks(execute=True):
        start_selection(campaign, ["email"], build=BUILD)
    assert Missive.objects.filter(campaign=campaign).count() == 2


@pytest.mark.django_db
def test_start_selection_runs_with_a_task_backend_allowlist(settings, django_capture_on_commit_callbacks):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = ["myapp.tasks", "tests"]
    campaign = _campaign()
    select(campaign, "email", _contact("ada@example.com"))

    with django_capture_on_commit_callbacks(execute=True):
        scheduled = start_selection(campaign, ["email"], build=BUILD)

    scheduled.refresh_from_db()
    assert "last_error" not in scheduled.additional_config
    row = CampaignTarget.objects.get(campaign=campaign)
    assert row.missive.external_id.startswith("dry-run:")


@pytest.mark.django_db
def test_cancelled_selection_run_checks_its_unsent_targets_again(
    settings,
    django_capture_on_commit_callbacks,
):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    campaign = _campaign()
    ada, grace = _contact("ada@example.com"), _contact("grace@example.com", first="Grace")
    select(campaign, "email", [ada, grace])
    send_missive = Missive.send_missive

    def send_then_cancel(missive, *args, **kwargs):
        missive.scheduler.cancel("stop")
        return send_missive(missive, *args, **kwargs)

    with patch.object(Missive, "send_missive", send_then_cancel):
        with django_capture_on_commit_callbacks(execute=True):
            run = start_selection(campaign, ["email"], build=BUILD)

    run.refresh_from_db()
    assert run.cancelled_at is not None
    sent = CampaignTarget.objects.get(campaign=campaign, missive__isnull=False)
    assert sent.missive.status != MissiveStatus.DRAFT
    assert Missive.objects.filter(campaign=campaign).count() == 1
    assert sum(is_selected(campaign, target, "email") for target in (ada, grace)) == 1
    assert CampaignTarget.objects.filter(campaign=campaign).count() == 2


@pytest.mark.django_db
def test_checking_a_sent_target_again_continues_its_thread(settings):
    from django.contrib import admin
    from django.test import Client
    from django.urls import reverse

    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)
    send_target(campaign, ada, "email", build=build_contact_email)
    first_row = CampaignTarget.objects.get(campaign=campaign)
    first = first_row.missive

    select(campaign, "email", ada)
    send_target(campaign, ada, "email", build=build_contact_email)

    second_row = CampaignTarget.objects.filter(campaign=campaign).latest("created_at")
    second = second_row.missive
    first.refresh_from_db()
    assert second.pk != first.pk
    assert second.thread_id == first.thread_id
    assert first.thread_type == MissiveThreadType.HISTORY
    assert list(second_row.history()) == [second_row, first_row]
    assert list(first_row.thread_missives()) == [second, first]

    client = Client()
    client.force_login(_superuser("target-admin-history"))
    page = client.get(
        reverse("admin:django_pymissive_campaigntarget_change", args=[second_row.pk]),
    )
    html = page.content.decode()
    assert page.status_code == 200
    assert reverse("admin:django_pymissive_campaigntarget_change", args=[first_row.pk]) in html
    assert reverse("admin:django_pymissive_missive_change", args=[first.pk]) in html
    assert admin.site._registry[CampaignTarget].thread_missives_display(first_row) != "-"


@pytest.mark.django_db
def test_a_missive_claimed_but_not_yet_sent_is_neither_reused_nor_duplicated():
    from django_pymissive.services import last_sent, link_target

    campaign = _campaign()
    ada = _contact("ada@example.com")
    claimed = Missive.objects.create(
        campaign=campaign,
        missive_type=MissiveType.EMAIL,
        subject="Hi",
        status=MissiveStatus.PROCESSING,
    )
    link_target(claimed, ada)

    assert last_sent(campaign, ada, "email") is None
    missive, created = materialize_missive(campaign, ada, "email", build=build_contact_email)

    assert created is True
    assert missive.pk != claimed.pk
    claimed.refresh_from_db()
    assert claimed.thread_type == MissiveThreadType.MISSIVE

    Missive.objects.filter(pk=claimed.pk).update(external_id="provider-1")
    missive.delete()
    assert last_sent(campaign, ada, "email") == claimed


@pytest.mark.django_db
def test_campaign_links_to_its_targets_filtered_by_state():
    from django.test import Client
    from django.urls import reverse

    campaign = _campaign()
    other = _campaign()
    select(campaign, "email", [_contact("ada@example.com"), _contact("grace@example.com")])
    select(other, "email", _contact("linus@example.com"))
    abandoned = CampaignTarget.objects.filter(campaign=campaign).first()
    abandoned.abandon("moved away")
    client = Client()
    client.force_login(_superuser("target-admin-links"))

    campaigns = client.get(reverse("admin:django_pymissive_missivecampaign_changelist"))
    changelist = reverse("admin:django_pymissive_campaigntarget_changelist")
    pending_url = f"{changelist}?campaign__id__exact={campaign.pk}&amp;state=pending"
    assert pending_url in campaigns.content.decode()

    def listed(state):
        response = client.get(changelist, {"campaign__id__exact": campaign.pk, "state": state})
        assert response.status_code == 200
        return {row.pk for row in response.context["cl"].result_list}

    pending = set(
        CampaignTarget.objects.filter(campaign=campaign).exclude(pk=abandoned.pk).values_list("pk", flat=True)
    )
    assert listed("pending") == pending
    assert listed("abandoned") == {abandoned.pk}
    assert listed("with_missive") == set()


@pytest.mark.django_db
def test_thread_missives_of_a_row_without_missive_reads_the_history():
    campaign = _campaign()
    select(campaign, "email", _contact("ada@example.com"))
    row = CampaignTarget.objects.get(campaign=campaign)

    assert not row.thread_missives().exists()
    assert list(row.history()) == [row]


BUILD_LOG = []


def build_and_log(campaign, target, missive_type):
    run = MissiveScheduledCampaign.objects.get(campaign=campaign)
    run.refresh_counts()
    BUILD_LOG.append((run.total_count, run.total_sent_count))
    return build_contact_email(campaign, target, missive_type)


@pytest.mark.django_db
def test_selection_run_builds_every_target_before_sending(settings, django_capture_on_commit_callbacks):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    BUILD_LOG.clear()
    campaign = _campaign()
    hand_draft = Missive.objects.create(
        campaign=campaign,
        missive_type=MissiveType.EMAIL,
        subject="Hi",
        body_text="Hi",
    )
    select(campaign, "email", [_contact("ada@example.com"), _contact("grace@example.com")])

    with django_capture_on_commit_callbacks(execute=True):
        start_selection(campaign, ["email"], build="tests.test_campaign_target.build_and_log")

    # One claimed draft plus two targets, all counted before any send.
    assert BUILD_LOG == [(3, 0), (3, 0)]
    run = MissiveScheduledCampaign.objects.get(campaign=campaign)
    assert (run.total_count, run.total_sent_count, run.progress) == (3, 3, 100)
    assert run.average_send_speed is not None
    hand_draft.refresh_from_db()
    assert hand_draft.status != MissiveStatus.DRAFT


@pytest.mark.django_db
def test_start_selection_refuses_a_campaign_already_sending():
    campaign = _campaign()
    campaign.to_missivecampaignsend.create()

    with pytest.raises(CampaignAlreadySending):
        start_selection(campaign, ["email"], build=BUILD)


@pytest.mark.django_db
def test_start_selection_ignores_legacy_processing_metadata():
    campaign = _campaign()
    campaign.metadata = {"processing": True}
    campaign.save(update_fields=["metadata"])

    run = start_selection(campaign, ["email"], build=BUILD)

    assert run.campaign_id == campaign.pk


@pytest.mark.django_db
def test_send_target_sends_one_selected_target(settings):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)

    send_target(campaign, ada, "email", build=build_contact_email)

    row = CampaignTarget.objects.get(campaign=campaign)
    assert row.missive.external_id.startswith("dry-run:")
    assert row.is_active() is False


@pytest.mark.django_db
def test_send_target_refuses_while_a_run_is_open_without_the_flag():
    campaign = _campaign()
    campaign.to_missivecampaignsend.create()
    with pytest.raises(CampaignAlreadySending):
        send_target(campaign, _contact("ada@example.com"), "email", build=build_contact_email)
    assert Missive.objects.filter(campaign=campaign).count() == 0


@pytest.mark.django_db
def test_a_run_after_send_target_does_not_build_the_target_again(settings):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)

    send_target(campaign, ada, "email", build=build_contact_email)
    start_selection(campaign, ["email"], build=BUILD)

    assert Missive.objects.filter(campaign=campaign).count() == 1


@pytest.mark.django_db
def test_send_target_attaches_the_row_before_delivering(settings):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    campaign = _campaign()
    ada = _contact("ada@example.com")
    select(campaign, "email", ada)
    seen = []
    send_missive = Missive.send_missive

    def spy(missive, *args, **kwargs):
        row = CampaignTarget.objects.get(campaign=campaign)
        seen.append(row.missive_id == missive.pk)
        return send_missive(missive, *args, **kwargs)

    with patch.object(Missive, "send_missive", spy):
        send_target(campaign, ada, "email", build=build_contact_email)

    assert seen == [True]


@pytest.mark.django_db
def test_start_selection_rejects_an_unknown_channel():
    campaign = _campaign()
    with pytest.raises(ValidationError):
        start_selection(campaign, ["pigeon"], build=BUILD)


@pytest.mark.django_db
def test_campaign_counts_targets_still_without_a_missive():
    campaign = _campaign()
    ada = _contact("ada@example.com")
    grace = _contact("grace@example.com", first="Grace")
    select(campaign, "email", [ada, grace])
    select(campaign, "sms", ada)

    pending = CampaignTarget.objects.filter(campaign=campaign, missive__isnull=True)
    pending.first().attach_missive(
        Missive.objects.create(
            campaign=campaign,
            missive_type=MissiveType.EMAIL,
            subject="Hi",
            body_text="Hi",
            status=MissiveStatus.DRAFT,
        )
    )

    annotated = MissiveCampaign.objects.with_counts("count_target_pending").get(pk=campaign.pk)
    assert annotated.count_target_pending == 2

    plain = MissiveCampaign.objects.get(pk=campaign.pk)
    assert plain.count_target_pending == 2
    assert MissiveCampaign.objects.with_counts().get(pk=_campaign().pk).count_target_pending == 0


@pytest.mark.django_db
def test_campaign_contact_selects_and_builds_email_or_sms():
    campaign = _campaign()
    ada = create_campaign_contact(
        "Ada",
        "Lovelace",
        emails=["ada@example.com"],
        phones=["+33612345678"],
    )
    assert select(campaign, "email", ada) == 1
    assert select(campaign, "sms", ada) == 1

    email, created = materialize_missive(
        campaign,
        ada,
        "email",
        build=build_campaign_contact,
    )
    assert created is True
    assert email.to_missiverecipient.get().email == "ada@example.com"

    sms, created = materialize_missive(
        campaign,
        ada,
        "sms",
        build=build_campaign_contact,
    )
    assert created is True
    assert str(sms.to_missiverecipient.get().phone) == "+33612345678"

    letter, created = materialize_missive(
        campaign,
        ada,
        "letter",
        build=build_campaign_contact,
    )
    assert letter is None
    assert created is False


@pytest.mark.django_db
def test_campaign_contact_exposes_the_first_and_all_contact_points():
    ada = create_campaign_contact(
        "Ada",
        "Lovelace",
        emails=["ada@example.com", "ada.work@example.com"],
        phones=["+33612345678"],
        addresses=[{"address_line1": "1 rue A", "postal_code": "75001", "city": "Paris"}],
    )

    assert ada.email == "ada@example.com"
    assert ada.emails == ["ada@example.com", "ada.work@example.com"]
    assert ada.phone == "+33612345678"
    assert ada.phones == ["+33612345678"]
    assert dict(ada.address) == {
        "address_line1": "1 rue A",
        "postal_code": "75001",
        "city": "Paris",
    }
    assert ada.addresses == [ada.address]

    bare = create_campaign_contact("Bob", "Nobody")
    assert (bare.email, bare.phone, bare.address) == ("", "", {})
    assert (bare.emails, bare.phones, bare.addresses) == ([], [], [])


@pytest.mark.django_db
def test_generate_campaign_contacts_fills_every_channel():
    contacts = generate_campaign_contacts(3, emails=2, phones=1, addresses=2)

    assert len(contacts) == 3
    assert len({contact.email for contact in contacts}) == 3
    for contact in contacts:
        assert len(contact.emails) == 2
        assert contact.phone.startswith("+336")
        assert len(contact.addresses) == 2
        assert contact.address["city"]


@pytest.mark.django_db
def test_seed_command_tops_up_campaign_contacts():
    from django.core.management import call_command

    call_command("seed_fake_contacts", ncampaigncontact=2)
    call_command("seed_fake_contacts", ncampaigncontact=3, phones=1, addresses=0)

    assert CampaignContact.objects.count() == 3
    assert [len(contact.phones) for contact in CampaignContact.objects.order_by("pk")] == [2, 2, 1]
    assert CampaignContact.objects.order_by("pk").last().addresses == []


@pytest.mark.django_db
def test_admin_view_generates_campaign_contacts():
    from django.test import Client
    from django.urls import reverse

    client = Client()
    client.force_login(_superuser("fake-generator"))
    url = reverse("admin:fakeapp_campaigncontact_generate_contacts")

    assert client.get(url).status_code == 200
    response = client.post(
        url,
        {"count": 4, "emails": 3, "phones": 0, "addresses": 1, "seed": ""},
    )

    assert response.status_code == 302
    assert CampaignContact.objects.count() == 4
    changelist = client.get(reverse("admin:fakeapp_campaigncontact_changelist"))
    assert url in changelist.content.decode()
    contact = CampaignContact.objects.first()
    assert (len(contact.emails), contact.phones, len(contact.addresses)) == (3, [], 1)


@pytest.mark.django_db
def test_build_target_links_the_object_and_expands_every_contact(settings):
    from django_pymissive.managers.related_object import object_id_value
    from django_pymissive.processors.build_target import build_target_processor

    settings.PYMISSIVE_BUILD_TARGET_FIELDS = {
        "name": ["name", "full_name"],
        "email": ["email"],
        "emails": ["emails"],
        "phone": ["phone"],
        "phones": ["phones"],
        "address": ["address"],
        "addresses": ["addresses"],
    }
    campaign = _campaign()
    ada = create_campaign_contact(
        "Ada",
        "Lovelace",
        emails=["ada@example.com", "ada.work@example.com"],
        phones=["+33612345678", "+33600000000"],
        addresses=[
            {"address_line1": "1 rue A", "city": "Paris"},
            {"address_line1": "2 rue B", "city": "Lyon"},
        ],
    )

    email = build_target_processor(campaign, ada, "email", full_targets=True)
    assert email.status == MissiveStatus.DRAFT
    assert email.to_missiverecipient.get(email="ada@example.com").name == "Ada Lovelace"
    assert set(email.to_missiverecipient.values_list("email", flat=True)) == {
        "ada@example.com",
        "ada.work@example.com",
    }
    link = email.to_missiverelatedobject.get()
    assert link.content_type == ContentType.objects.get_for_model(CampaignContact)
    assert link.object_id == object_id_value(ada.pk)

    sms = build_target_processor(campaign, ada, "sms", full_targets=True)
    assert {str(recipient.phone) for recipient in sms.to_missiverecipient.all()} == {
        "+33612345678",
        "+33600000000",
    }

    postal = build_target_processor(campaign, ada, "letter", full_targets=True)
    cities = {recipient.address["city"] for recipient in postal.to_missiverecipient.all()}
    assert cities == {"Paris", "Lyon"}

    only_one = build_target_processor(campaign, ada, "email", full_targets=False)
    assert list(only_one.to_missiverecipient.values_list("email", flat=True)) == [
        "ada@example.com",
    ]


@pytest.mark.django_db
def test_build_target_reads_only_the_configured_fields(settings):
    from django_pymissive.processors.build_target import build_target_processor

    settings.PYMISSIVE_BUILD_TARGET_FIELDS = {
        "name": ["label"],
        "email": ["mail"],
        "emails": ["extra_mails"],
    }
    campaign = _campaign()
    ada = create_campaign_contact(
        "Ada",
        "Lovelace",
        emails=["ignored@example.com", "also-ignored@example.com"],
    )
    ada.label = "Ada"
    ada.mail = "ada@example.com"
    ada.extra_mails = ["ada.work@example.com", "ada@example.com"]

    email = build_target_processor(campaign, ada, "email", full_targets=True)
    assert email.to_missiverecipient.get(email="ada@example.com").name == "Ada"
    assert set(email.to_missiverecipient.values_list("email", flat=True)) == {
        "ada@example.com",
        "ada.work@example.com",
    }

    only_mail = build_target_processor(campaign, ada, "email", full_targets=False)
    assert list(only_mail.to_missiverecipient.values_list("email", flat=True)) == [
        "ada@example.com",
    ]


def _target_admin_request(user):
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    request = RequestFactory().post("/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _superuser(username="target-admin"):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        username=username,
        email=f"{username}@example.com",
        password="x",
    )


@pytest.mark.django_db
def test_generate_missive_action_builds_a_draft_and_opens_it():
    from django.contrib import admin
    from django.urls import reverse

    campaign = _campaign()
    ada = create_campaign_contact("Ada", "Lovelace", emails=["ada@example.com"])
    select(campaign, "email", ada)
    row = CampaignTarget.objects.get(campaign=campaign)
    model_admin = admin.site._registry[CampaignTarget]
    request = _target_admin_request(_superuser())
    view = getattr(type(model_admin), "generate_missive")

    assert "generate_missive" in model_admin.get_submit_actions(request, row)
    assert "confirm" in view(model_admin, request, row, confirmed=False)

    response = view(model_admin, request, row, confirmed=True)
    row.refresh_from_db()
    assert row.missive_id
    assert row.missive.status == MissiveStatus.DRAFT
    assert response.url == reverse(
        "admin:django_pymissive_missive_change",
        args=[row.missive_id],
    )
    assert "generate_missive" not in model_admin.get_submit_actions(request, row)


@pytest.mark.django_db
def test_target_build_target_processors_replace_the_default(settings):
    from django_pymissive.services import selection_build

    settings.PYMISSIVE_DEFAULT_BUILD_TARGET_PROCESSORS = [
        "tests.fakeapp.campaign_targets.does_not_exist",
    ]
    campaign = _campaign()
    ada = create_campaign_contact("Ada", "Lovelace", emails=["ada@example.com"])
    select(campaign, "email", ada)
    row = CampaignTarget.objects.get(campaign=campaign)
    assert resolve_build_target_processors(row) == settings.PYMISSIVE_DEFAULT_BUILD_TARGET_PROCESSORS

    row.build_target_processors = ["tests.test_campaign_target.build_marked"]
    row.save(update_fields=["build_target_processors"])
    missive, created = materialize_missive(
        campaign,
        ada,
        "email",
        build=selection_build(row, build=build_campaign_contact),
    )
    assert created is True
    assert missive.subject == "from-target-processor"


@pytest.mark.django_db
def test_a_run_chain_emptied_after_creation_stays_empty():
    campaign = _campaign()
    campaign.build_target_processors = [BUILD]
    campaign.save(update_fields=["build_target_processors"])
    run = MissiveScheduledCampaign.objects.create(campaign=campaign)
    assert run.build_target_processors == [BUILD]

    run.build_target_processors = []
    run.save()

    run.refresh_from_db()
    assert run.build_target_processors == []


@pytest.mark.django_db
def test_prefetch_pending_targets_matches_the_per_run_lookup(django_assert_num_queries):
    from django_pymissive.models.scheduler import SELECTION_TASK

    campaign = _campaign()
    select(campaign, "email", [_contact("ada@example.com"), _contact("bob@example.com", "Bob")])
    select(campaign, "sms", _contact("eve@example.com", "Eve"))
    run = MissiveScheduledCampaign.objects.create(
        campaign=campaign,
        external_task_backend=SELECTION_TASK,
        additional_config={"missive_types": ["email"]},
    )
    expected = MissiveScheduledCampaign.objects.get(pk=run.pk).pending_targets_by_type()

    runs = list(MissiveScheduledCampaign.objects.filter(pk=run.pk))
    with django_assert_num_queries(1):
        MissiveScheduledCampaign.prefetch_pending_targets(runs)
    with django_assert_num_queries(0):
        assert runs[0].pending_targets_by_type() == expected == {"email": 2}


@pytest.mark.django_db
def test_checkpoint_stops_a_cancelled_run():
    from django.utils import timezone

    run = MissiveScheduledCampaign.objects.create(campaign=_campaign())
    assert run.checkpoint() is False
    now = timezone.now()
    MissiveScheduledCampaign.objects.filter(pk=run.pk).update(
        send_date=now,
        cancelled_at=now,
        cancel_reason="stop",
    )
    assert run.checkpoint() is True
    assert run.cancel_reason == "stop"


@pytest.mark.django_db
def test_schedule_copies_the_campaign_chain_when_its_own_is_empty():
    campaign = _campaign()
    campaign.build_target_processors = [
        "tests.fakeapp.campaign_targets.build_campaign_contact",
    ]
    campaign.save(update_fields=["build_target_processors"])

    copied = MissiveScheduledCampaign.objects.create(campaign=campaign)
    assert copied.build_target_processors == campaign.build_target_processors

    custom = MissiveScheduledCampaign.objects.create(
        campaign=campaign,
        build_target_processors=["tests.test_campaign_target.build_marked"],
    )
    assert custom.build_target_processors == ["tests.test_campaign_target.build_marked"]

    ada = create_campaign_contact("Ada", "Lovelace", emails=["ada@example.com"])
    select(campaign, "email", ada)
    row = CampaignTarget.objects.get(campaign=campaign)
    assert resolve_build_target_processors(row) == campaign.build_target_processors
    assert resolve_build_target_processors(row, scheduler=custom) == custom.build_target_processors

    from django_pymissive.services import selection_build

    missive, created = materialize_missive(
        campaign,
        ada,
        "email",
        build=selection_build(row, scheduler=custom),
    )
    assert created is True
    assert missive.subject == "from-target-processor"


@pytest.mark.django_db
def test_start_selection_build_becomes_the_run_chain_and_beats_the_campaign(
    settings, django_capture_on_commit_callbacks
):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    campaign = _campaign()
    campaign.build_target_processors = [
        "tests.fakeapp.campaign_targets.build_campaign_contact",
    ]
    campaign.save(update_fields=["build_target_processors"])
    select(campaign, "email", create_campaign_contact("Ada", "Lovelace", emails=["ada@example.com"]))

    with django_capture_on_commit_callbacks(execute=True):
        run = start_selection(campaign, ["email"], build="tests.test_campaign_target.build_marked")

    run.refresh_from_db()
    assert run.build_target_processors == ["tests.test_campaign_target.build_marked"]
    assert "build" not in run.additional_config
    assert Missive.objects.get(campaign=campaign).subject == "from-target-processor"


@pytest.mark.django_db
def test_start_selection_without_build_uses_the_campaign_chain(settings, django_capture_on_commit_callbacks):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    campaign = _campaign()
    campaign.build_target_processors = ["tests.test_campaign_target.build_marked"]
    campaign.save(update_fields=["build_target_processors"])
    select(campaign, "email", create_campaign_contact("Ada", "Lovelace", emails=["ada@example.com"]))

    with django_capture_on_commit_callbacks(execute=True):
        run = start_selection(campaign, ["email"])

    run.refresh_from_db()
    assert run.build_target_processors == campaign.build_target_processors
    assert Missive.objects.get(campaign=campaign).subject == "from-target-processor"


@pytest.mark.django_db
def test_start_campaign_builds_and_sends_the_pending_targets(settings, django_capture_on_commit_callbacks):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    campaign = _campaign()
    select(
        campaign,
        "email",
        [
            _contact("ada@example.com"),
            _contact("grace@example.com", "Grace"),
            _contact("linus@example.com", "Linus"),
        ],
    )

    with django_capture_on_commit_callbacks(execute=True):
        run = campaign.start_campaign()

    run.refresh_from_db()
    assert run.external_task_backend.endswith("run_selection")
    assert run.additional_config["missive_types"] == ["email"]
    assert run.ended_at is not None
    assert CampaignTarget.objects.filter(campaign=campaign, missive__isnull=False).count() == 3
    assert set(
        Missive.objects.filter(campaign=campaign).values_list(
            "to_missiverecipient__email",
            flat=True,
        )
    ) == {"ada@example.com", "grace@example.com", "linus@example.com"}


@pytest.mark.django_db
def test_start_campaign_without_targets_only_sends_existing_drafts():
    run = _campaign().start_campaign()

    assert run.external_task_backend == ""
    assert run.additional_config == {}


@pytest.mark.django_db
def test_generate_missive_action_stays_when_no_build_is_configured(settings):
    from django.contrib import admin
    from django.urls import reverse

    settings.PYMISSIVE_DEFAULT_BUILD_TARGET_PROCESSORS = []
    campaign = _campaign()
    ada = create_campaign_contact("Ada", "Lovelace", emails=["ada@example.com"])
    select(campaign, "email", ada)
    row = CampaignTarget.objects.get(campaign=campaign)
    model_admin = admin.site._registry[CampaignTarget]
    request = _target_admin_request(_superuser("target-admin-nobuild"))
    view = getattr(type(model_admin), "generate_missive")

    response = view(model_admin, request, row, confirmed=True)
    row.refresh_from_db()
    assert row.missive_id is None
    assert response.url == reverse(
        "admin:django_pymissive_campaigntarget_change",
        args=[row.pk],
    )


@pytest.mark.django_db
def test_generate_missive_action_refuses_a_view_only_account():
    from django.contrib import admin
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission
    from django.core.exceptions import PermissionDenied

    campaign = _campaign()
    ada = create_campaign_contact("Ada", "Lovelace", emails=["ada@example.com"])
    select(campaign, "email", ada)
    row = CampaignTarget.objects.get(campaign=campaign)
    user = get_user_model().objects.create_user(
        username="target-viewer",
        password="x",
        is_staff=True,
    )
    user.user_permissions.add(
        Permission.objects.get(codename="view_campaigntarget"),
    )
    user = get_user_model().objects.get(pk=user.pk)
    model_admin = admin.site._registry[CampaignTarget]
    request = _target_admin_request(user)
    view = getattr(type(model_admin), "generate_missive")

    assert model_admin.has_generate_missive_permission(request, row) is False
    with pytest.raises(PermissionDenied):
        view(model_admin, request, row, confirmed=True)
    assert CampaignTarget.objects.get(pk=row.pk).missive_id is None


def build_unsaved(campaign, target, missive_type):
    return Missive(campaign=campaign, missive_type=missive_type)


def _generate_from_admin(row, username):
    from django.contrib import admin

    model_admin = admin.site._registry[CampaignTarget]
    request = _target_admin_request(_superuser(username))
    response = type(model_admin).generate_missive(model_admin, request, row, confirmed=True)
    return response, [str(m) for m in request._messages]


@pytest.mark.django_db
def test_missive_change_page_links_to_its_campaign_target():
    from django.test import Client
    from django.urls import reverse
    from django.utils.html import escape

    campaign = _campaign()
    select(campaign, "email", _contact("ada@example.com"))
    row = CampaignTarget.objects.get(campaign=campaign)
    row.missive = Missive.objects.create(campaign=campaign, missive_type="email")
    row.save(update_fields=["missive"])
    client = Client()
    client.force_login(_superuser("target-admin-missive-link"))

    response = client.get(reverse("admin:django_pymissive_missive_change", args=[row.missive_id]))

    assert response.status_code == 200
    row_url = reverse("admin:django_pymissive_campaigntarget_change", args=[row.pk])
    assert f'<a href="{row_url}">{escape(row.object_str)}</a>' in response.content.decode()

    changelist = client.get(reverse("admin:django_pymissive_missive_changelist"))
    assert row_url not in changelist.content.decode()


@pytest.mark.django_db
def test_generate_missive_action_reports_a_broken_build_instead_of_crashing():
    campaign = _campaign()
    select(campaign, "email", _contact("ada@example.com"))
    row = CampaignTarget.objects.get(campaign=campaign)
    row.build_target_processors = ["tests.test_campaign_target.build_unsaved"]
    row.save(update_fields=["build_target_processors"])

    response, sent = _generate_from_admin(row, "target-admin-broken")

    assert response.status_code == 302
    assert any("saved missive" in message for message in sent)
    assert CampaignTarget.objects.get(pk=row.pk).missive_id is None


@pytest.mark.django_db
def test_abandon_action_keeps_the_reason_and_removes_the_buttons():
    from django.contrib import admin

    campaign = _campaign()
    select(campaign, "email", _contact("ada@example.com"))
    row = CampaignTarget.objects.get(campaign=campaign)
    model_admin = admin.site._registry[CampaignTarget]
    request = _target_admin_request(_superuser("target-admin-abandon"))
    view = type(model_admin).abandon

    assert "abandon" in model_admin.get_submit_actions(request, row)
    assert "form" in view(model_admin, request, row)
    form = view(model_admin, request, row)["form"].__class__({"abandon_reason": "moved away"})
    assert form.is_valid()
    view(model_admin, request, row, form=form)

    row.refresh_from_db()
    assert row.abandon_reason == "moved away"
    actions = model_admin.get_submit_actions(request, row)
    assert "abandon" not in actions
    assert "generate_missive" not in actions


@pytest.mark.django_db
def test_bulk_abandon_skips_rows_that_already_have_a_missive():
    from django.contrib import admin

    campaign = _campaign()
    select(campaign, "email", [_contact("ada@example.com"), _contact("grace@example.com")])
    sent = CampaignTarget.objects.filter(campaign=campaign).first()
    sent.attach_missive(
        Missive.objects.create(
            campaign=campaign,
            missive_type=MissiveType.EMAIL,
            subject="Hi",
        )
    )
    model_admin = admin.site._registry[CampaignTarget]
    request = _target_admin_request(_superuser("target-admin-bulk"))

    model_admin.abandon_selected(request, CampaignTarget.objects.filter(campaign=campaign))

    assert list(
        CampaignTarget.objects.filter(campaign=campaign, abandoned_at__isnull=False).values_list(
            "missive_id", flat=True
        )
    ) == [None]
    assert [str(m) for m in request._messages] == ["1 target abandoned."]


@pytest.mark.django_db
def test_generate_missive_action_refuses_while_the_campaign_is_sending():
    campaign = _campaign()
    select(campaign, "email", _contact("ada@example.com"))
    campaign.to_missivecampaignsend.create()
    row = CampaignTarget.objects.get(campaign=campaign)

    response, sent = _generate_from_admin(row, "target-admin-sending")

    assert response.status_code == 302
    assert "A campaign send is already in progress." in sent
    assert CampaignTarget.objects.get(pk=row.pk).missive_id is None
    assert not Missive.objects.filter(campaign=campaign).exists()
