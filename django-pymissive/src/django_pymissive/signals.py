"""Signal handlers for django_pymissive."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import cast

from django.core.exceptions import ValidationError
from django.db.models import Count
from django.db.models.signals import m2m_changed, post_save, pre_delete
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from .models.attachment import MissiveBaseAttachment
from .models.campaign_step import CampaignStep
from .models.choices import MissiveEventType
from .models.event import MissiveEvent
from .models.scheduler import MissiveScheduledCampaign

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
    from .services.billings import fetch_missive_billings
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


def delete_attachments_exclusive_to_step(sender, instance, **kwargs):
    """A file limited to the steps being deleted must not become shared.

    An attachment with no step link is sent with every step. Drop this
    step's links first, then delete the files that no longer have one.
    A file that was already unlinked stays shared. When several steps go
    in one call, each pass sees the links the previous pass removed.
    """
    linked_ids = list(instance.attachments.values_list("pk", flat=True))
    if not linked_ids:
        return
    instance.attachments.clear()
    (
        MissiveBaseAttachment.objects.filter(pk__in=linked_ids)
        .annotate(step_count=Count("campaign_step"))
        .filter(step_count=0)
        .delete()
    )


for _step_model_object in (CampaignStep, *CampaignStep.__subclasses__()):
    _step_model = cast(type[CampaignStep], _step_model_object)
    pre_delete.connect(
        delete_attachments_exclusive_to_step,
        sender=_step_model,
        dispatch_uid=f"delete_attachments_exclusive_to_step.{_step_model._meta.label_lower}",
    )


@receiver(m2m_changed, sender=MissiveScheduledCampaign.campaign_steps.through)
def validate_scheduled_campaign_steps(sender, instance, action, reverse, model, pk_set, **kwargs):
    """Reject scheduler-step links that cross campaign boundaries."""
    if action != "pre_add" or not pk_set:
        return
    if reverse:
        invalid = model.objects.filter(pk__in=pk_set).exclude(campaign_id=instance.campaign_id).exists()
    else:
        invalid = CampaignStep.objects.filter(pk__in=pk_set).exclude(campaign_id=instance.campaign_id).exists()
    if invalid:
        raise ValidationError(_("Every selected step must belong to the scheduled campaign."))
