"""Collapsed read-only Annotations section for models annotated by ``with_counts``."""

from datetime import date, datetime
from functools import lru_cache
from typing import Any

from django.contrib import admin
from django.utils import formats, timezone
from django.utils.translation import gettext_lazy as _

_CACHE_ATTR = "_admin_annotation_values"
_READERS: dict[str, Any] = {}


def _flatten_fieldset_fields(fieldsets) -> set[str]:
    names: set[str] = set()
    for _title, options in fieldsets:
        for field in options.get("fields", ()):
            if isinstance(field, (list, tuple)):
                names.update(field)
            else:
                names.add(field)
    return names


def _format_annotation(value):
    if value is None:
        return "-"
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return formats.localize(value)
    if isinstance(value, date):
        return formats.localize(value)
    return value


def _annotation_reader(name: str):
    def reader(self, obj):
        value = self._annotation_value(obj, name)
        if name.startswith("is_"):
            return bool(value)
        return _format_annotation(value)

    displayed: Any = reader
    displayed.short_description = name
    displayed.boolean = name.startswith("is_")
    displayed.__name__ = name
    return displayed


def _reader(name: str):
    reader = _READERS.get(name)
    if reader is None:
        reader = _annotation_reader(name)
        _READERS[name] = reader
    return reader


@lru_cache(maxsize=1)
def campaign_annotation_names() -> tuple[str, ...]:
    from ..managers.campaign import count_annotations

    return tuple(count_annotations())


@lru_cache(maxsize=1)
def campaign_step_annotation_names() -> tuple[str, ...]:
    from ..managers.campaign_step import count_annotations

    return tuple(count_annotations())


@lru_cache(maxsize=1)
def missive_annotation_names() -> tuple[str, ...]:
    from ..managers.missive import count_annotation_names

    return tuple(sorted(count_annotation_names()))


@lru_cache(maxsize=1)
def scheduled_campaign_annotation_names() -> tuple[str, ...]:
    """Run counters, plus ``send_speed`` which ``with_counts`` adds beside them."""
    from ..managers.scheduler import count_annotations

    names = list(count_annotations())
    if "send_speed" not in names:
        names.append("send_speed")
    return tuple(names)


class AnnotationFieldsetMixin(admin.ModelAdmin):
    """Show every ``with_counts`` annotation on the change view, collapsed.

    Django resolves a readonly field on the model or on this admin class.
    An annotation only exists on the instance, so each name is exposed as an
    admin method. The changelist stays on the counters it already selects.
    """

    def annotation_names(self) -> tuple[str, ...]:
        return ()

    def _annotation_names_for(self, fieldsets, obj) -> list[str]:
        if obj is None or not obj.pk:
            return []
        shown = _flatten_fieldset_fields(fieldsets)
        concrete = {field.name for field in self.model._meta.concrete_fields}
        return [name for name in self.annotation_names() if name not in shown and name not in concrete]

    def _install_annotation_readers(self, names) -> None:
        cls = type(self)
        for name in names:
            if any(name in klass.__dict__ for klass in cls.__mro__):
                continue
            setattr(cls, name, _reader(name))

    def _annotation_value(self, obj, name):
        if name in obj.__dict__:
            return obj.__dict__[name]
        cache = obj.__dict__.get(_CACHE_ATTR)
        if cache is None:
            cache = {}
            if obj.pk:
                row = type(obj)._default_manager.with_counts().filter(pk=obj.pk).first()
                if row is not None:
                    cache = {key: row.__dict__[key] for key in self.annotation_names() if key in row.__dict__}
            obj.__dict__[_CACHE_ATTR] = cache
        return cache.get(name)

    def _base_fieldsets(self, request, obj):
        return super().get_fieldsets(request, obj)

    def _with_annotation_fieldset(self, fieldsets, obj):
        names = self._annotation_names_for(fieldsets, obj)
        if not names:
            return fieldsets
        self._install_annotation_readers(names)
        return [
            *fieldsets,
            (_("Annotations"), {"fields": names, "classes": ("collapse",)}),
        ]

    def get_fieldsets(self, request, obj=None):
        return self._with_annotation_fieldset(self._base_fieldsets(request, obj), obj)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is None or not obj.pk:
            return readonly
        names = self._annotation_names_for(self._base_fieldsets(request, obj), obj)
        self._install_annotation_readers(names)
        for name in names:
            if name not in readonly:
                readonly.append(name)
        return readonly
