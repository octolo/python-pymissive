"""Config helpers stay consistent without Django."""

from __future__ import annotations

import pytest
from pymissive.config import (
    ADDRESS_FIELDS,
    ALL_EVENTS,
    EMAIL_FIELDS,
    FAILED_EVENTS,
    GENERIC_SUPPORT,
    INFO_EVENTS,
    MISSIVE_FIELDS,
    MISSIVE_TYPES,
    PHONE_FIELDS,
    SENT_EVENTS,
    SUCCESSFUL_EVENTS,
    fields_to_arg_config,
    get_config_by_support,
    missive_service_type,
    missive_support_for_type,
    missive_types_for_support,
    normalize_missive_type,
    normalize_support,
    provider_service_name,
)
from pymissive.config.recipient import RECIPIENT_FIELDS


def test_normalize_support_accepts_key_and_type():
    assert normalize_support("address") == "address"
    assert normalize_support("registered_letter") == "address"
    assert normalize_support("letter") == "address"
    assert normalize_support("hand-delivery") == "address"
    assert normalize_support("not-a-support") == ""
    assert normalize_support("postal") == ""
    assert normalize_support("courrier") == ""
    assert normalize_support("mail") == ""
    assert normalize_support("app") == ""


def test_normalize_missive_type_is_strict():
    assert normalize_missive_type("registered_letter") == "registered_letter"
    assert normalize_missive_type("letter") == "letter"
    assert normalize_missive_type("address") == ""
    assert normalize_missive_type("") == ""


def test_missive_types_for_support_round_trips():
    for support, types in GENERIC_SUPPORT.items():
        assert missive_types_for_support(support) == list(types)
    assert missive_types_for_support("sms") == list(GENERIC_SUPPORT["phone"])
    assert missive_types_for_support("unknown") == []


def test_get_config_by_support_returns_the_support_fields():
    assert get_config_by_support("email") is EMAIL_FIELDS
    assert get_config_by_support("ere") is EMAIL_FIELDS
    assert get_config_by_support("sms") is PHONE_FIELDS
    assert get_config_by_support("registered_letter") is ADDRESS_FIELDS
    assert get_config_by_support("letter") is ADDRESS_FIELDS
    assert get_config_by_support("branded") is MISSIVE_FIELDS
    assert get_config_by_support("not-a-type") is MISSIVE_FIELDS


def test_letter_and_registered_letter_have_distinct_provider_services():
    assert provider_service_name("send", "letter") == "send_letter"
    assert provider_service_name("preview", "registered_letter") == "preview_registered_letter"
    assert provider_service_name("retrieve", "email") == "retrieve_email"
    assert missive_service_type("hand-delivery") == "hand_delivery"


def test_unknown_missive_type_does_not_build_a_service_name():
    with pytest.raises(ValueError, match="Unknown missive type"):
        missive_service_type("lre")
    with pytest.raises(ValueError, match="Unknown missive type"):
        provider_service_name("send", "postal")


def test_every_missive_type_belongs_to_one_support():
    owners: dict[str, str] = {}
    for support, types in GENERIC_SUPPORT.items():
        assert normalize_support(support) == support
        configured = tuple(types)
        returned = missive_types_for_support(support)
        assert returned == list(configured)
        returned.append("mutated")
        assert tuple(types) == configured
        for missive_type in types:
            assert missive_type not in owners, f"{missive_type} belongs to {owners.get(missive_type)} and {support}"
            assert missive_type in MISSIVE_TYPES, missive_type
            owners[missive_type] = support

    orphans = set(MISSIVE_TYPES) - set(owners)
    assert orphans == set()

    for missive_type, support in owners.items():
        assert normalize_missive_type(missive_type) == missive_type
        assert missive_support_for_type(missive_type) == support
        assert normalize_support(missive_type) == support
        hyphenated = missive_type.replace("_", "-")
        assert normalize_missive_type(hyphenated) == missive_type
        assert missive_support_for_type(hyphenated) == support
        assert normalize_support(hyphenated) == support


def test_sent_events_keep_their_documented_order_and_membership():
    assert SENT_EVENTS == ("sent", "accepted", "delivered")
    assert set(SENT_EVENTS) <= set(ALL_EVENTS)


def test_event_categories_partition_all_events():
    successful = set(SUCCESSFUL_EVENTS)
    failed = set(FAILED_EVENTS)
    info = set(INFO_EVENTS)
    assert successful.isdisjoint(failed)
    assert successful.isdisjoint(info)
    assert failed.isdisjoint(info)
    assert set(ALL_EVENTS) == successful | failed | info
    assert len(ALL_EVENTS) == len(successful) + len(failed) + len(info)


_RECIPIENT_CONTRACT_FIELDS = (
    "recipient_type",
    "name",
    "internal_id",
    "external_id",
    "substitute_id",
    "email",
    "phone",
    "address",
    "notification_id",
    "sent_at",
    "delivered_at",
    "tracking_number",
)


def test_recipient_contract_fields_keep_their_formats():
    missing = [name for name in _RECIPIENT_CONTRACT_FIELDS if name not in RECIPIENT_FIELDS]
    assert missing == []
    for name in _RECIPIENT_CONTRACT_FIELDS:
        assert RECIPIENT_FIELDS[name].get("format"), name
    assert RECIPIENT_FIELDS["sent_at"]["format"] == "datetime"
    assert RECIPIENT_FIELDS["delivered_at"]["format"] == "datetime"


def test_fields_to_arg_config_maps_formats():
    fields = {
        "name": {"format": "str", "label": "Name"},
        "count": {"format": "int", "label": "Count"},
        "flag": {"format": "bool", "label": "Flag"},
    }
    parsed = fields_to_arg_config(fields)
    assert parsed["name"]["type"] is str
    assert parsed["count"]["type"] is int
    assert parsed["flag"]["type"] == "store_true"
