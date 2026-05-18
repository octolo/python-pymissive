"""Pytest configuration shared by all django-pymissive tests.

We don't ship Django migrations for the lib's own apps (the project
that integrates django-pymissive owns its migrations). Tests run
against an in-memory SQLite DB and use ``--create-db`` semantics, so
we let pytest-django build the schema directly from the models via
``django.test.utils.setup_test_environment`` + ``create_all`` (the
default behaviour when ``MIGRATION_MODULES`` makes migrations a no-op
for the apps under test).
"""

from __future__ import annotations

import pytest
from django.conf import settings


@pytest.fixture(autouse=True)
def _disable_dry_run(settings):
    """Make sure tests never enter the dry-run branch implicitly."""
    settings.PYMISSIVE_DRY_RUN = False


@pytest.fixture(autouse=True)
def _disable_debug_toolbar(settings):
    """Strip the debug toolbar from MIDDLEWARE during tests.

    ``tests/settings.py`` runs with ``DEBUG=True`` which auto-enables
    debug_toolbar. The toolbar's response middleware tries to render a
    template that reverses ``djdt:...`` URLs — which aren't registered
    when ``DEBUG=False`` (forced by ``client.get(...)``-style tests
    using ``override_settings`` in the wider ecosystem). Stripping the
    middleware here lets the Django test client run the view-under-test
    without the toolbar interfering.
    """
    settings.DEBUG = False
    middleware = [
        m for m in settings.MIDDLEWARE if "debug_toolbar" not in m.lower()
    ]
    if middleware != list(settings.MIDDLEWARE):
        settings.MIDDLEWARE = middleware


@pytest.fixture
def small_pdf_bytes() -> bytes:
    """Tiny single-page PDF generated via reportlab.

    Useful as an input to the watermark / attachment processor pipeline
    when we want a real PDF without depending on a fixture file (the
    ``tests/pdf_sample_1mb.pdf`` lives next to the fakeapp model and
    isn't always available depending on how the package is installed).
    """
    pytest.importorskip("reportlab")
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(100, 750, "Hello world")
    c.showPage()
    c.save()
    return buf.getvalue()


def pytest_configure(config):
    """Register custom markers used by the suite."""
    config.addinivalue_line(
        "markers",
        "needs_pdf: tests that need pypdf+reportlab+weasyprint at runtime",
    )
