"""Tests for :meth:`Missive.missive_context` related-object exposition.

Covers the new ``<ct_name>`` (singular shortcut) + ``<ct_name>_list``
(always-a-list) convention, replacing the legacy "1 related object per
content_type" cap.
"""

from __future__ import annotations

import pytest

from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.missive import Missive
from django_pymissive.models.related_object import (
    CampaignRelatedObject,
    MissiveRelatedObject,
)
from tests.fakeapp.models import PdfDocument

pytestmark = pytest.mark.django_db


def _make_email_missive(**overrides) -> Missive:
    defaults = {
        "missive_type": "email",
        "subject": "ctx",
        "body_html": "<p>hi</p>",
    }
    defaults.update(overrides)
    return Missive.objects.create(**defaults)


def _attach_related(missive_or_campaign, doc: PdfDocument):
    if isinstance(missive_or_campaign, Missive):
        return MissiveRelatedObject.objects.create(
            missive=missive_or_campaign, content_object=doc
        )
    return CampaignRelatedObject.objects.create(
        campaign=missive_or_campaign, content_object=doc
    )


# ---------------------------------------------------------------------------
# Cardinality contract: 0, 1, N related objects of the same content_type
# ---------------------------------------------------------------------------


def test_missive_context_no_related_objects_has_no_ct_keys():
    """Without any related object, neither the singular nor the ``_list`` key
    appear — clients can rely on ``ct in context`` being false."""
    missive = _make_email_missive()
    ctx = missive.missive_context()
    assert "pdfdocument" not in ctx
    assert "pdfdocument_list" not in ctx


def test_missive_context_single_related_object_exposes_singular_and_list_of_one():
    """One related object → singular shortcut **and** a list of exactly one item."""
    missive = _make_email_missive()
    doc = PdfDocument.objects.create(name="alpha")
    _attach_related(missive, doc)

    ctx = missive.missive_context()

    assert "pdfdocument" in ctx
    assert "pdfdocument_list" in ctx
    assert isinstance(ctx["pdfdocument_list"], list)
    assert len(ctx["pdfdocument_list"]) == 1
    # Singular MUST be identical to the first list element so templates
    # using either form see the same object.
    assert ctx["pdfdocument"] == ctx["pdfdocument_list"][0]
    assert ctx["pdfdocument"]["name"] == "alpha"
    # to_context_dict() extras are merged in.
    assert ctx["pdfdocument"]["display_name"] == "ALPHA"


def test_missive_context_multiple_related_objects_all_appear_in_list():
    """N related objects of the same type → list of N; singular = most-recent."""
    missive = _make_email_missive()
    a = PdfDocument.objects.create(name="alpha")
    b = PdfDocument.objects.create(name="bravo")
    c = PdfDocument.objects.create(name="charlie")
    _attach_related(missive, a)
    _attach_related(missive, b)
    _attach_related(missive, c)

    ctx = missive.missive_context()

    assert len(ctx["pdfdocument_list"]) == 3
    names = {item["name"] for item in ctx["pdfdocument_list"]}
    assert names == {"alpha", "bravo", "charlie"}
    # ``BaseRelatedObject.Meta.ordering = ["-created_at"]`` ⇒ the singular
    # shortcut points at the most-recent attachment (``charlie``).
    assert ctx["pdfdocument"]["name"] == "charlie"
    # And it is always equal to the first list element regardless of N.
    assert ctx["pdfdocument"] == ctx["pdfdocument_list"][0]


# ---------------------------------------------------------------------------
# Union semantics: missive + campaign, deduplicated by (content_type, pk)
# ---------------------------------------------------------------------------


def test_missive_context_unions_missive_and_campaign_objects():
    """When both the campaign AND the missive declare related objects of the
    same type, the resulting list is the **union** of both (missive first,
    campaign second). The campaign's objects are not hidden.
    """
    campaign = MissiveCampaign.objects.create(subject="camp")
    missive = _make_email_missive(campaign=campaign)

    # Campaign: 2 PdfDocuments.
    _attach_related(campaign, PdfDocument.objects.create(name="camp-A"))
    _attach_related(campaign, PdfDocument.objects.create(name="camp-B"))

    # Missive: 1 distinct PdfDocument of the same type.
    _attach_related(missive, PdfDocument.objects.create(name="miss-only"))

    ctx = missive.missive_context()

    list_names = [item["name"] for item in ctx["pdfdocument_list"]]
    # 3 distinct objects, missive's come first → singular is the missive one.
    assert set(list_names) == {"miss-only", "camp-A", "camp-B"}
    assert list_names[0] == "miss-only"
    assert ctx["pdfdocument"]["name"] == "miss-only"


def test_missive_context_dedups_same_object_attached_on_both_layers():
    """The same object attached on both the missive AND the campaign must
    appear only once in the resulting list (deduped by content_type + pk)."""
    campaign = MissiveCampaign.objects.create(subject="camp")
    missive = _make_email_missive(campaign=campaign)

    shared = PdfDocument.objects.create(name="shared")
    only_campaign = PdfDocument.objects.create(name="only-campaign")
    only_missive = PdfDocument.objects.create(name="only-missive")

    _attach_related(campaign, shared)
    _attach_related(campaign, only_campaign)
    _attach_related(missive, shared)  # also attached on missive → must dedup
    _attach_related(missive, only_missive)

    ctx = missive.missive_context()

    list_names = [item["name"] for item in ctx["pdfdocument_list"]]
    assert sorted(list_names) == ["only-campaign", "only-missive", "shared"], (
        f"shared object must appear exactly once, got {list_names!r}"
    )
    # Missive-only objects come before campaign-only — "shared" is iterated
    # via the missive (kept), so it appears in the missive segment.
    assert list_names.index("only-missive") < list_names.index("only-campaign")
    assert list_names.index("shared") < list_names.index("only-campaign")


def test_missive_context_falls_back_to_campaign_when_missive_has_none_for_type():
    """If the missive has no related object of a given content_type, the
    campaign's list is exposed unchanged for that type."""
    campaign = MissiveCampaign.objects.create(subject="camp")
    missive = _make_email_missive(campaign=campaign)

    _attach_related(campaign, PdfDocument.objects.create(name="camp-A"))
    _attach_related(campaign, PdfDocument.objects.create(name="camp-B"))

    ctx = missive.missive_context()

    list_names = sorted(item["name"] for item in ctx["pdfdocument_list"])
    assert list_names == ["camp-A", "camp-B"]
    # Singular tracks the most-recent campaign object (Meta.ordering = -created_at).
    assert ctx["pdfdocument"]["name"] == "camp-B"


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_missive_context_singular_is_always_first_of_list():
    """Invariant under any cardinality / source: ``context[ct] == context[ct + '_list'][0]``."""
    campaign = MissiveCampaign.objects.create(subject="camp")
    missive = _make_email_missive(campaign=campaign)
    for name in ("c1", "c2"):
        _attach_related(campaign, PdfDocument.objects.create(name=name))
    for name in ("m1", "m2", "m3"):
        _attach_related(missive, PdfDocument.objects.create(name=name))

    ctx = missive.missive_context()
    assert ctx["pdfdocument"] == ctx["pdfdocument_list"][0]
    # And the singular is the most-recent missive object (most specific).
    assert ctx["pdfdocument"]["name"] == "m3"
