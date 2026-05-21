"""Body processors sub-package.

Re-exports everything so ``django_pymissive.processors.body`` is a
one-stop import for all body-processor symbols.
"""

from ._base import (
    DEFAULT_BODY_PROCESSORS,
    EMAIL_BODY_HTML_FIELDS,
    EMAIL_BODY_TEXT_FIELDS,
    EMAIL_MISSIVE_TYPES,
    MissiveBodyProcessor,
    _append_email_snippet,
    _call_processor,
    _email_body_owner,
    _is_email_body_field,
    _is_email_missive,
    _resolve_processor,
    apply_body_processors,
    get_default_body_processors,
)
from .add_attachments_linked import AttachmentsLinkedProcessor, add_attachments_linked
from .add_preview_browser import PreviewBrowserProcessor, add_preview_browser
from .django_template import django_template_processor

__all__ = [
    "DEFAULT_BODY_PROCESSORS",
    "EMAIL_BODY_HTML_FIELDS",
    "EMAIL_BODY_TEXT_FIELDS",
    "EMAIL_MISSIVE_TYPES",
    "MissiveBodyProcessor",
    "apply_body_processors",
    "get_default_body_processors",
    "django_template_processor",
    "add_preview_browser",
    "PreviewBrowserProcessor",
    "add_attachments_linked",
    "AttachmentsLinkedProcessor",
]
