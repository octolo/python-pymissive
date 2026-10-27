# pymissive

Lightweight, framework-agnostic Python library for multi-channel message sending: email, SMS, WhatsApp, registered electronic mail (registered letter) and team messaging.

## Overview

**pymissive** exposes one provider interface per channel, so the calling code
stays the same whichever service actually delivers the message. It is the base
of **django-pymissive** and can be used on its own in any Python project.

The PyPI name is `pymissive`; the directory holding it in this monorepo is
`python-pymissive/`.

### Main features

- 🔌 **8 providers**, all sharing the same service names
- 📧 **Email**: Brevo, Scaleway
- 📱 **SMS**: Brevo, SMSPartner
- 💬 **WhatsApp**: Brevo
- 📮 **Postal letters**: Maileva (simple letter and electronic registered letter)
- 👥 **Team messaging**: Slack, Microsoft Teams, Discord
- ✋ **Hand delivery**: tracks an in-person hand-over, no external API
- 🏗️ **Modular architecture** based on ProviderKit
- ✅ **Framework-agnostic**: usable with or without a framework
- 🎯 **Type hints** throughout

## Installation

```bash
pip install pymissive
```

`requests` is a base dependency, so Maileva and SMSPartner work as installed.
Providers needing another SDK have their own extra. Those imports are lazy, so a
missing extra only disables that one provider:

```bash
pip install pymissive[brevo]     # brevo-python
pip install pymissive[scaleway]  # boto3
pip install pymissive[discord]   # discord.py
```

## Quick usage

```python
from pymissive.providers.slack import SlackProvider

provider = SlackProvider(config={
    "SLACK_BOT_TOKEN": "xoxb-your-token",
    "SLACK_CHANNEL_ID": "C0123456789",
})

result = provider.send_branded(
    subject="Deployment finished",
    body_text="Version 1.3.15 is live.",
)
```

Each key in `config_keys` is read from `config` first, then from the
environment, so exporting `SLACK_BOT_TOKEN` instead works the same way.

## Available providers

Services are named `<verb>_<missive_type>` — `send_email`, `retrieve_registered_letter`,
`handle_webhook_sms`, and so on. `branded` is the missive type used by the team
messaging platforms, where the sender identity is the bot rather than an address.

| Provider | Class | Missive types | Extra |
|---|---|---|---|
| Brevo | `BrevoAPIProvider` | `email`, `sms`, `branded` (including WhatsApp) | `[brevo]` |
| Scaleway | `ScalewayProvider` | `email`, `branded` | `[scaleway]` |
| Maileva | `MailevaProvider` | `letter`, `registered_letter`, `branded` | — |
| SMSPartner | `PartnerProvider` | `sms`, `branded` | — |
| Slack | `SlackProvider` | `branded` | — |
| Microsoft Teams | `TeamsProvider` | `branded` | — |
| Discord | `DiscordProvider` | `branded` | `[discord]` |
| Hand delivery | `HandDeliveryProvider` | `hand_delivery`, `branded` | — |

### Planned providers

The following providers are roadmap items only. They are not shipped as Python
modules and cannot be imported:

- **Email**: Django email backend, SMTP, SendGrid, Mailgun, Amazon SES
- **SMS**: Twilio, Vonage
- **Instant messaging**: Telegram, Signal, Messenger
- **Postal and registered delivery**: La Poste, AR24, Certeurope
- **Push notifications**: Firebase Cloud Messaging (FCM), Apple Push
  Notification service (APNs), in-app notifications

## Architecture

Providers are plain classes discovered by **ProviderKit**:

```python
from pathlib import Path

import pymissive.providers as providers_package
from providerkit import autodiscover_providers

classes = autodiscover_providers(
    Path(list(providers_package.__path__)[0]),
    base_module="pymissive.providers",
    exclude_files=["base"],
)
# {'brevo': BrevoAPIProvider, 'maileva': MailevaProvider, ...}
```

Beware of `ProviderBase.services`: it lists the whole catalogue of service names,
not the subset a given provider implements. To know whether a provider really
supports something, look for the method itself:

```python
provider = classes["brevo"]()
can_send_sms = hasattr(provider, "send_sms")
```

## Documentation

For more details, see the documentation in the `docs/` folder:

- `docs/purpose.md` - Project goals and architecture
- `docs/structure.md` - Module structure and organization
- `docs/development.md` - Development guidelines
- `docs/AI.md` - Contract for AI assistants

## Development

```bash
pip install -e ".[test]"

# Tests and lint
python -m pytest
ruff check src
```

The core package has its own provider, CLI, webhook and packaging tests under
`tests/`. Django integration tests live separately in `django-pymissive/tests/`.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
