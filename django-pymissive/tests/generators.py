"""Named-id generators used to exercise the campaign setting override."""

from namedid import generate_namedid


def test_campaign_named_id(instance, source_fields, separator="-"):
    """Prefix the default slug so tests can tell the override is active."""
    base = generate_namedid(instance, source_fields, separator)
    return f"test{separator}{base}" if base else base
