"""Signal handlers for django_pymissive."""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import post_save
from django.dispatch import receiver

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


@receiver(post_save, sender=MissiveEvent)
def trigger_billings_on_event(sender, instance, created, **kwargs):
    """Call get_billings on the missive after a new event is saved."""
    if not created or _suppress_event_billings.get():
        return
    if instance.missive_id and instance.missive.can_billings():
        instance.missive.get_billings()
