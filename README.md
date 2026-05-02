# Missive

Monorepo containing **python-pymissive** (framework-agnostic Python library for multi-channel messaging) and **django-pymissive** (Django integration).

## Packages

### python-pymissive — `python-pymissive/`

Lightweight, framework-agnostic Python library for sending multi-channel missives: emails, SMS, push notifications, postal mail, and more. Built on ProviderKit.

- **15+ providers**: SendGrid, Mailgun, Twilio, La Poste, Telegram, FCM, APN, Slack, Teams, etc.
- **Modular architecture**: works with or without a framework
- **Multi-channel**: email, SMS, postal, messaging, push

📁 Details: [python-pymissive/README.md](python-pymissive/README.md) | Docs: [python-pymissive/docs/](python-pymissive/docs/)

### django-pymissive — `django-pymissive/`

Full Django integration for managing multi-channel missive delivery. Admin interface, models, unified webhooks, and delivery tracking.

- **Django admin interface**: manage missives with validation and preview
- **Unified webhooks**: `/missive/webhook/{provider}/`
- **Recipient model**: centralised contact management
- **Dependency**: requires python-pymissive

📁 Details: [django-pymissive/README.md](django-pymissive/README.md)

## Repository structure

```
missive/
├── python-pymissive/   # Core library
├── django-pymissive/   # Django integration
└── README.md
```

## Development

Each package has its own `service.py`:

```bash
# Inside python-pymissive/ or django-pymissive/
./service.py dev install-dev
./service.py dev test
./service.py quality lint
```

## Licence

MIT
