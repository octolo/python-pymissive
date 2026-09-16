"""Compiled HTML must not execute on the preview page origin."""

from __future__ import annotations

import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.preview_sandbox import sandboxed_preview_srcdoc

pytestmark = pytest.mark.django_db

PAYLOAD = '<p>Hello</p><script>document.cookie="x"</script><img src=x onerror="alert(1)">'


def _email_missive(**kw) -> Missive:
    defaults = dict(
        missive_type=MissiveType.EMAIL,
        subject="Hello",
        body_rich=PAYLOAD,
        body_text="Hello",
        sender_name="Octolo",
        sender_email="hello@example.com",
        status=MissiveStatus.DRAFT,
    )
    defaults.update(kw)
    return Missive.objects.create(**defaults)


def test_srcdoc_wraps_the_compiled_html():
    doc = sandboxed_preview_srcdoc(PAYLOAD)
    assert PAYLOAD in doc
    assert "Content-Security-Policy" in doc
    assert doc.startswith("<!DOCTYPE html>")


def test_email_preview_puts_compiled_html_in_a_sandboxed_iframe():
    missive = _email_missive()
    response = Client().get(
        reverse("django_pymissive:preview", args=["missive", missive.pk]),
    )
    assert response.status_code == 200
    html = response.content.decode()

    assert 'class="sandboxed-html-preview"' in html
    assert "sandbox" in html
    assert 'referrerpolicy="no-referrer"' in html
    # Attribute-escaped: the parent document must not contain a live script tag.
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Hello" in html


def test_quotes_in_the_body_cannot_break_out_of_srcdoc():
    missive = _email_missive(body_rich='<p class="break">ok</p>')
    html = Client().get(
        reverse("django_pymissive:preview", args=["missive", missive.pk]),
    ).content.decode()

    assert 'class="break"' not in html
    assert "class=&quot;break&quot;" in html


def test_postal_pdf_letter_keeps_inline_html():
    """WeasyPrint needs the compiled body in the page, not in an iframe."""
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        status=MissiveStatus.DRAFT,
        body_rich="<p>letter body</p>",
    )
    page = render_to_string(
        "django_pymissive/includes/postal_a4_letter_page.html",
        missive.get_postal_letter_render_context(),
    )
    assert "<iframe" not in page
    assert "<p>letter body</p>" in page


def test_postal_browser_letter_sandboxes_the_compiled_body():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        status=MissiveStatus.DRAFT,
        body_rich=PAYLOAD,
    )
    ctx = missive.get_postal_letter_render_context()
    ctx["sandbox_compiled_body"] = True
    page = render_to_string(
        "django_pymissive/includes/postal_a4_letter_page.html",
        ctx,
    )
    assert "<iframe" in page
    assert 'sandbox' in page
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
