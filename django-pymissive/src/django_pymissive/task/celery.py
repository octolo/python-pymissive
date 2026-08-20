from datetime import date, datetime

from celery import shared_task
from django.utils.module_loading import import_string

from .base import BaseCampaignBackend
from .campaign import run_campaign


def _json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


@shared_task
def celery_campaign_task(campaign_id):
    run_campaign(campaign_id)


@shared_task
def celery_enqueue_task(func_path, args, kwargs):
    import_string(func_path)(*args, **kwargs)


class CeleryBackend(BaseCampaignBackend):
    def delay(self, campaign_id: int):
        celery_campaign_task.delay(campaign_id)

    def enqueue(self, func, *args, **kwargs):
        celery_enqueue_task.delay(
            f"{func.__module__}.{func.__name__}",
            [_json_safe(arg) for arg in args],
            {key: _json_safe(value) for key, value in kwargs.items()},
        )
