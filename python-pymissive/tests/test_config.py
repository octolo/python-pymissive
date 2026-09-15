"""Config helpers stay consistent without Django."""

from __future__ import annotations

from pymissive.config import (
    ADDRESS_FIELDS,
    EMAIL_FIELDS,
    GENERIC_SUPPORT,
    MISSIVE_FIELDS,
    PHONE_FIELDS,
    fields_to_arg_config,
    get_config_by_support,
    missive_types_for_support,
    normalize_support,
)


def test_normalize_support_accepts_key_type_and_alias():
    assert normalize_support("address") == "address"
    assert normalize_support("lre") == "address"
    assert normalize_support("postal") == "address"
    assert normalize_support("hand-delivery") == "address"
    assert normalize_support("not-a-support") == ""


def test_missive_types_for_support_round_trips():
    for support, types in GENERIC_SUPPORT.items():
        assert missive_types_for_support(support) == list(types)
    assert missive_types_for_support("sms") == list(GENERIC_SUPPORT["phone"])
    assert missive_types_for_support("unknown") == []


def test_get_config_by_support_returns_the_support_fields():
    assert get_config_by_support("email") is EMAIL_FIELDS
    assert get_config_by_support("ere") is EMAIL_FIELDS
    assert get_config_by_support("sms") is PHONE_FIELDS
    assert get_config_by_support("lre") is ADDRESS_FIELDS
    assert get_config_by_support("branded") is MISSIVE_FIELDS
    assert get_config_by_support("not-a-type") is MISSIVE_FIELDS


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
