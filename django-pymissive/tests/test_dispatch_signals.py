"""Public missive lifecycle signals."""

from unittest.mock import patch

import pytest

from django_pymissive.dispatch_signals import (
    missive_post_duplicate,
    missive_post_send,
    missive_pre_duplicate,
    missive_pre_send,
)
from django_pymissive.models.choices import MissiveThreadType, MissiveType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _capture(signal):
    calls = []

    def receiver(sender, **kwargs):
        calls.append((sender, kwargs))

    signal.connect(receiver, weak=False)
    return calls, receiver


def test_duplicate_emits_pre_and_post_signals():
    source = Missive.objects.create(missive_type=MissiveType.EMAIL, subject="Original")
    pre_calls, pre_receiver = _capture(missive_pre_duplicate)
    post_calls, post_receiver = _capture(missive_post_duplicate)

    try:
        duplicate = source.duplicate_missive(
            thread_type=MissiveThreadType.HISTORY,
            thread_id=source.thread_id,
            resend=True,
        )
    finally:
        missive_pre_duplicate.disconnect(pre_receiver)
        missive_post_duplicate.disconnect(post_receiver)

    pre_sender, pre = pre_calls[0]
    assert pre_sender is Missive
    assert pre["source_missive"].pk == source.pk
    assert pre["resend"] is True
    assert pre["thread_type"] == MissiveThreadType.HISTORY
    assert pre["thread_id"] == source.thread_id

    post_sender, post = post_calls[0]
    assert post_sender is Missive
    assert post["source_missive"].pk == source.pk
    assert post["new_missive"] == duplicate
    assert post["resend"] is True


def test_send_emits_pre_and_post_signals(settings):
    settings.PYMISSIVE_DRY_RUN = True
    missive = Missive.objects.create(missive_type=MissiveType.EMAIL, subject="Signal")
    old_missive = Missive(missive_type=MissiveType.EMAIL)
    pre_calls, pre_receiver = _capture(missive_pre_send)
    post_calls, post_receiver = _capture(missive_post_send)

    try:
        with (
            patch.object(Missive, "_claim_send"),
            patch.object(Missive, "set_locally_ifnull"),
            patch.object(Missive, "get_serialized_data", return_value={}),
        ):
            missive.send_missive(old_missive=old_missive)
    finally:
        missive_pre_send.disconnect(pre_receiver)
        missive_post_send.disconnect(post_receiver)

    assert pre_calls == [
        (
            Missive,
            {
                "signal": missive_pre_send,
                "missive": missive,
                "old_missive": old_missive,
            },
        )
    ]
    assert post_calls == [
        (
            Missive,
            {
                "signal": missive_post_send,
                "missive": missive,
                "old_missive": old_missive,
            },
        )
    ]
