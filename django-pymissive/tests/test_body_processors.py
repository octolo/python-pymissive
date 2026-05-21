"""Unit tests for ``django_pymissive.processors.body``.

Covers the resolver, the chain runner, the default Django template
processor, and the override semantics for
``PYMISSIVE_DEFAULT_BODY_PROCESSORS``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.test import override_settings

from django_pymissive.processors.body import (
    DEFAULT_BODY_PROCESSORS,
    MissiveBodyProcessor,
    apply_body_processors,
    django_template_processor,
    get_default_body_processors,
)


def _shouty(content, **kwargs):
    """Sample function processor — uppercases input."""
    return (content or "").upper()


def _prefix(content, *, prefix="[X] ", **kwargs):
    """Sample function processor with a config kwarg."""
    return f"{prefix}{content}"


class _SuffixProcessor(MissiveBodyProcessor):
    """Class-based processor — appends a configurable suffix."""

    def process(self, content, *, suffix=" / ok", **kwargs):
        return f"{content}{suffix}"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_chain_uses_django_template_processor():
    assert DEFAULT_BODY_PROCESSORS == [
        "django_pymissive.processors.body.django_template.django_template_processor",
    ]


def test_get_default_body_processors_falls_back_to_default():
    """``None`` setting falls back to the built-in default chain."""
    with override_settings(PYMISSIVE_DEFAULT_BODY_PROCESSORS=None):
        assert get_default_body_processors() == list(DEFAULT_BODY_PROCESSORS)


def test_get_default_body_processors_honors_override():
    with override_settings(PYMISSIVE_DEFAULT_BODY_PROCESSORS=["tests.test_body_processors._shouty"]):
        assert get_default_body_processors() == ["tests.test_body_processors._shouty"]


def test_get_default_body_processors_supports_empty_list():
    """Empty list = explicitly disable defaults (don't fall back)."""
    with override_settings(PYMISSIVE_DEFAULT_BODY_PROCESSORS=[]):
        assert get_default_body_processors() == []


# ---------------------------------------------------------------------------
# apply_body_processors
# ---------------------------------------------------------------------------


def test_apply_body_processors_empty_chain_passes_through():
    assert apply_body_processors("hello", []) == "hello"
    assert apply_body_processors("hello", None) == "hello"


def test_apply_body_processors_function():
    out = apply_body_processors("hello", ["tests.test_body_processors._shouty"])
    assert out == "HELLO"


def test_apply_body_processors_with_kwargs_pair():
    out = apply_body_processors(
        "world",
        [["tests.test_body_processors._prefix", {"prefix": ">>> "}]],
    )
    assert out == ">>> world"


def test_apply_body_processors_with_kwargs_dict():
    out = apply_body_processors(
        "world",
        [{"processor": "tests.test_body_processors._prefix", "kwargs": {"prefix": ">>> "}}],
    )
    assert out == ">>> world"


def test_apply_body_processors_class_based():
    out = apply_body_processors(
        "hello",
        [["tests.test_body_processors._SuffixProcessor", {"suffix": "!"}]],
    )
    assert out == "hello!"


def test_apply_body_processors_chain_runs_in_order():
    out = apply_body_processors(
        "x",
        [
            "tests.test_body_processors._shouty",  # → 'X'
            ["tests.test_body_processors._prefix", {"prefix": ">"}],  # → '>X'
            ["tests.test_body_processors._SuffixProcessor", {"suffix": "<"}],  # → '>X<'
        ],
    )
    assert out == ">X<"


def test_apply_body_processors_skips_none_entries():
    out = apply_body_processors("hi", [None, "tests.test_body_processors._shouty", None])
    assert out == "HI"


# ---------------------------------------------------------------------------
# django_template_processor
# ---------------------------------------------------------------------------


def test_django_template_processor_renders_variables():
    out = django_template_processor(
        "Hello {{ name }}",
        context={"name": "Charles"},
    )
    assert out == "Hello Charles"


def test_django_template_processor_renders_tags():
    out = django_template_processor(
        "{% if show %}YES{% else %}NO{% endif %}",
        context={"show": True},
    )
    assert out == "YES"


def test_django_template_processor_no_context_safe_on_plain_text():
    out = django_template_processor("plain text", context=None)
    assert out == "plain text"


def test_django_template_processor_handles_empty():
    assert django_template_processor("", context={}) == ""
    assert django_template_processor(None, context={}) is None


def test_django_template_processor_does_not_html_escape_plain_text_fields():
    """``body_text`` / ``body_sms`` / ``subject`` must stay plain text — no ``&#x27;``."""
    for fname in ("body_text", "body_sms", "subject", None):
        out = django_template_processor(
            "It's a {{ thing }}",
            context={"thing": "test & sample"},
            field_name=fname,
        )
        assert out == "It's a test & sample", (
            f"field_name={fname!r} unexpectedly HTML-escaped the output: {out!r}"
        )


def test_django_template_processor_html_escapes_html_fields():
    """``body_html`` / ``first_document`` keep autoescape ON to avoid XSS."""
    for fname in ("body_html", "first_document"):
        out = django_template_processor(
            "<p>{{ value }}</p>",
            context={"value": "<script>x</script>"},
            field_name=fname,
        )
        assert out == "<p>&lt;script&gt;x&lt;/script&gt;</p>", out


# ---------------------------------------------------------------------------
# Field-name awareness (processors should receive field_name)
# ---------------------------------------------------------------------------


def test_processor_receives_field_name():
    captured: dict = {}

    def capture(content, *, field_name=None, **kwargs):
        captured["field_name"] = field_name
        return content

    apply_body_processors(
        "x",
        [capture],
        field_name="body_html",
    )
    assert captured["field_name"] == "body_html"


# ---------------------------------------------------------------------------
# Email snippet processors (preview + linked attachments)
# ---------------------------------------------------------------------------


def _email_missive(**extra):
    defaults = {
        "missive_type": "email",
        "show_preview_browser": "<p>PREVIEW_HTML</p>",
        "show_preview_browser_text": "PREVIEW_TEXT\n",
        "show_attachments_linked": "<p>ATTACH_HTML</p>",
        "show_attachments_linked_text": "ATTACH_TEXT\n",
    }
    defaults.update(extra)
    return SimpleNamespace(**defaults)


def test_add_preview_browser_appends_html_and_text():
    from django_pymissive.processors.body import add_preview_browser

    missive = _email_missive()
    html = add_preview_browser("<p>body</p>", missive=missive, field_name="body_html")
    assert html.endswith("<p>PREVIEW_HTML</p>")
    text = add_preview_browser("Hello", missive=missive, field_name="body_text")
    assert text.endswith("PREVIEW_TEXT")


def test_add_attachments_linked_appends_html_and_text():
    from django_pymissive.processors.body import add_attachments_linked

    missive = _email_missive()
    html = add_attachments_linked("<p>body</p>", missive=missive, field_name="body_html")
    assert html.endswith("<p>ATTACH_HTML</p>")
    text = add_attachments_linked("Hello", missive=missive, field_name="body_text")
    assert text.endswith("ATTACH_TEXT")


def test_email_snippet_processors_skip_postal_and_subject():
    from django_pymissive.processors.body import add_attachments_linked, add_preview_browser

    missive = _email_missive(missive_type="lre")
    assert add_preview_browser("<p>x</p>", missive=missive, field_name="body_html") == "<p>x</p>"
    assert add_preview_browser("subj", missive=missive, field_name="subject") == "subj"
    assert add_attachments_linked("<p>x</p>", missive=missive, field_name="body_html") == "<p>x</p>"


def test_html_snippet_is_separated_from_body_by_a_br():
    """HTML snippets must not render flush with the last paragraph.

    Regression: without a separator, ``show_preview_browser`` (an ``<a>``)
    and ``show_attachments_linked`` (a ``<div>`` with no default margin in
    most email clients) ended up visually glued to the body. We now insert
    a single ``<br>`` between the body and every HTML snippet.
    """
    from django_pymissive.processors.body import add_attachments_linked, add_preview_browser

    missive = _email_missive()

    out = add_preview_browser("<p>body</p>", missive=missive, field_name="body_html")
    assert out == "<p>body</p><br><p>PREVIEW_HTML</p>"

    out = add_attachments_linked("<p>body</p>", missive=missive, field_name="body_html")
    assert out == "<p>body</p><br><p>ATTACH_HTML</p>"

    # Chained: both snippets appended sequentially, each preceded by its own <br>.
    chained = add_attachments_linked(
        add_preview_browser("<p>body</p>", missive=missive, field_name="body_html"),
        missive=missive,
        field_name="body_html",
    )
    assert chained == (
        "<p>body</p><br><p>PREVIEW_HTML</p><br><p>ATTACH_HTML</p>"
    )


def test_text_snippet_keeps_blank_line_separator():
    """Text snippets still get the ``\\n\\n`` separator (unchanged behaviour)."""
    from django_pymissive.processors.body import add_preview_browser

    missive = _email_missive()
    out = add_preview_browser("Hello", missive=missive, field_name="body_text")
    assert out == "Hello\n\nPREVIEW_TEXT"
