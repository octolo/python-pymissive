"""Force-release entry points for crashed scheduled campaign runs."""

from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_pymissive.models import (
    Missive,
    MissiveCampaign,
    MissiveScheduledCampaign,
    MissiveStatus,
)
from django_pymissive.task.campaign import (
    enqueue_force_release_run,
    force_release_run,
)

pytestmark = pytest.mark.django_db


def _running_run():
    campaign = MissiveCampaign.objects.create(subject="Crashed run")
    run = MissiveScheduledCampaign.objects.create(
        campaign=campaign,
        send_date=timezone.now(),
    )
    return campaign, run


def _processing(campaign, run, *, external_id=None):
    return Missive.objects.create(
        campaign=campaign,
        scheduler=run,
        missive_type="email",
        subject="Queued",
        status=MissiveStatus.PROCESSING,
        external_id=external_id,
    )


def test_force_release_ends_run_and_only_reopens_unaccepted_missives():
    campaign, run = _running_run()
    unaccepted = _processing(campaign, run)
    accepted = _processing(campaign, run, external_id="provider-1")

    reopened = run.force_release("worker host stopped")

    run.refresh_from_db()
    unaccepted.refresh_from_db()
    accepted.refresh_from_db()
    assert reopened == 1
    assert run.ended_at is not None
    assert run.additional_config["last_error"] == "worker host stopped"
    assert unaccepted.status == MissiveStatus.DRAFT
    assert accepted.status == MissiveStatus.PROCESSING
    with pytest.raises(ValidationError, match="in progress"):
        run.force_release()


def test_force_release_task_and_enqueue_helper():
    campaign, run = _running_run()
    missive = _processing(campaign, run)

    assert force_release_run(run.pk, "task release") == 1
    missive.refresh_from_db()
    assert missive.status == MissiveStatus.DRAFT

    backend = Mock()
    with patch("django_pymissive.task.get_task_backend", return_value=backend):
        enqueue_force_release_run(run.pk, "queued release")
    backend.enqueue.assert_called_once_with(force_release_run, str(run.pk), "queued release")


def test_force_release_management_command():
    campaign, run = _running_run()
    missive = _processing(campaign, run)
    stdout = StringIO()

    call_command(
        "force_release_run",
        str(run.pk),
        reason="operator release",
        stdout=stdout,
    )

    run.refresh_from_db()
    missive.refresh_from_db()
    assert run.additional_config["last_error"] == "operator release"
    assert missive.status == MissiveStatus.DRAFT
    assert "reopened 1 processing missive" in stdout.getvalue()


def test_force_release_admin_action_warns_and_releases():
    campaign, run = _running_run()
    missive = _processing(campaign, run)
    user = get_user_model().objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="x",
    )
    client = Client()
    client.force_login(user)
    url = reverse(
        "admin:django_pymissive_missivescheduledcampaign_force_release_run",
        args=[run.pk],
    )

    confirmation = client.get(url)
    assert confirmation.status_code == 200
    assert b"duplicate deliveries" in confirmation.content
    response = client.post(url, {"reason": "admin release"})

    assert response.status_code == 302
    run.refresh_from_db()
    missive.refresh_from_db()
    assert run.additional_config["last_error"] == "admin release"
    assert missive.status == MissiveStatus.DRAFT
