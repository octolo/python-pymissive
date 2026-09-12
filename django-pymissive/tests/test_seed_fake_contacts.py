"""Management command ``seed_fake_contacts``: top-up + random related objects."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.missive import Missive
from django_pymissive.models.related_object import (
    CampaignRelatedObject,
    MissiveRelatedObject,
)
from tests.fakeapp.models import Category, Contact

pytestmark = pytest.mark.django_db


def test_seed_requires_an_action():
    with pytest.raises(CommandError, match="Specify"):
        call_command("seed_fake_contacts")


def test_seed_creates_categories_then_contacts_with_category():
    call_command("seed_fake_contacts", ncategory=3, ncontact=5)
    assert Category.objects.count() == 3
    assert Contact.objects.count() == 5
    assert Contact.objects.filter(category__isnull=False).count() == 5


def test_seed_tops_up_only_the_missing_rows():
    Category.objects.create(name="Pro")
    Contact.objects.create(
        first_name="Ada", last_name="Lovelace", email="ada@example.com"
    )
    call_command("seed_fake_contacts", ncategory=3, ncontact=4)
    assert Category.objects.count() == 3
    assert Contact.objects.count() == 4
    call_command("seed_fake_contacts", ncategory=3, ncontact=4)
    assert Category.objects.count() == 3
    assert Contact.objects.count() == 4


def test_seed_randcampaign_and_randmissive_default_to_one_each():
    call_command("seed_fake_contacts", ncategory=2, ncontact=4)
    campaign = MissiveCampaign.objects.create(subject="camp")
    missive = Missive.objects.create(
        missive_type="email", subject="m", body_rich="<p>hi</p>"
    )
    call_command("seed_fake_contacts", randcampaign=1, randmissive=1, seed=1)
    campaign_objs = [
        rel.content_object
        for rel in CampaignRelatedObject.objects.filter(campaign=campaign)
    ]
    missive_objs = [
        rel.content_object
        for rel in MissiveRelatedObject.objects.filter(missive=missive)
    ]
    assert sum(isinstance(obj, Contact) for obj in campaign_objs) == 1
    assert sum(isinstance(obj, Category) for obj in campaign_objs) == 1
    assert sum(isinstance(obj, Contact) for obj in missive_objs) == 1
    assert sum(isinstance(obj, Category) for obj in missive_objs) == 1
    call_command("seed_fake_contacts", randcampaign=1, randmissive=1, seed=2)
    assert CampaignRelatedObject.objects.filter(campaign=campaign).count() == 2
    assert MissiveRelatedObject.objects.filter(missive=missive).count() == 2


def test_seed_rand_count_attaches_n_of_each_type():
    call_command("seed_fake_contacts", ncategory=3, ncontact=4)
    campaign = MissiveCampaign.objects.create(subject="camp")
    missive = Missive.objects.create(
        missive_type="email", subject="m", body_rich="<p>hi</p>"
    )
    call_command("seed_fake_contacts", randcampaign=2, randmissive=2, seed=1)
    campaign_objs = [
        rel.content_object
        for rel in CampaignRelatedObject.objects.filter(campaign=campaign)
    ]
    missive_objs = [
        rel.content_object
        for rel in MissiveRelatedObject.objects.filter(missive=missive)
    ]
    assert sum(isinstance(obj, Contact) for obj in campaign_objs) == 2
    assert sum(isinstance(obj, Category) for obj in campaign_objs) == 2
    assert sum(isinstance(obj, Contact) for obj in missive_objs) == 2
    assert sum(isinstance(obj, Category) for obj in missive_objs) == 2
    assert len({obj.pk for obj in campaign_objs if isinstance(obj, Contact)}) == 2
    assert len({obj.pk for obj in missive_objs if isinstance(obj, Contact)}) == 2
