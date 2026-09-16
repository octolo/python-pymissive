"""Signal handlers for django_pymissive."""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models.choices import MissiveEventType
from .models.event import MissiveEvent

_suppress_event_billings = ContextVar("pymissive_suppress_event_billings", default=False)


@contextmanager
def suppress_event_billings():
    """Skip ``get_billings`` while ingesting a bulk event retrieve."""
    token = _suppress_event_billings.set(True)
    try:
        yield
    finally:
        _suppress_event_billings.reset(token)


def trigger_billings(missive):
    """Queue a billing fetch for ``missive`` when its provider supports them.

    Runs through the configured task backend so a provider outage cannot
    fail ``send_missive`` or a webhook. Callable directly so a caller
    creating several events for the *same* missive can enqueue once.
    """
    if missive is None or not missive.can_billings():
        return
    from .billings import fetch_missive_billings
    from .task import get_task_backend

    get_task_backend().enqueue(fetch_missive_billings, str(missive.pk))


@receiver(post_save, sender=MissiveEvent)
def trigger_billings_on_event(sender, instance, created, **kwargs):
    """Queue get_billings after a new billable event is saved."""
    if not created or _suppress_event_billings.get():
        return
    if instance.event in (MissiveEventType.SUBMITTED, MissiveEventType.REQUEST):
        return
    if instance.missive_id:
        trigger_billings(instance.missive)
