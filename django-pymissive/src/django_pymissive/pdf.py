"""Default PDF generator for django-pymissive.

Compiles the missive body template and converts it to PDF using weasyprint.
Postal / LRE first-page layout CSS lives in ``static/django_pymissive/css/letter_page.css``;
WeasyPrint loads that file via staticfiles and appends PDF-specific ``@page`` / sheet resets.

Override by setting MISSIVEPDF_GENERATOR in your Django settings.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.contrib.staticfiles import finders
from django.template import Context, Template
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

HTML_WRAPPER = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{head_css}
</style>
</head>
<body>
{body}
</body>
</html>"""

# Missive types that use the postal/LRE letter layout (header + body) in preview and PDF.
_POSTAL_LETTER_TYPES = frozenset({
    "postal",
    "postal_registered",
    "postal_signature",
    "lre",
    "lre_qualified",
})

_DEFAULT_PDF_CSS = """
@page {{
    size: A4;
    margin: 10mm;
}}
body {{
    font-family: serif;
    font-size: 12pt;
    line-height: 1.5;
    color: #000;
}}
"""

_POSTAL_PDF_FOUNDATION = """
@page {{
    size: A4;
    margin: 10mm 10mm 10mm 10mm;
}}
body {{
    font-family: serif;
    font-size: 12pt;
    line-height: 1.5;
    color: #000;
}}
"""

# After letter_page.css: drop on-screen "sheet" chrome so @page margins define the box.
_POSTAL_PDF_SHEET_RESET = """
.a4-page {{
    width: 100%;
    margin: 0;
    padding: 0;
    border: none;
    box-shadow: none;
    min-height: auto;
    background: #fff;
}}
"""

_LETTER_PAGE_CSS_REL = "django_pymissive/css/letter_page.css"


def _letter_page_css_text() -> str:
    path = finders.find(_LETTER_PAGE_CSS_REL)
    if not path:
        logger.warning(
            "Static file %s not found; postal PDF letter layout may be incomplete",
            _LETTER_PAGE_CSS_REL,
        )
        return ""
    return Path(path).read_text(encoding="utf-8")


def _postal_pdf_head_css() -> str:
    return "".join(
        (
            _POSTAL_PDF_FOUNDATION,
            _letter_page_css_text(),
            _POSTAL_PDF_SHEET_RESET,
        )
    )


def _compile_body(missive) -> str:
    """Compile first_document (campaign) or body_html when no campaign."""
    context = missive.missive_context()
    tpl = missive.get_locally_or_campaign_value("body_html") or ""
    return Template(str(tpl)).render(Context(context))


def _postal_letter_html(missive, postal_recipient_pk=None) -> str:
    """HTML for the first postal page (recipient + body), same template as browser preview."""
    ctx = missive.get_postal_letter_render_context(postal_recipient_pk=postal_recipient_pk)
    return render_to_string("django_pymissive/includes/postal_a4_letter_page.html", ctx)


def body_to_pdf(missive, **kwargs: Any) -> bytes:
    """Compile the body and convert it to a PDF (bytes).

    Requires ``weasyprint`` to be installed::

        pip install django-pymissive[pdf]

    Accepted kwargs:
        extra_css (str): additional CSS rules appended inside the document ``<style>`` block.
        postal_recipient_pk (int | None): primary key of the ``MissiveRecipient`` row for the address block;
            ``None`` uses the first recipient when available.
    """
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "weasyprint is required for PDF generation. "
            "Install it with: pip install django-pymissive[pdf]"
        ) from exc

    pr_pk = kwargs.get("postal_recipient_pk")
    if pr_pk is not None:
        try:
            pr_pk = int(pr_pk)
        except (TypeError, ValueError):
            pr_pk = None

    mt = (getattr(missive, "missive_type", None) or "").lower()
    if mt in _POSTAL_LETTER_TYPES:
        compiled_body = _postal_letter_html(missive, postal_recipient_pk=pr_pk)
        head_css = _postal_pdf_head_css()
    else:
        compiled_body = _compile_body(missive)
        head_css = _DEFAULT_PDF_CSS

    extra = kwargs.get("extra_css", "")
    if extra:
        head_css = f"{head_css}\n{extra}\n"

    html_string = HTML_WRAPPER.format(body=compiled_body, head_css=head_css)
    return HTML(string=html_string).write_pdf()
