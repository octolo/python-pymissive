"""Maileva retrieve maps all address_line_N fields to geoaddress."""

from pymissive.providers.maileva import (
    MailevaProvider,
    _address_from_maileva_lines,
    _parse_maileva_address_line_6,
)


def test_parse_domestic_line_6():
    assert _parse_maileva_address_line_6("75000 Paris") == {
        "postal_code": "75000",
        "city": "Paris",
    }


def test_parse_line_6_cedex():
    assert _parse_maileva_address_line_6("75000 PARIS CEDEX 01") == {
        "postal_code": "75000",
        "city": "PARIS",
        "sorting_code": "CEDEX 01",
    }


def test_parse_international_italy_line_6():
    assert _parse_maileva_address_line_6("I 39044 EGNA BZ ITALIE") == {
        "postal_code": "39044",
        "city": "EGNA",
        "state_code": "BZ",
    }


def test_parse_line_6_with_postal_prepended_on_send():
    assert _parse_maileva_address_line_6("39044 I 39044 EGNA BZ ITALIE") == {
        "postal_code": "39044",
        "city": "EGNA",
        "state_code": "BZ",
    }


def test_address_from_maileva_france_payload():
    address = _address_from_maileva_lines(
        {
            "id": "d905a65e-aa46-4f37-8480-260c4600c810",
            "custom_id": "custom12234",
            "address_line_1": "La Poste",
            "address_line_2": "Me Eva DUPONT",
            "address_line_3": "Résidence des Peupliers",
            "address_line_4": "33 avenue de Paris",
            "address_line_5": "BP 356",
            "address_line_6": "75000 Paris",
            "country_code": "FR",
        }
    )
    assert address == {
        "organization": "La Poste",
        "address_line2": "Résidence des Peupliers",
        "address_line1": "33 avenue de Paris",
        "address_line3": "BP 356",
        "po_box": "BP 356",
        "postal_code": "75000",
        "city": "Paris",
        "country_code": "FR",
    }
    assert "address_line_2" not in address
    assert "Me Eva DUPONT" not in address.values()


def test_address_line_5_lieu_dit_is_locality():
    address = _address_from_maileva_lines(
        {
            "address_line_4": "12 rue des Champs",
            "address_line_5": "Lieu-dit Les Fauvettes",
            "address_line_6": "01000 Bourg-en-Bresse",
            "country_code": "FR",
        }
    )
    assert address["locality"] == "Lieu-dit Les Fauvettes"
    assert address["address_line3"] == "Lieu-dit Les Fauvettes"
    assert "po_box" not in address


def test_address_from_maileva_italy_payload():
    address = _address_from_maileva_lines(
        {
            "address_line_1": "RIWEGA SRL",
            "address_line_2": "Mario Rossi",
            "address_line_4": "Via Isola Di Sopra 28",
            "address_line_6": "I 39044 EGNA BZ ITALIE",
            "country_code": "IT",
        }
    )
    assert address == {
        "organization": "RIWEGA SRL",
        "address_line1": "Via Isola Di Sopra 28",
        "country_code": "IT",
        "postal_code": "39044",
        "city": "EGNA",
        "state_code": "BZ",
    }


def test_serialize_recipient_uses_all_maileva_lines():
    provider = MailevaProvider.__new__(MailevaProvider)
    data = provider._serialize_recipient_ref(
        {"id": "custom12234"},
        {
            "id": "d905a65e-aa46-4f37-8480-260c4600c810",
            "custom_id": "custom12234",
            "address_line_1": "La Poste",
            "address_line_2": "Me Eva DUPONT",
            "address_line_3": "Résidence des Peupliers",
            "address_line_4": "33 avenue de Paris",
            "address_line_5": "BP 356",
            "address_line_6": "75000 Paris",
            "country_code": "FR",
        },
    )
    assert data["name"] == "Me Eva DUPONT"
    assert data["internal_id"] == "custom12234"
    assert data["substitute_id"] == "custom12234"
    assert data["external_id"] == "d905a65e-aa46-4f37-8480-260c4600c810"
    assert data["address"] == {
        "organization": "La Poste",
        "address_line2": "Résidence des Peupliers",
        "address_line1": "33 avenue de Paris",
        "address_line3": "BP 356",
        "po_box": "BP 356",
        "postal_code": "75000",
        "city": "Paris",
        "country_code": "FR",
    }


