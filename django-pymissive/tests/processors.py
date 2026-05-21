"""Body processors used for live testing of django-pymissive.

Some are wired in ``tests/settings.py`` via
``PYMISSIVE_DEFAULT_BODY_PROCESSORS`` so every missive sent against this test
project goes through them. Others (like :func:`add_test_banner` /
:class:`BannerProcessor`) are intentionally NOT wired by default and meant to
be added manually to a specific missive or campaign's ``body_processors``
JSON field to test per-instance overrides. Use as reference implementations
for real business processors.

The watermark / filigrane PDF processor lives in
:mod:`django_pymissive.processors.pdf` (it's a built-in, not test-only).
"""

from django_pymissive.processors.body import MissiveBodyProcessor


SIGNATURE_HTML = (
    '<hr style="margin-top:24px"/>'
    '<p style="font-size:12px;color:#666">'
    "Best regards,<br/>"
    "<strong>The django-pymissive team</strong><br/>"
    "<em>(signature appended by the test processor)</em>"
    "</p>"
)

SIGNATURE_TEXT = (
    "\n\n--\n"
    "Best regards,\n"
    "The django-pymissive team\n"
    "(signature appended by the test processor)"
)

SIGNATURE_SMS = " - django-pymissive"


def add_signature(content, *, missive=None, campaign=None, field_name=None, context=None, **kwargs):
    """Append a signature to a missive body, picking the right format per field.

    Skips ``subject`` and SMS first_document; appends HTML markup for
    ``body_html`` / ``first_document``, plain text for ``body_text``, and a
    short suffix for ``body_sms``.
    """
    if not content:
        return content
    if field_name in ("body_html", "first_document"):
        return f"{content}{SIGNATURE_HTML}"
    if field_name == "body_text":
        return f"{content}{SIGNATURE_TEXT}"
    if field_name == "body_sms":
        return f"{content}{SIGNATURE_SMS}"
    return content


class SignatureProcessor(MissiveBodyProcessor):
    """Class-based variant of :func:`add_signature` for symmetry / examples.

    Demonstrates the class-based API: subclass ``MissiveBodyProcessor`` and
    override ``process``. Configurable via ``kwargs`` passed from the
    processor entry, e.g. ``["tests.processors.SignatureProcessor",
    {"team": "Support"}]``.
    """

    def process(self, content, *, missive=None, campaign=None, field_name=None, context=None, team=None, **kwargs):
        if not content:
            return content
        team = team or "django-pymissive"
        if field_name in ("body_html", "first_document"):
            return (
                f"{content}"
                '<hr style="margin-top:24px"/>'
                '<p style="font-size:12px;color:#666">'
                f"Best regards,<br/><strong>{team}</strong>"
                "</p>"
            )
        if field_name == "body_text":
            return f"{content}\n\n--\n{team}"
        if field_name == "body_sms":
            return f"{content} - {team}"
        return content


# ---------------------------------------------------------------------------
# Opt-in processors — NOT wired in PYMISSIVE_DEFAULT_BODY_PROCESSORS.
# Add them manually to a specific Missive/MissiveCampaign ``body_processors``
# field to test per-instance behaviour, e.g.:
#
#     missive.body_processors = ["tests.processors.add_test_banner"]
#     missive.save()
#
# Or with kwargs:
#
#     campaign.body_processors = [
#         ["tests.processors.BannerProcessor", {"label": "INTERNAL"}],
#     ]
#     campaign.save()
# ---------------------------------------------------------------------------

BANNER_HTML = (
    '<div style="background:#fff3cd;border:1px solid #ffeeba;'
    'padding:12px;margin-bottom:16px;border-radius:4px;'
    'font-size:13px;color:#856404">'
    "{label}"
    "</div>"
)

BANNER_TEXT = "[{label}]\n\n"

BANNER_DEFAULT_LABEL = "TEST BANNER — added by add_test_banner processor"


def add_test_banner(content, *, missive=None, campaign=None, field_name=None, context=None, label=None, **kwargs):
    """Prepend a visible banner at the top of the body (opt-in, NOT a default).

    Skips ``subject``. Adds an HTML banner for ``body_html`` /
    ``first_document``, a bracketed prefix for ``body_text`` / ``body_sms``.
    Use this to verify that processors set on a single
    ``Missive.body_processors`` (or ``MissiveCampaign.body_processors``) run
    as expected, on top of the global defaults.
    """
    if not content:
        return content
    label = label or BANNER_DEFAULT_LABEL
    if field_name in ("body_html", "first_document"):
        return BANNER_HTML.format(label=label) + content
    if field_name in ("body_text", "body_sms"):
        return BANNER_TEXT.format(label=label) + content
    return content


class BannerProcessor(MissiveBodyProcessor):
    """Class-based variant of :func:`add_test_banner`.

    Equivalent behaviour, demonstrating the class-based API. Both the
    function and this class are intentionally NOT included in
    ``PYMISSIVE_DEFAULT_BODY_PROCESSORS`` so they can be enabled per
    instance via the ``body_processors`` JSON field, e.g.::

        ["tests.processors.BannerProcessor", {"label": "DRY-RUN"}]
    """

    def process(self, content, *, missive=None, campaign=None, field_name=None, context=None, label=None, **kwargs):
        return add_test_banner(
            content,
            missive=missive,
            campaign=campaign,
            field_name=field_name,
            context=context,
            label=label,
            **kwargs,
        )
