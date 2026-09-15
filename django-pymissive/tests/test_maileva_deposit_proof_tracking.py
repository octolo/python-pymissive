"""Maileva deposit-proof PDFs carry the public carrier tracking number.

The real proofs contain personal data and are not committed. To run these
tests locally, drop the two files in ``tests/fixtures/`` then::

    pytest tests/test_maileva_deposit_proof_tracking.py
"""

from pathlib import Path

import pytest

from pymissive.providers.maileva import (
    MailevaProvider,
    extract_tracking_number_from_deposit_proof,
)

FIXTURES = Path(__file__).parent / "fixtures"
FRANCE_PDF = FIXTURES / "deposit_proof_france.pdf"
ITALY_PDF = FIXTURES / "deposit_proof_italy.pdf"

pytestmark = pytest.mark.deposit_proof


def _require_fixture(path: Path) -> Path:
    if not path.exists():
        pytest.skip(
            f"{path.name} is not committed (personal data). "
            f"Copy it to {FIXTURES} to run this test."
        )
    return path


def test_extract_tracking_number_from_french_deposit_proof():
    pdf = _require_fixture(FRANCE_PDF).read_bytes()
    assert extract_tracking_number_from_deposit_proof(pdf) == "875001584741682"


def test_extract_tracking_number_from_international_deposit_proof():
    pdf = _require_fixture(ITALY_PDF).read_bytes()
    assert extract_tracking_number_from_deposit_proof(pdf) == "RW799210633FR"


def test_tracking_number_lre_prefers_deposit_proof_over_api_field():
    france_pdf = _require_fixture(FRANCE_PDF).read_bytes()

    class _Provider(MailevaProvider):
        def __init__(self):
            self.ack_level = "acknowledgement_of_receipt"

        def is_acknowledgement_of_receipt(self, **kwargs):
            return True

        def _detail_recipients_lre(self, external_id):
            return [
                {
                    "custom_id": "rec-1",
                    "id": "mv-recipient-1",
                    "registered_number": "API-SHOULD-BE-IGNORED",
                    "deposit_proof_url": "/registered_mail/v4/proofs/abc",
                }
            ]

        def _download_proof_bytes(self, url):
            assert url == "/registered_mail/v4/proofs/abc"
            return france_pdf

    result = _Provider().tracking_number_lre(external_id="sending-1")
    assert result == [
        {
            "internal_id": "rec-1",
            "external_id": "mv-recipient-1",
            "substitute_id": "rec-1",
            "tracking_number": "875001584741682",
        }
    ]
