"""Public postal tracking URLs keyed by ISO country code."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from urllib.parse import quote


@cache
def postal_tracking_urls() -> dict[str, dict[str, str]]:
    raw = files("pymissive").joinpath("postal_tracking_urls.json").read_text(encoding="utf-8")
    return json.loads(raw)


def get_tracking_url(
    country_code: str | None,
    tracking_number: str | None = None,
) -> str | None:
    """Return the carrier tracking URL for ``country_code``.

    Replaces ``{tracking}`` with ``tracking_number`` when the number is present.
    Returns ``None`` when the country is unknown or the URL still needs a number.
    """
    if not country_code:
        return None
    entry = postal_tracking_urls().get(str(country_code).strip().upper())
    if not entry:
        return None
    url = entry.get("tracking_url")
    if not url:
        return None
    if tracking_number:
        url = url.replace("{tracking}", quote(str(tracking_number), safe=""))
    if "{tracking}" in url:
        return None
    return url