def test_serialize_recipient_prefers_parsed_maileva_lines():
    provider = MailevaProvider.__new__(MailevaProvider)
    data = provider._serialize_recipient_ref(
        {"id": "local-id", "address": {"city": "should not win"}},
        {
            "id": "mv-1",
            "custom_id": "local-id",
            "address_line_1": "RIWEGA SRL",
            "address_line_2": "Mario Rossi",
            "address_line_4": "Via Isola Di Sopra 28",
            "address_line_6": "39044 I 39044 EGNA BZ ITALIE",
            "country_code": "it",
        },
    )
    assert data["name"] == "Mario Rossi"
    assert data["address"] == {
        "organization": "RIWEGA SRL",
        "address_line1": "Via Isola Di Sopra 28",
        "country_code": "IT",
        "postal_code": "39044",
        "city": "EGNA",
        "state_code": "BZ",
    }


_FR_RECIPIENT_PAYLOAD = {
    "id": "d905a65e-aa46-4f37-8480-260c4600c810",
    "custom_id": "custom12234",
    "address_line_1": "La Poste",
    "address_line_2": "Me Eva DUPONT",
    "address_line_3": "Résidence des Peupliers",
    "address_line_4": "33 avenue de Paris",
    "address_line_5": "BP 356",
    "address_line_6": "75000 Paris",
    "country_code": "FR",
}

_FR_GEOADDRESS = {
    "organization": "La Poste",
    "address_line2": "Résidence des Peupliers",
    "address_line1": "33 avenue de Paris",
    "address_line3": "BP 356",
    "po_box": "BP 356",
    "postal_code": "75000",
    "city": "Paris",
    "country_code": "FR",
}


def test_normalize_recipients_maps_raw_maileva_lines():
    provider = MailevaProvider.__new__(MailevaProvider)
    recipients = provider.get_normalize_recipients({"recipients": [_FR_RECIPIENT_PAYLOAD]})
    assert recipients == [
        {
            "internal_id": "custom12234",
            "external_id": "d905a65e-aa46-4f37-8480-260c4600c810",
            "substitute_id": "custom12234",
            "name": "Me Eva DUPONT",
            "address": _FR_GEOADDRESS,
        }
    ]


def test_normalize_sender_address_from_maileva_lines():
    provider = MailevaProvider.__new__(MailevaProvider)
    data = {
        "sender_address_line_1": "La Poste",
        "sender_address_line_2": "Service Courrier",
        "sender_address_line_3": "Résidence des Peupliers",
        "sender_address_line_4": "33 avenue de Paris",
        "sender_address_line_5": "BP 356",
        "sender_address_line_6": "75000 Paris",
        "sender_country_code": "FR",
    }
    assert provider.get_normalize_sender_name(data) == "Service Courrier"
    assert provider.get_normalize_sender_address(data) == _FR_GEOADDRESS


def test_normalize_sender_address_keeps_already_mapped_geoaddress():
    provider = MailevaProvider.__new__(MailevaProvider)
    mapped = {"address_line1": "10 rue Example", "city": "Paris", "country_code": "FR"}
    data = {
        "sender_address": mapped,
        "sender_address_line_4": "should not win",
        "sender_country_code": "FR",
    }
    assert provider.get_normalize_sender_address(data) == mapped


def test_recipient_lre_custom_id_prefers_substitute_id():
    provider = MailevaProvider.__new__(MailevaProvider)
    data = provider.get_recipient_lre_data(
        {
            "id": "local-pk",
            "substitute_id": "legacy-custom-id",
            "name": "Alice",
            "address": {
                "address_line1": "1 rue",
                "postal_code": "75001",
                "city": "Paris",
                "country_code": "FR",
            },
        }
    )
    assert data["custom_id"] == "legacy-custom-id"


def test_recipient_lre_custom_id_falls_back_to_id():
    provider = MailevaProvider.__new__(MailevaProvider)
    data = provider.get_recipient_lre_data(
        {
            "id": "uuid-or-pk",
            "name": "Alice",
            "address": {
                "address_line1": "1 rue",
                "postal_code": "75001",
                "city": "Paris",
                "country_code": "FR",
            },
        }
    )
    assert data["custom_id"] == "uuid-or-pk"

