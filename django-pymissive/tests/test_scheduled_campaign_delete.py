"""A run a worker is still sending cannot be deleted: it must be cancelled first."""

import pytest
from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_pymissive.models import MissiveCampaign, MissiveScheduledCampaign

pytestmark = pytest.mark.django_db

MESSAGE = "A campaign send in progress cannot be deleted: cancel it first."


def _run(**kw):
    campaign = MissiveCampaign.objects.create(subject="Run")
    return MissiveScheduledCampaign.objects.create(campaign=campaign, **kw)


def _sending():
    return _run(send_date=timezone.now())


def _stale():
    past = timezone.now() - timezone.timedelta(hours=2)
    run = _run(send_date=past)
    MissiveScheduledCampaign.objects.filter(pk=run.pk).update(updated_at=past)
    run.refresh_from_db()
    return run


def _admin_client():
    user = get_user_model().objects.create_superuser(username="admin", email="admin@example.com", password="x")
    client = Client()
    client.force_login(user)
    return client


def test_delete_refuses_a_run_being_sent():
    run = _sending()
    with pytest.raises(ProtectedError, match="cancel it first"):
        run.delete()
    with pytest.raises(ProtectedError):
        MissiveScheduledCampaign.objects.filter(pk=run.pk).delete()
    assert MissiveScheduledCampaign.objects.filter(pk=run.pk).exists()


def test_delete_accepts_pending_ended_and_stale_runs():
    pending = _run()
    ended = _run(send_date=timezone.now(), ended_at=timezone.now())
    stale = _stale()
    assert stale.is_running and not stale.is_sending

    pending.delete()
    MissiveScheduledCampaign.objects.filter(pk__in=[ended.pk, stale.pk]).delete()

    assert not MissiveScheduledCampaign.objects.exists()


def test_campaign_delete_refuses_while_one_of_its_runs_is_sent():
    run = _sending()
    with pytest.raises(ProtectedError, match="cancel it first"):
        run.campaign.delete()
    with pytest.raises(ProtectedError):
        MissiveCampaign.objects.filter(pk=run.campaign_id).delete()
    assert MissiveScheduledCampaign.objects.filter(pk=run.pk).exists()


def test_admin_delete_view_tells_to_cancel_first_and_keeps_the_run():
    run = _sending()
    url = reverse("admin:django_pymissive_missivescheduledcampaign_delete", args=[run.pk])
    client = _admin_client()

    page = client.get(url)
    response = client.post(url, {"post": "yes"})

    assert MESSAGE in page.content.decode()
    assert response.status_code == 200
    assert MissiveScheduledCampaign.objects.filter(pk=run.pk).exists()


def test_admin_bulk_delete_tells_to_cancel_first_and_keeps_the_run():
    run = _sending()
    response = _admin_client().post(
        reverse("admin:django_pymissive_missivescheduledcampaign_changelist"),
        {"action": "delete_selected", "_selected_action": [run.pk], "post": "yes"},
    )

    assert MESSAGE in response.content.decode()
    assert MissiveScheduledCampaign.objects.filter(pk=run.pk).exists()


def test_admin_campaign_delete_view_tells_to_cancel_first():
    run = _sending()
    url = reverse("admin:django_pymissive_missivecampaign_delete", args=[run.campaign_id])
    response = _admin_client().post(url, {"post": "yes"})

    assert MESSAGE in response.content.decode()
    assert MissiveCampaign.objects.filter(pk=run.campaign_id).exists()


def test_inline_refuses_to_delete_a_run_being_sent():
    from django_pymissive.admin.scheduler import ScheduledCampaignInlineFormSet
    from django.forms.models import inlineformset_factory

    run = _sending()
    FormSet = inlineformset_factory(
        MissiveCampaign,
        MissiveScheduledCampaign,
        formset=ScheduledCampaignInlineFormSet,
        fields=["comment"],
        extra=0,
        can_delete=True,
    )
    prefix = FormSet.get_default_prefix()
    data = {
        f"{prefix}-TOTAL_FORMS": "1",
        f"{prefix}-INITIAL_FORMS": "1",
        f"{prefix}-0-id": str(run.pk),
        f"{prefix}-0-campaign": str(run.campaign_id),
        f"{prefix}-0-comment": "",
        f"{prefix}-0-DELETE": "on",
    }
    formset = FormSet(data, instance=run.campaign, prefix=prefix)

    assert not formset.is_valid()
    assert MESSAGE in formset.non_form_errors()


def test_inline_adds_runs_but_leaves_existing_ones_untouched():
    from django.contrib import admin
    from django.test import RequestFactory

    from django_pymissive.admin.scheduler import MissiveScheduledCampaignInline

    run = _run(comment="kept")
    campaign = run.campaign
    request = RequestFactory().post("/")
    request.user = get_user_model().objects.create_superuser(username="admin", email="admin@example.com", password="x")
    inline = next(
        i
        for i in admin.site._registry[MissiveCampaign].get_inline_instances(request, campaign)
        if isinstance(i, MissiveScheduledCampaignInline)
    )
    FormSet = inline.get_formset(request, campaign)
    prefix = FormSet.get_default_prefix()
    data = {
        f"{prefix}-TOTAL_FORMS": "2",
        f"{prefix}-INITIAL_FORMS": "1",
        f"{prefix}-0-id": str(run.pk),
        f"{prefix}-0-campaign": str(campaign.pk),
        f"{prefix}-0-missive_type": "sms",
        f"{prefix}-1-campaign": str(campaign.pk),
        f"{prefix}-1-missive_type": "email",
    }
    formset = FormSet(data, instance=campaign, prefix=prefix)

    assert formset.is_valid(), formset.errors
    formset.save()

    run.refresh_from_db()
    assert run.missive_type != "sms"
    assert campaign.to_missivecampaignsend.filter(missive_type="email").exclude(pk=run.pk).exists()
