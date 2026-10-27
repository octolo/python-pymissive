"""Behavioural tests for the framework-independent Maileva helpers."""

import zlib

import pytest

from pymissive.providers.maileva import helpers


def test_http_error_summary_keeps_reasons_without_echoed_payload():
    payload = {
        "code": " INVALID_ADDRESS ",
        "message": "Recipient is invalid",
        "errors": [
            {"field": "address.postal_code", "message": "is required"},
            {"path": "address.city", "code": "invalid"},
            {"error": "global failure"},
            "ignored",
        ],
        "recipient": {"name": "Private Person", "address": "Private address"},
    }

    assert helpers._http_error_parts(payload) == [
        "INVALID_ADDRESS",
        "Recipient is invalid",
        "address.postal_code: is required",
        "address.city: invalid",
        "global failure",
    ]
    assert helpers._compact_http_error_detail(
        __import__("json").dumps(payload),
    ) == (
        "INVALID_ADDRESS — Recipient is invalid — address.postal_code: is required"
        " — address.city: invalid — global failure"
    )


def test_http_error_summary_ignores_invalid_data_deduplicates_and_limits_items():
    payload = {
        "message": "same",
        "detail": "same",
        "errors": [{"message": f"error {index}"} for index in range(10)],
    }

    parts = helpers._http_error_parts(payload)

    assert parts.count("same") == 1
    assert parts[-1] == "error 7"
    assert "error 8" not in parts
    assert helpers._http_error_reason_parts(["not", "a", "mapping"]) == []
    assert helpers._http_error_item_part(None) == ""
    assert helpers._compact_http_error_detail("") == ""
    assert helpers._compact_http_error_detail("not json") == ""
    assert helpers._compact_http_error_detail('{"message": "abcdefgh"}', limit=7) == "abcd..."


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        ("letter", ("mail", "v3")),
        ("registered_letter", ("registered_mail", "v4")),
    ],
)
def test_postal_api_selects_endpoint_from_product(product, expected):
    assert helpers._postal_api(product) == expected


def test_postal_api_rejects_unknown_product():
    with pytest.raises(ValueError, match="Unknown Maileva postal product.*parcel"):
        helpers._postal_api("parcel")


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, True),
        ({"acknowledgement": None}, True),
        ({"acknowledgement": ""}, True),
        ({"acknowledgement": True}, True),
        ({"acknowledgement": False}, False),
        ({"acknowledgement": "basic_delivery"}, False),
        ({"acknowledgement": " BASIC_DELIVERY "}, False),
        ({"acknowledgement": "registered"}, True),
        ({"acknowledgement_of_receipt": 0, "acknowledgement": "registered"}, False),
    ],
)
def test_registered_acknowledgement_normalization(kwargs, expected):
    assert helpers._registered_acknowledgement_of_receipt(kwargs) is expected


def test_notification_email_prefers_explicit_then_first_valid_recipient():
    recipients = [
        None,
        {"email": ""},
        {"email": " first@example.test "},
        {"email": "second@example.test"},
    ]

    assert (
        helpers._notification_email(
            notification_email=" explicit@example.test ",
            notification=recipients,
        )
        == "explicit@example.test"
    )
    assert helpers._notification_email(notification=recipients) == "first@example.test"
    assert helpers._notification_email(notification=[]) == ""


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (None, None),
        ({}, None),
        ({"substitute_id": "", "id": None}, None),
        ({"substitute_id": 42, "id": 7}, "42"),
        ({"id": 7}, "7"),
    ],
)
def test_provider_custom_id_uses_public_then_local_identifier(data, expected):
    assert helpers._provider_custom_id(data) == expected


def test_billing_pagination_builds_params_and_reads_both_response_shapes():
    assert helpers._billing_page_params(
        {"status": "paid", "unused": None, "empty": ""},
        20,
        10,
    ) == {"status": "paid", "start_index": 20, "count": 10}
    nested = {"invoice": {"items": [{"id": "nested"}]}, "items": [{"id": "flat"}]}
    assert helpers._billing_page_items(nested) == [{"id": "nested"}]
    assert helpers._billing_page_items({"invoice": {}, "items": [{"id": "flat"}]}) == [
        {"id": "flat"},
    ]
    assert helpers._billing_page_items({}) == []


@pytest.mark.parametrize(
    ("data", "page", "item_count", "count", "expected"),
    [
        ({}, [], 0, 10, True),
        ({}, [1], 1, 10, True),
        ({}, list(range(10)), 10, 10, False),
        ({"paging": {"total_results": "20"}}, list(range(10)), 19, 10, False),
        ({"paging": {"total_results": "20"}}, list(range(10)), 20, 10, True),
    ],
)
def test_billing_last_page_detection(data, page, item_count, count, expected):
    assert helpers._billing_page_is_last(data, page, item_count, count) is expected


def test_existing_recipient_reference_only_exposes_reusable_identity():
    assert helpers._existing_recipient_ref(None) is None
    assert helpers._existing_recipient_ref({"substitute_id": "orphan"}) is None
    assert helpers._existing_recipient_ref({"external_id": "ext"}) == {}
    assert helpers._existing_recipient_ref(
        {"id": "id-1", "substitute_id": "public-1", "name": "Ada"},
    ) == {"id": "id-1", "substitute_id": "public-1", "name": "Ada"}
    assert helpers._existing_recipient_ref({"id": "id-2"}) == {
        "id": "id-2",
        "substitute_id": "id-2",
    }


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"resource_name": "recipients"}, True),
        ({"resource_type": "mail/v3/recipients"}, True),
        ({"resource_type": "mail/v3/senders"}, False),
        ({}, False),
    ],
)
def test_recipient_resource_recognizes_both_maileva_discriminators(data, expected):
    assert helpers._is_recipient_resource(data) is expected


