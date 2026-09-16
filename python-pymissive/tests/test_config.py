"""Config helpers stay consistent without Django."""

from __future__ import annotations

import pytest

from pymissive.config import (
    ADDRESS_FIELDS,
    EMAIL_FIELDS,
    GENERIC_SUPPORT,
    MISSIVE_FIELDS,
    PHONE_FIELDS,
    fields_to_arg_config,
    get_config_by_support,
    missive_service_type,
    missive_types_for_support,
    normalize_missive_type,
    normalize_support,
    provider_service_name,
)


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
