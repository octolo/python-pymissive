"""Abstract mixins: timestamps, JSON config bags, processor chains."""

from __future__ import annotations

from typing import Callable, Iterable

from django.db import models
from django.utils.translation import gettext_lazy as _

from ..fields import JSONField


# ---------------------------------------------------------------------------
# Comment + timestamps mixin: ubiquitous audit fields.
# ---------------------------------------------------------------------------

class CommentTimestampedModel(models.Model):
    """``comment``, ``created_at``, ``updated_at``."""

    comment = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Comment"),
        help_text=_("Internal comment or note"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        editable=False,
        verbose_name=_("Created At"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        editable=False,
        verbose_name=_("Updated At"),
    )

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Config mixin: JSON bags shared across pymissive models.
# ---------------------------------------------------------------------------

class ConfigMixin(models.Model):
    """``additional_context`` (templates), ``additional_config`` (runtime), ``metadata``."""

    additional_context = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional context"),
        help_text=_("Additional context as JSON"),
    )
    additional_config = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional configuration"),
        help_text=_("Additional configuration as JSON"),
    )
    metadata = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata"),
        help_text=_("Additional metadata as JSON"),
    )

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Processors mixin: per-instance processor chains + resolution helpers.
# ---------------------------------------------------------------------------

_PROCESSOR_HELP = _(
    "Ordered list of processors. When non-empty, REPLACES inherited defaults. "
    "Runtime resolution (first non-empty wins): this object's value, then its "
    "campaign's value (when this is a missive linked to a campaign), then the "
    "global setting. Each entry may be a dotted-path string, a "
    "``[path, kwargs]`` pair, or a ``{\"processor\": path, \"kwargs\": {...}}`` "
    "dict. When overriding the body chain, include "
    "``django_pymissive.processors.body.django_template.django_template_processor`` "
    "if you still want ``{{ var }}`` / ``{% tag %}`` rendering; when overriding "
    "the first_document chain, include "
    "``django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer`` "
    "(or your own renderer) as the first entry."
)


class ProcessorsMixin(models.Model):
    """Body / first_document / attachment processor chains (self → parent → defaults)."""

    body_processors = JSONField(
        default=list,
        blank=True,
        verbose_name=_("Body processors"),
        help_text=_PROCESSOR_HELP,
    )
    first_document_processors = JSONField(
        default=list,
        blank=True,
        verbose_name=_("First document PDF processors"),
        help_text=_PROCESSOR_HELP,
    )
    attachment_processors = JSONField(
        default=list,
        blank=True,
        verbose_name=_("Attachment processors"),
        help_text=_PROCESSOR_HELP,
    )

    class Meta:
        abstract = True

    # -- defaults (read from settings) --------------------------------------

    def get_default_body_processors(self) -> list:
        from ..processors.body import get_default_body_processors

        return get_default_body_processors()

    def get_default_pdf_processors(self) -> list:
        from ..processors.pdf import get_default_pdf_processors

        return get_default_pdf_processors()

    def get_default_attachment_processors(self) -> list:
        from ..processors.attachment import get_default_attachment_processors

        return get_default_attachment_processors()

    def _parent_processors(self, field_name: str) -> Iterable | None:
        """Parent chain for resolution; ``Missive`` overrides to use ``campaign``."""
        return None

    def _resolve_processors(
        self, field_name: str, default_factory: Callable[[], list]
    ) -> list:
        local = getattr(self, field_name, None)
        if local:
            return list(local)
        parent = self._parent_processors(field_name)
        if parent:
            return list(parent)
        return default_factory()

    def get_body_processors(self) -> list:
        return self._resolve_processors(
            "body_processors", self.get_default_body_processors
        )

    def get_first_document_processors(self) -> list:
        return self._resolve_processors(
            "first_document_processors", self.get_default_pdf_processors
        )

    def get_attachment_processors(self) -> list:
        return self._resolve_processors(
            "attachment_processors", self.get_default_attachment_processors
        )
