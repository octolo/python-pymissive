"""Body processors pipeline for Missive and MissiveCampaign.

Body processors are post-template hooks that transform the compiled content of
a missive (or campaign) just before sending or previewing. They allow business
apps to plug custom transformations (signatures, legal footers, invoice merge,
unsubscribe links, AB testing, IA rewrite, etc.) without touching the core
``django_pymissive`` model code.

A processor is either:

- a callable ``processor(content, *, missive=None, campaign=None,
  field_name=None, context=None, **kwargs) -> str``;
- a class with a ``process(self, content, *, missive=None, campaign=None,
  field_name=None, context=None, **kwargs) -> str`` method (subclass
  :class:`MissiveBodyProcessor`);
- a class instance exposing the same ``process`` method.

Processors are referenced as Python import paths (strings) stored in the
``body_processors`` JSON field on :class:`~django_pymissive.models.Missive` and
:class:`~django_pymissive.models.MissiveCampaign`. The same field also accepts
already-imported callables/classes when invoked programmatically. Each entry
may be:

- a string import path: ``"myapp.processors.add_signature"``;
- a list/tuple ``[import_path, kwargs_dict]`` to pass extra kwargs;
- a dict ``{"processor": import_path, "kwargs": {...}}``.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.conf import settings
from django.template import Context, Template
from django.utils.module_loading import import_string


def django_template_processor(
    content: str,
    *,
    missive=None,
    campaign=None,
    field_name: str | None = None,
    context: dict | None = None,
    **kwargs: Any,
) -> str:
    """Render ``content`` as a Django template using ``context``.

    Built-in default processor: applied first in the chain so subsequent
    processors operate on the already-rendered output. Disable globally by
    setting ``PYMISSIVE_DEFAULT_BODY_PROCESSORS = []``, or per model by
    overriding ``get_default_body_processors()``.
    """
    if not content:
        return content
    return Template(str(content)).render(Context(context or {}))


DEFAULT_BODY_PROCESSORS: list[str] = [
    "django_pymissive.body_processors.django_template_processor",
]


def get_default_body_processors() -> list:
    """Return default body processors, honoring ``PYMISSIVE_DEFAULT_BODY_PROCESSORS``."""
    override = getattr(settings, "PYMISSIVE_DEFAULT_BODY_PROCESSORS", None)
    if override is not None:
        return list(override)
    return list(DEFAULT_BODY_PROCESSORS)


class MissiveBodyProcessor:
    """Base class for class-based body processors.

    Subclass and override :meth:`process`. The default implementation is a
    no-op so subclasses can override only the hooks they care about.
    """

    def process(
        self,
        content: str,
        *,
        missive=None,
        campaign=None,
        field_name: str | None = None,
        context: dict | None = None,
        **kwargs: Any,
    ) -> str:
        return content


def _resolve_processor(processor: Any) -> tuple[Any, dict]:
    """Resolve a processor entry to ``(callable, kwargs)``.

    Accepts an import path string, a (path, kwargs) sequence, a
    ``{"processor": ..., "kwargs": ...}`` dict, a callable, or a class.
    Class references are instantiated with no args. Returns a tuple of
    the resolved callable (function or instance with ``process``) and
    extra kwargs to forward.
    """
    extra_kwargs: dict = {}

    if isinstance(processor, dict):
        path = processor.get("processor") or processor.get("path")
        extra_kwargs = dict(processor.get("kwargs") or {})
        processor = path
    elif isinstance(processor, (list, tuple)) and len(processor) == 2:
        processor, extra_kwargs = processor[0], dict(processor[1] or {})

    if isinstance(processor, str):
        processor = import_string(processor)

    if isinstance(processor, type):
        processor = processor()

    return processor, extra_kwargs


def _call_processor(
    processor: Any,
    content: str,
    *,
    missive=None,
    campaign=None,
    field_name: str | None = None,
    context: dict | None = None,
    **kwargs: Any,
) -> str:
    """Invoke a resolved processor (instance with ``process`` or plain callable)."""
    if hasattr(processor, "process") and callable(processor.process):
        return processor.process(
            content,
            missive=missive,
            campaign=campaign,
            field_name=field_name,
            context=context,
            **kwargs,
        )
    if callable(processor):
        return processor(
            content,
            missive=missive,
            campaign=campaign,
            field_name=field_name,
            context=context,
            **kwargs,
        )
    raise TypeError(f"Processor {processor!r} is not callable and has no .process() method")


def apply_body_processors(
    content: str,
    processors: Iterable[Any] | None,
    *,
    missive=None,
    campaign=None,
    field_name: str | None = None,
    context: dict | None = None,
) -> str:
    """Apply ``processors`` (in order) to ``content`` and return the result.

    Each processor receives the current content as the first positional arg
    and the same kwargs (``missive``, ``campaign``, ``field_name``,
    ``context``) so it can introspect the missive/campaign at will.
    """
    if not processors:
        return content
    for entry in processors:
        if entry is None:
            continue
        processor, extra_kwargs = _resolve_processor(entry)
        content = _call_processor(
            processor,
            content,
            missive=missive,
            campaign=campaign,
            field_name=field_name,
            context=context,
            **extra_kwargs,
        )
    return content
