"""Virtual queryset of the settings this package reads. No database table."""

import json
import os

from django.conf import settings
from virtualqueryset.managers import VirtualManager


def _known_settings() -> dict[str, object]:
    """Every setting this package reads, with the value used when it is unset."""
    from pymissive.config import DELIVERY_MODES, MISSIVE_ACKNOWLEDGEMENT_LEVELS, PRIORITIES

    from ..processors.attachment._base import DEFAULT_ATTACHMENT_PROCESSORS
    from ..processors.body._base import DEFAULT_BODY_PROCESSORS
    from ..processors.build_target import DEFAULT_BUILD_TARGET_FIELDS, DEFAULT_BUILD_TARGET_PROCESSORS
    from ..processors.pdf._base import DEFAULT_PDF_PROCESSORS
    from ..processors.pdf.watermark import DEFAULT_WATERMARK_LINES
    from ..utils import (
        PROGRESS_STEP_DEFAULT,
        SEND_CHUNK_SIZE_DEFAULT,
        STALE_PROCESSING_SECONDS_DEFAULT,
    )

    known: dict[str, object] = {
        "PYMISSIVE_CAMPAIGN_TASK_BACKEND": "sync",
        "PYMISSIVE_DOMAIN": None,
        "PYMISSIVE_PDF_GENERATOR": "django_pymissive.pdf.body_to_pdf",
        "PYMISSIVE_SCHEME": None,
        "PYMISSIVE_ALLOW_FAKE_PROVIDER": False,
        "PYMISSIVE_ALLOWED_ATTACHMENT_EXTENSIONS": None,
        "PYMISSIVE_ALLOWED_TASK_BACKENDS": None,
        "PYMISSIVE_ATTACHMENT_FILE_STORAGE": None,
        "PYMISSIVE_ATTACHMENT_PATH_MAX_LENGTH": None,
        "PYMISSIVE_ATTACHMENT_UPLOAD_TO": None,
        "PYMISSIVE_BUILD_TARGET_FIELDS": DEFAULT_BUILD_TARGET_FIELDS,
        "PYMISSIVE_BUILD_TARGET_FULL": False,
        "PYMISSIVE_CAMPAIGN_NAMED_ID_GENERATOR": None,
        "PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS": DEFAULT_ATTACHMENT_PROCESSORS,
        "PYMISSIVE_DEFAULT_BODY_PROCESSORS": DEFAULT_BODY_PROCESSORS,
        "PYMISSIVE_DEFAULT_BUILD_TARGET_PROCESSORS": DEFAULT_BUILD_TARGET_PROCESSORS,
        "PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS": DEFAULT_PDF_PROCESSORS,
        "PYMISSIVE_DEFAULT_PROVIDER": None,
        "PYMISSIVE_DEFAULT_SENDER": None,
        "PYMISSIVE_DISABLE_SEND": False,
        "PYMISSIVE_DRY_RUN": False,
        "PYMISSIVE_FORCE_FAKE_PROVIDER": False,
        "PYMISSIVE_JSON_WIDGET": None,
        "PYMISSIVE_OVERRIDE_RECIPIENT": None,
        "PYMISSIVE_PROGRESS_HOOK": None,
        "PYMISSIVE_RECIPIENT_ALLOWED": None,
        "PYMISSIVE_PROGRESS_STEP": PROGRESS_STEP_DEFAULT,
        "PYMISSIVE_RICHTEXT_WIDGET": "django.forms.Textarea",
        "PYMISSIVE_SAVE_UNTREATED_EVENTS": False,
        "PYMISSIVE_SEND_CHUNK_SIZE": SEND_CHUNK_SIZE_DEFAULT,
        "PYMISSIVE_STALE_PROCESSING_SECONDS": STALE_PROCESSING_SECONDS_DEFAULT,
        "PYMISSIVE_WATERMARK": DEFAULT_WATERMARK_LINES,
    }
    for name in (
        *DELIVERY_MODES,
        *PRIORITIES,
        *(level["name"] for level in MISSIVE_ACKNOWLEDGEMENT_LEVELS),
    ):
        known.setdefault(f"PYMISSIVE_{str(name).upper()}", True)
    return known


_ENV_FLAGS = ("PYMISSIVE_DISABLE_SEND", "PYMISSIVE_ALLOW_FAKE_PROVIDER", "PYMISSIVE_FORCE_FAKE_PROVIDER")


def _env_flag(name: str):
    """Effective boolean for a flag read from the environment, then settings."""
    from pymissive.utils import is_disable_send, is_fake_provider_allowed, is_force_fake_provider

    if name == "PYMISSIVE_DISABLE_SEND":
        return is_disable_send()
    if name == "PYMISSIVE_FORCE_FAKE_PROVIDER":
        return is_force_fake_provider()
    return is_fake_provider_allowed()


def _setting_value(name: str, default: object) -> tuple[object, bool]:
    if name in _ENV_FLAGS and os.environ.get(name) is not None:
        return _env_flag(name), True
    if hasattr(settings, name):
        if name in _ENV_FLAGS:
            return _env_flag(name), True
        return getattr(settings, name), True
    return default, False


def _jsonable(value: object) -> object:
    if callable(value):
        return _callable_path(value)
    if isinstance(value, set):
        return [_jsonable(item) for item in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _callable_path(value: object) -> str:
    module = getattr(value, "__module__", "") or ""
    qualname = getattr(value, "__qualname__", None) or getattr(value, "__name__", "")
    return f"{module}.{qualname}" if module and qualname else repr(value)


def _format_setting(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if callable(value):
        return _callable_path(value)
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(_jsonable(value), ensure_ascii=False, separators=(", ", ": "))
    return " ".join(str(value).split())


class MissiveSettingManager(VirtualManager):
    """One row per setting, built in memory."""

    def get_data(self) -> list[dict[str, str]]:
        known = _known_settings()
        rows = []
        for name in sorted(known):
            value, explicit = _setting_value(name, known.get(name))
            rows.append(
                {
                    "name": name,
                    "default_value": _format_setting(known.get(name)),
                    "configured_value": _format_setting(value) if explicit else "",
                }
            )
        return rows
