"""Build hooks for campaign-target sends against fakeapp contacts."""

from __future__ import annotations


def build_contact_email(campaign, target, missive_type):
    """Draft an email when *target* has an ``email`` attribute."""
    from django_pymissive.services.drafts import build_draft

    return build_draft(
        campaign,
        target,
        missive_type,
        name=getattr(target, "full_name", "") or str(target),
        email=getattr(target, "email", None),
    )


def build_campaign_contact(campaign, target, missive_type, **kwargs):
    """Draft from a target object. Does not send.

    Delegates to :func:`build_target_processor`: one recipient from ``email``,
    ``phone`` or ``address``, plus the plurals when ``full_targets`` is set.
    """
    from django_pymissive.processors.build_target import build_target_processor

    return build_target_processor(campaign, target, missive_type, **kwargs)
