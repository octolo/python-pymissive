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

CI also audits dependencies and runs Bandit separately for each package.
Bandit findings in the Django package are reported without blocking pending
review.

`django-pymissive` depends on the core package, so install the local copy first
or pip will look for a released version on PyPI.

```bash
# Core library
(cd python-pymissive && pip install -e ".[test]")

# Django integration, against the local core
(cd django-pymissive && pip install -e ../python-pymissive && pip install -e ".[test]")
```

Each package has its own test suite:

```bash
(cd python-pymissive && python -m pytest)
(cd django-pymissive && python manage.py check && python -m pytest)

# Linting, from the repository root (same command as CI)
ruff check python-pymissive/src django-pymissive/src
```

## Licence

MIT

## CI packaging check

CI also installs the built wheel(s) in a clean environment and checks their
dependencies and imports without publishing. This installation check is
non-blocking during the initial rollout.

## Local audit

Install the project's development/test dependencies (including both local
packages where applicable), plus the audit tools:

```bash
python -m pip install ruff mypy bandit pip-audit vulture radon xenon pytest pytest-django pytest-cov build twine
make audit
```

Use the activated environment's Python, or pass `make audit PYTHON=/path/to/python`.
On systems without Make, run `python scripts/audit.py` directly. Git is required;
the geoaddress widget tests also require Node.js. The audit reports missing test
suites and runs all available checks even when earlier checks fail.
Xenon checks the absolute C, module B, and average A complexity thresholds. Existing
lint, typing, security, dependency, or test findings can make the audit fail.
CI also runs this audit as a non-blocking job and separately reports Radon maintainability without imposing a threshold.
