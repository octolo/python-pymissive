# Changelog

## 1.5.0 — 2026-10-26

### Compatibility

- Python 3.11 or newer is now required.
- Django 5.0 through 5.2 is supported.
- `django-pymissive` now requires `pymissive>=1.5.0,<2`.

### Changes

- Brevo and Maileva implementations are organized as provider packages while
  preserving `pymissive.providers.brevo` and
  `pymissive.providers.maileva` imports.
- Campaign selection, scheduler tracking and cancellation handling were
  strengthened.
- Import allowlists and Teams webhook URL validation were hardened.
- Both distributions now include typing markers, and CI verifies Mypy and
  wheel package data.

Applications still running Python 3.10 must upgrade Python before installing
this release.
