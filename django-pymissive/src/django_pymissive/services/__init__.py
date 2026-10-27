"""Campaign target selection, materialization and sending.

The checkbox is a :class:`~django_pymissive.models.campaign_target.CampaignTarget`
row. The missive is created at send time.

Typical use::

    from django_pymissive.services import select, start_selection

    select(campaign, "email", participants)
    start_selection(
        campaign,
        ["email"],
        build="myapp.campaigns.build_missive",
    )

``build(campaign, target, missive_type)`` returns a saved draft missive, or
``None`` to skip that target. :func:`build_draft` creates the usual one
recipient draft when the project already knows the contact fields.
"""

from .drafts import (
    build_draft,
    delete_drafts,
    existing_draft,
    last_sent,
    link_target,
    materialize_missive,
    resend_draft,
)
from .send import (
    SELECTION_TASK,
    CampaignAlreadySending,
    build_send_preview,
    generate_target,
    materialize_selection,
    run_selection,
    selection_build,
    send_target,
    start_selection,
)
from .targets import (
    counts,
    is_selected,
    iter_targets,
    select,
    selection_qs,
    unselect,
)

__all__ = [
    "SELECTION_TASK",
    "CampaignAlreadySending",
    "build_draft",
    "build_send_preview",
    "counts",
    "delete_drafts",
    "existing_draft",
    "generate_target",
    "is_selected",
    "iter_targets",
    "last_sent",
    "link_target",
    "materialize_missive",
    "materialize_selection",
    "resend_draft",
    "run_selection",
    "selection_build",
    "select",
    "selection_qs",
    "send_target",
    "start_selection",
    "unselect",
]
