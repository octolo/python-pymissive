# python-missive

Lightweight, framework-agnostic Python library for multi-channel message sending (email, SMS, push notifications, postal mail, etc.).

## Overview

**python-missive** is a framework-agnostic Python library that provides unified providers for multi-channel message sending. It serves as the base for **django-missive** and can be used independently in any Python project.

### Main features

- 🔌 **15+ integrated providers** for different communication channels
- 📧 **Email**: SendGrid, Mailgun, SES, Brevo, SMTP, Django Email
- 📱 **SMS & Voice**: Twilio, Vonage, SMSPartner
- 💬 **Messaging**: Telegram, Signal, Messenger, Slack, Teams
- 📮 **Postal & LRE**: La Poste, Maileva, AR24, Certeurope
- 🔔 **Push notifications**: FCM (Firebase), APN (Apple), In-App
- 🏗️ **Modular architecture** based on ProviderKit
- ✅ **Framework-agnostic**: usable with or without a framework
- 🎯 **Complete type hints** and documentation

## Installation

```bash
# Basic installation
pip install python-missive

# With dependencies for specific providers
pip install python-missive[email]      # Email providers
pip install python-missive[sms]        # SMS and voice
pip install python-missive[messaging]  # Telegram, Signal, etc.
pip install python-missive[push]       # FCM, APN
pip install python-missive[postal]     # Postal mail
pip install python-missive[all]        # All providers
```

## Quick usage

```python
from pymissive.providers.sendgrid import SendGridProvider

# Configure the provider
provider = SendGridProvider(config={
    'SENDGRID_API_KEY': 'your-api-key'
})

# Send an email
result = provider.send_email(
    from_email='sender@example.com',
    to_email='recipient@example.com',
    subject='Hello',
    body='<p>Message content</p>'
)
```

## Available providers

### Email
- `DjangoEmailProvider` - Uses Django email backend
- `SMTPProvider` - Generic SMTP
- `SendGridProvider` - SendGrid API
- `MailgunProvider` - Mailgun API
- `SESProvider` - Amazon SES
- `BrevoProvider` - Brevo (ex-Sendinblue)
- `ScalewayProvider` - Scaleway Transactional Email

### SMS & Voice
- `TwilioProvider` - Twilio SMS and voice calls
- `VonageProvider` - Vonage (ex-Nexmo)
- `SMSPartnerProvider` - SMSPartner

### Messaging
- `TelegramProvider` - Telegram Bot API
- `SignalProvider` - Signal Messenger
- `MessengerProvider` - Facebook Messenger
- `SlackProvider` - Slack
- `TeamsProvider` - Microsoft Teams

### Postal mail & LRE
- `LaPosteProvider` - La Poste (physical mail)
- `MailevaProvider` - Maileva
- `AR24Provider` - AR24 (LRE)
- `CerteuropeProvider` - Certeurope

### Push notifications
- `FCMProvider` - Firebase Cloud Messaging
- `APNProvider` - Apple Push Notification
- `InAppNotificationProvider` - In-app notifications

## Architecture

The library uses **ProviderKit** for provider management:

```python
from pymissive.providers import get_missive_providers

# Discover all available providers
providers = get_missive_providers()

# Filter by service type
email_providers = [p for p in providers if 'email' in p.services]
```

## Documentation

For more details, see the documentation in the `docs/` folder:

- `docs/purpose.md` - Project goals and architecture
- `docs/structure.md` - Module structure and organization
- `docs/development.md` - Development guidelines
- `docs/AI.md` - Contract for AI assistants

## Development

```bash
# Create virtual environment
python service.py dev venv

# Install in development mode
python service.py dev install-dev

# Run tests
python service.py dev test

# Format code
python service.py dev format

# Run all quality checks
python service.py quality check
```

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
