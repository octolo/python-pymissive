"""Default PDF generator for django-pymissive.

Compiles the missive body template and converts it to PDF using weasyprint.
Override by setting PYMISSIVE_PDF_GENERATOR in your Django settings.
"""

from __future__ import annotations

from typing import Any

from django.template import Context, Template

HTML_WRAPPER = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: A4;
    margin: 20mm;
}}
body {{
    font-family: serif;
    font-size: 12pt;
    line-height: 1.5;
    color: #000;
}}
</style>
{extra_css}
</head>
<body>
{body}
</body>
</html>"""


def _compile_body(missive) -> str:
    """Compile the missive body through the Django template engine."""
    context = missive.missive_context()
    tpl = missive.get_locally_or_campaign_value("body_postal", missive.body_html)
    if not tpl:
        tpl = missive.get_locally_or_campaign_value("body_html", "")
    return Template(tpl).render(Context(context))


def body_to_pdf(missive, **kwargs: Any) -> bytes:
    """Compile the body and convert it to a PDF (bytes).

    Requires ``weasyprint`` to be installed::

        pip install django-pymissive[pdf]

    Accepted kwargs:
        extra_css (str): additional ``<style>`` block injected in ``<head>``.
    """
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "weasyprint is required for PDF generation. "
            "Install it with: pip install django-pymissive[pdf]"
        ) from exc

    compiled_body = _compile_body(missive)
    extra_css = kwargs.get("extra_css", "")
    if extra_css:
        extra_css = f"<style>{extra_css}</style>"

    html_string = HTML_WRAPPER.format(body=compiled_body, extra_css=extra_css)
    return HTML(string=html_string).write_pdf()
