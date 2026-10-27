from io import StringIO

import pytest
from django.core.management import call_command

from django_pymissive.models import Missive, MissiveCampaign
from django_pymissive.models.choices import MissiveSupport

pytestmark = pytest.mark.django_db


def test_create_dataset_without_campaign():
    output = StringIO()

    call_command(
        "create_missive_dataset",
        3,
        types=["email", "sms"],
        stdout=output,
    )

    missives = Missive.objects.order_by("subject")
    assert missives.count() == 3
    assert not missives.exclude(campaign=None).exists()
    assert sorted(
        missives.values_list(
            "to_missiverecipient__recipient_support",
            flat=True,
        )
    ) == [
        MissiveSupport.EMAIL,
        MissiveSupport.EMAIL,
        MissiveSupport.PHONE,
    ]
    assert "3 standalone missive(s) created" in output.getvalue()


def test_create_dataset_with_new_campaign():
    output = StringIO()

    call_command(
        "create_missive_dataset",
        2,
        types=["registered_letter"],
        campaign_id="",
        subject="Postal dataset",
        stdout=output,
    )

    campaign = MissiveCampaign.objects.get(subject="Postal dataset")
    assert Missive.objects.filter(campaign=campaign).count() == 2
    assert set(
        Missive.objects.filter(campaign=campaign).values_list(
            "to_missiverecipient__recipient_support",
            flat=True,
        )
    ) == {MissiveSupport.ADDRESS}
    assert "2 missive(s) created in campaign" in output.getvalue()
