# Missive

Monorepo containing **python-pymissive** (framework-agnostic Python library for multi-channel messaging) and **django-pymissive** (Django integration).

## Packages

### python-pymissive — `python-pymissive/`

Lightweight, framework-agnostic Python library for sending multi-channel missives. Built on ProviderKit. Distributed on PyPI as `pymissive`.

- **8 providers**: Brevo, Scaleway, Maileva, SMSPartner, Slack, Teams, Discord, hand delivery
- **Modular architecture**: works with or without a framework
- **Channels**: email, SMS, WhatsApp, registered electronic mail (registered letter), team messaging

📁 Details: [python-pymissive/README.md](python-pymissive/README.md) | Docs: [python-pymissive/docs/](python-pymissive/docs/)

### django-pymissive — `django-pymissive/`

Full Django integration for managing multi-channel missive delivery. Admin interface, models, unified webhooks, and delivery tracking.

- **Django admin interface**: manage missives with validation and preview
- **Unified webhooks**: `/missive/webhook/<provider>/<missive_type>/`
- **Recipient model**: centralised contact management
- **Dependency**: requires `pymissive`

📁 Details: [django-pymissive/README.md](django-pymissive/README.md)

## Repository structure

```
missive/
├── python-pymissive/   # Core library
├── django-pymissive/   # Django integration
└── README.md
```

## Development

`django-pymissive` depends on the core package, so install the local copy first
or pip will look for a released version on PyPI.

```bash
# Core library
cd python-pymissive && pip install -e .

# Django integration, against the local core
cd django-pymissive && pip install -e ../python-pymissive && pip install -e ".[test]"
```

The test suite lives in `django-pymissive/`; the core package has no tests of
its own yet and CI only checks that it imports.

```bash
cd django-pymissive && python manage.py check && python -m pytest

# Linting, from the repository root (same command as CI)
ruff check python-pymissive/src django-pymissive/src
```

## Licence

MIT