def test_address_line_5_classifies_po_boxes_and_localities():
    assert helpers._geoaddress_from_maileva_line_5("") == {}
    assert helpers._geoaddress_from_maileva_line_5("BP 42") == {
        "address_line3": "BP 42",
        "po_box": "BP 42",
    }
    assert helpers._geoaddress_from_maileva_line_5("Boîte Postale 8")["po_box"] == "Boîte Postale 8"
    assert helpers._geoaddress_from_maileva_line_5("Lieu-dit Le Moulin") == {
        "address_line3": "Lieu-dit Le Moulin",
        "locality": "Lieu-dit Le Moulin",
    }


def test_required_maileva_name_accepts_either_line_and_reports_role():
    helpers._require_maileva_line_1_or_2("Company", "", role="sender")
    helpers._require_maileva_line_1_or_2("", "Ada Lovelace", role="recipient")

    with pytest.raises(ValueError, match="Maileva recipient requires address_line_1 or address_line_2"):
        helpers._require_maileva_line_1_or_2(" ", None, role="recipient")


def test_address_line_6_requires_location_and_appends_sorting_code():
    assert (
        helpers._maileva_address_line_6(
            {"postal_code": " 75000 ", "city": " Paris ", "sorting_code": " CEDEX 15 "},
            role="recipient",
        )
        == "75000 Paris CEDEX 15"
    )

    with pytest.raises(ValueError, match="Maileva sender requires postal_code and city"):
        helpers._maileva_address_line_6({"postal_code": "75000"}, role="sender")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("", {}),
        ("75000 Paris", {"postal_code": "75000", "city": "Paris"}),
        (
            "75000 PARIS CEDEX 15",
            {"postal_code": "75000", "city": "PARIS", "sorting_code": "CEDEX 15"},
        ),
        (
            "I 39044 EGNA BZ ITALIE",
            {"postal_code": "39044", "city": "EGNA", "state_code": "BZ"},
        ),
        (
            "DE 12345 DE 12345 BERLIN GERMANY",
            {"postal_code": "12345", "city": "BERLIN"},
        ),
        ("PARIS", {"city": "PARIS"}),
    ],
)
def test_parse_maileva_address_line_6_handles_domestic_and_international_forms(line, expected):
    assert helpers._parse_maileva_address_line_6(line) == expected


def test_address_from_maileva_lines_reconstructs_prefixed_geoaddress():
    payload = {
        "sender_address_line_1": " Example Corp ",
        "sender_address_line_3": " Building B ",
        "sender_address_line_4": " 1 Main Street ",
        "sender_address_line_5": " BP 42 ",
        "sender_address_line_6": " 75000 PARIS CEDEX 15 ",
        "sender_country": " fr ",
    }

    assert helpers._address_from_maileva_lines(
        payload,
        prefix="sender_",
        country_key="sender_country",
    ) == {
        "organization": "Example Corp",
        "address_line2": "Building B",
        "address_line1": "1 Main Street",
        "country_code": "FR",
        "address_line3": "BP 42",
        "po_box": "BP 42",
        "postal_code": "75000",
        "city": "PARIS",
        "sorting_code": "CEDEX 15",
    }
    assert helpers._address_from_maileva_lines({}) is None


def _pdf_with_stream(content: bytes) -> bytes:
    return b"%PDF-1.4\n1 0 obj\nstream\n" + content + b"\nendstream\nendobj\n%%EOF"


def test_pdf_stream_iteration_supports_plain_zlib_and_raw_deflate():
    content = b"BT (RW799210633FR) Tj ET"
    raw_deflate = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    raw_compressed = raw_deflate.compress(content) + raw_deflate.flush()
    pdf = (
        _pdf_with_stream(content)
        + _pdf_with_stream(zlib.compress(content))
        + _pdf_with_stream(raw_compressed)
        + b"\nstream\nunterminated"
    )

    assert list(helpers._iter_pdf_streams(pdf)) == [content, content, content]
    assert helpers._inflate_pdf_stream(b"not compressed") is None


def test_pdf_unicode_map_decodes_ranges_and_explicit_characters():
    cmap = b"""
        beginbfrange
        <0001> <0003> <0041>
        endbfrange
        beginbfchar
        <0004> <20AC>
        endbfchar
    """
    mapping = helpers._pdf_tounicode_map([b"irrelevant", cmap])

    assert mapping == {1: "A", 2: "B", 3: "C", 4: "€"}
    assert helpers._pdf_decode_hex_tj("0001000200030004", mapping) == "ABC€"


def test_pdf_text_decoding_handles_escapes_hex_and_malformed_values():
    assert helpers._pdf_unescape_literal(rb"A\nB\050C\051\\") == "A\nB(C)\\"
    assert helpers._pdf_unescape_literal(b"trailing\\") == "trailing\\"
    assert helpers._pdf_decode_hex_tj("4142", {}) == "AB"
    assert helpers._pdf_decode_hex_tj("", {}) == ""
    assert helpers._pdf_decode_hex_tj("ABC", {}) == ""
    assert helpers._pdf_decode_hex_tj("000100", {1: "A"}) == "\x00A\x00"


def test_tracking_number_extraction_prefers_upu_and_supports_french_lr():
    both = _pdf_with_stream(b"BT (1234567890123) Tj (rw799210633fr) Tj ET")
    domestic_hex = _pdf_with_stream(b"BT <313233343536373839303132333435> Tj ET")

    assert helpers.extract_tracking_number_from_deposit_proof(both) == "RW799210633FR"
    assert helpers.extract_tracking_number_from_deposit_proof(domestic_hex) == "123456789012345"
    assert helpers.extract_tracking_number_from_deposit_proof(_pdf_with_stream(b"(nothing) Tj")) is None
