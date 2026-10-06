"""Optional override for the campaign named-id generator."""

from django.conf import settings
from django.utils.module_loading import import_string

from namedid import generate_namedid

CAMPAIGN_NAMED_ID_GENERATOR = "PYMISSIVE_CAMPAIGN_NAMED_ID_GENERATOR"


def campaign_named_id(instance, source_fields, separator="-"):
    """Use ``PYMISSIVE_CAMPAIGN_NAMED_ID_GENERATOR`` when it is set.

    Without the setting, this calls :func:`namedid.generate_namedid`. The
    setting may be a dotted path or a callable with that same signature:
    ``(instance, source_fields, separator) -> str``. Collision suffixes are
    still applied by the field.
    """
    custom = getattr(settings, CAMPAIGN_NAMED_ID_GENERATOR, None)
    if not custom:
        return generate_namedid(instance, source_fields, separator)
    generator = custom if callable(custom) else import_string(custom)
    return generator(instance, source_fields, separator)
