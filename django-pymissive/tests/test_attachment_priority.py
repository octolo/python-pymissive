"""Page-order priorities are unique per missive and assigned under a parent lock."""

from __future__ import annotations

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction

from django_pymissive.models.attachment import FIRST_DOCUMENT_PRIORITY, MissiveBaseAttachment
from django_pymissive.models.choices import MissiveAttachmentType
from django_pymissive.models.missive import Missive
from django_pymissive.utils import recalculate_attachment_priorities

pytestmark = pytest.mark.django_db


def _missive() -> Missive:
    return Missive.objects.create(missive_type="email", subject="Priority")


def _attach(missive, *, name="doc.pdf", content=b"x", **kwargs) -> MissiveBaseAttachment:
    return MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.ATTACHMENT,
        attachment_file=ContentFile(content, name=name),
        **kwargs,
    )


def test_sequential_inserts_get_1_then_2():
    missive = _missive()
    first = _attach(missive, name="a.pdf")
    second = _attach(missive, name="b.pdf")
    assert first.priority == 1
    assert second.priority == 2


def test_first_document_keeps_zero_and_does_not_shift_annexes():
    missive = _missive()
    letter = _attach(missive, name="first-document-letter.pdf", priority=FIRST_DOCUMENT_PRIORITY)
    annex = _attach(missive, name="annex.pdf")
    assert letter.priority == FIRST_DOCUMENT_PRIORITY
    assert letter.is_first_document is True
    assert annex.priority == 1
    assert annex.is_first_document is False


def test_user_file_named_first_document_is_not_the_letter():
    """Filename is not the definition — only ATTACHMENT at priority 0 is."""
    missive = _missive()
    user = _attach(missive, name="first-document-x.pdf")
    assert user.priority == 1
    assert user.is_first_document is False


def test_proofs_do_not_consume_page_order_slots():
    missive = _missive()
    MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.PROOF,
        attachment_file=ContentFile(b"p", name="proof.pdf"),
    )
    annex = _attach(missive, name="annex.pdf")
    assert annex.priority == 1


def test_unique_priority_per_missive_for_page_order_types():
    missive = _missive()
    _attach(missive, name="a.pdf")
    other = _attach(missive, name="b.pdf")
    with pytest.raises(IntegrityError), transaction.atomic():
        MissiveBaseAttachment.objects.filter(pk=other.pk).update(priority=1)


def test_recalculate_closes_gaps_without_touching_proofs():
    missive = _missive()
    a = _attach(missive, name="a.pdf")
    b = _attach(missive, name="b.pdf")
    proof = MissiveBaseAttachment.objects.create(
        missive=missive,
        attachment_type=MissiveAttachmentType.PROOF,
        attachment_file=ContentFile(b"p", name="proof.pdf"),
    )
    MissiveBaseAttachment.objects.filter(pk=a.pk).update(priority=4)
    MissiveBaseAttachment.objects.filter(pk=b.pk).update(priority=7)
    proof_priority = proof.priority
    recalculate_attachment_priorities(missive_id=missive.pk)
    a.refresh_from_db()
    b.refresh_from_db()
    proof.refresh_from_db()
    assert {a.priority, b.priority} == {1, 2}
    assert proof.priority == proof_priority
