"""Verify that built wheels contain the runtime package data."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile


EXPECTED_FILES = {
    "pymissive": {
        "pymissive/.commands.json",
        "pymissive/commands/_docs/attachment.md",
        "pymissive/commands/_docs/billing.md",
        "pymissive/commands/_docs/missive.md",
        "pymissive/commands/_docs/recipient.md",
        "pymissive/commands/_docs/webhook.md",
        "pymissive/postal_tracking_urls.json",
        "pymissive/py.typed",
    },
    "django-pymissive": {
        "django_pymissive/py.typed",
    },
}

EXPECTED_PREFIXES = {
    "pymissive": (),
    "django-pymissive": (
        "django_pymissive/locale/",
        "django_pymissive/migrations/",
        "django_pymissive/static/",
        "django_pymissive/templates/",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", choices=EXPECTED_FILES, required=True)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()

    with ZipFile(args.wheel) as archive:
        names = set(archive.namelist())

    missing = sorted(EXPECTED_FILES[args.package] - names)
    missing.extend(prefix for prefix in EXPECTED_PREFIXES[args.package] if not any(n.startswith(prefix) for n in names))
    if missing:
        raise SystemExit(f"{args.wheel} is missing packaged content: {', '.join(missing)}")

    print(f"{args.wheel}: package data verified")


if __name__ == "__main__":
    main()
