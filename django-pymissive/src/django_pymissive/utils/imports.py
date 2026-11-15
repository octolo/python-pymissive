"""Restricted dotted-import helpers."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _


_PACKAGE_PREFIXES = ("django_pymissive.", "pymissive.")


def is_import_allowed(path: str) -> bool:
    """Whether a dotted path may be imported and called.

    ``settings.PYMISSIVE_ALLOWED_TASK_BACKENDS`` lists the allowed prefixes;
    unset (``None``) allows every path. The package's own modules are always
    allowed.
    """
    if path.startswith(_PACKAGE_PREFIXES):
        return True
    allowed = getattr(settings, "PYMISSIVE_ALLOWED_TASK_BACKENDS", None)
    if allowed is None:
        return True
    return any(path == entry or path.startswith(f"{entry}.") for entry in allowed)


def import_allowed_string(path: str):
    """``import_string`` restricted to :func:`is_import_allowed` paths."""
    if not is_import_allowed(path):
        raise ImportError(f"{path} is not allowed by settings.PYMISSIVE_ALLOWED_TASK_BACKENDS.")
    return import_string(path)


def processor_path(entry):
    """Dotted path of a processor entry, or ``None`` when it has none."""
    if isinstance(entry, dict):
        entry = entry.get("processor") or entry.get("path")
    elif isinstance(entry, (list, tuple)) and len(entry) == 2:
        entry = entry[0]
    return entry if isinstance(entry, str) else None


def validate_import_paths(instance, *field_names) -> None:
    """Raise ``ValidationError`` for paths in *field_names* that are not allowed.

    Each field holds a dotted path or a list of processor entries.
    """
    errors = {}
    for name in field_names:
        value = getattr(instance, name, None) or []
        entries = value if isinstance(value, list) else [value]
        refused = [path for path in map(processor_path, entries) if path and not is_import_allowed(path)]
        if refused:
            errors[name] = _("%(paths)s not allowed by settings.PYMISSIVE_ALLOWED_TASK_BACKENDS.") % {
                "paths": ", ".join(refused)
            }
    if errors:
        raise ValidationError(errors)


def _resolve_hook(hook):
    """Resolve a single hook (dotted path string or callable) to a callable."""
    return hook if callable(hook) else import_allowed_string(hook)
