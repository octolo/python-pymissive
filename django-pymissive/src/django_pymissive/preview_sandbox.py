"""Isolate compiled HTML in preview so it cannot run on the application origin.

Preview templates used to inject ``body_rich_compiled`` with ``|safe``. That is
required to *show* HTML mail, but it also runs author ``<script>`` in the same
origin as admin cookies. The compiled document goes into an iframe ``srcdoc``
with an empty ``sandbox`` (no scripts, no same-origin). The parent must
attribute-escape the srcdoc string — Django's ``{{ srcdoc }}`` does.
"""

from __future__ import annotations

_SRCDOC_PREFIX = (
    "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
    "<meta http-equiv=\"Content-Security-Policy\" "
    "content=\"default-src 'none'; img-src data: https: http:; "
    "style-src 'unsafe-inline'; font-src data: https: http:;\">"
    "<style>html,body{margin:0;background:#fff;}</style>"
    "</head><body>"
)
_SRCDOC_SUFFIX = "</body></html>"


def sandboxed_preview_srcdoc(html: str | None) -> str:
    """Full HTML document for an iframe ``srcdoc`` attribute."""
    return f"{_SRCDOC_PREFIX}{html or ''}{_SRCDOC_SUFFIX}"
