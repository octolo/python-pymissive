"""Regression: ``body_text_compiled`` must use the SMS pipeline for SMS/RCS missives.

Before the fix, sending an SMS routed ``body_text`` through the email
``body_text`` body-processor chain (signature appended with the long
email variant) while the preview correctly used ``body_sms_compiled``
(short SMS signature). The two compiled properties must now agree on
SMS/RCS so the provider receives the same text as the preview shows.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from django_pymissive.models.missive import Missive
from tests.processors import SIGNATURE_SMS, SIGNATURE_TEXT

pytestmark = pytest.mark.django_db


SIGNATURE_CHAIN = [
    "django_pymissive.processors.body.django_template.django_template_processor",
    "tests.processors.add_signature",
]


@override_settings(PYMISSIVE_DEFAULT_BODY_PROCESSORS=SIGNATURE_CHAIN)
def test_body_text_compiled_uses_sms_signature_for_sms_missive():
    missive = Missive.objects.create(
        missive_type="sms",
        body_text="hello",
    )
    compiled = missive.body_text_compiled
    assert compiled.endswith(SIGNATURE_SMS), (
        f"SMS body_text_compiled must carry the SMS signature; got {compiled!r}"
    )
    assert SIGNATURE_TEXT not in compiled, (
        "SMS body_text_compiled must NOT carry the long email signature"
    )
    assert compiled == missive.body_sms_compiled, (
        "SMS body_text_compiled and body_sms_compiled must agree (one renders "
        "the preview, the other is what the provider receives)"
    )


@override_settings(PYMISSIVE_DEFAULT_BODY_PROCESSORS=SIGNATURE_CHAIN)
def test_body_text_compiled_uses_sms_signature_for_rcs_missive():
    missive = Missive.objects.create(missive_type="rcs", body_text="hello")
    assert missive.body_text_compiled.endswith(SIGNATURE_SMS)


@override_settings(PYMISSIVE_DEFAULT_BODY_PROCESSORS=SIGNATURE_CHAIN)
def test_body_text_compiled_keeps_email_signature_for_email_missive():
    missive = Missive.objects.create(missive_type="email", body_text="hello")
    compiled = missive.body_text_compiled
    assert compiled.endswith(SIGNATURE_TEXT)
    assert SIGNATURE_SMS not in compiled.split("\n")[-1]
