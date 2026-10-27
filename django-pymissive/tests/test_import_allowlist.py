"""PYMISSIVE_ALLOWED_TASK_BACKENDS covers every dotted path read from the database."""

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from django_pymissive.models import CampaignTarget, MissiveCampaign, MissiveScheduledCampaign
from django_pymissive.processors.build_target import apply_build_target_processors
from django_pymissive.services import start_selection
from django_pymissive.utils import get_progress_hooks, is_import_allowed

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def allowlist(settings):
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = ["myapp"]


def test_unset_allowlist_allows_every_path(settings):
    settings.PYMISSIVE_ALLOWED_TASK_BACKENDS = None
    assert is_import_allowed("os.system")


def test_allowlist_matches_prefixes_and_always_allows_the_package():
    assert is_import_allowed("myapp")
    assert is_import_allowed("myapp.hooks.notify")
    assert not is_import_allowed("myapplication.hooks")
    assert not is_import_allowed("os.system")
    assert is_import_allowed("django_pymissive.services.send.run_selection")
    assert is_import_allowed("pymissive.config.missive_support_for_type")


def test_refused_processor_is_never_imported_or_called():
    with patch("os.system") as system:
        with pytest.raises(ImportError, match="not allowed"):
            apply_build_target_processors(None, None, "email", [["os.system", {}]])
    system.assert_not_called()


def test_refused_progress_hook_is_not_imported():
    with pytest.raises(ImportError, match="not allowed"):
        get_progress_hooks("os.getcwd")


def test_start_selection_checks_allowlist_before_importing_build():
    campaign = MissiveCampaign.objects.create(subject="Run")

    with patch("django_pymissive.utils.import_string") as import_string:
        with pytest.raises(ValidationError, match="Cannot import build"):
            start_selection(campaign, ["email"], build="os.system")

    import_string.assert_not_called()


def test_campaign_clean_reports_each_refused_field():
    campaign = MissiveCampaign(
        subject="Run",
        body_processors=[{"processor": "os.system", "kwargs": {}}],
        build_target_processors=["myapp.build", "subprocess.run"],
    )

    with pytest.raises(ValidationError) as exc:
        campaign.clean()

    errors = exc.value.message_dict
    assert set(errors) == {"body_processors", "build_target_processors"}
    assert "subprocess.run" in errors["build_target_processors"][0]
    assert "myapp.build" not in errors["build_target_processors"][0]


def test_run_and_target_clean_refuse_paths_outside_the_allowlist():
    campaign = MissiveCampaign.objects.create(subject="Run")

    run = MissiveScheduledCampaign(campaign=campaign, progress_hook="os.getcwd")
    with pytest.raises(ValidationError) as exc:
        run.clean()
    assert "progress_hook" in exc.value.message_dict

    target = CampaignTarget(campaign=campaign, build_target_processors=["os.system"])
    with pytest.raises(ValidationError) as exc:
        target.clean()
    assert "build_target_processors" in exc.value.message_dict
