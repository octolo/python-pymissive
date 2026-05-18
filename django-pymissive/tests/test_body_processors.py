"""Unit tests for ``django_pymissive.body_processors``.

Covers the resolver, the chain runner, the default Django template
processor, and the override semantics for
``PYMISSIVE_DEFAULT_BODY_PROCESSORS``.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from django_pymissive.body_processors import (
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
        "django_pymissive.body_processors.django_template_processor",
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
