## Project Structure

python-missive follows a standard Python package structure with a provider-based architecture using ProviderKit for provider management.

### General Structure

```
python-missive/
├── src/
│   └── pymissive/            # Main package directory
│       ├── __init__.py       # Package exports
│       ├── providers/        # Message provider implementations
│       │   ├── __init__.py   # Base provider classes
│       │   ├── base/         # Base provider mixins
│       │   │   ├── email.py           # Email base provider
│       │   │   ├── sms.py             # SMS base provider
│       │   │   ├── notification.py    # Push notification base
│       │   │   ├── postal.py          # Postal mail base
│       │   │   ├── voice_call.py      # Voice call base
│       │   │   └── branded.py         # Branded messaging base
│       │   ├── django_email.py        # Django email backend
│       │   ├── smtp.py                # SMTP provider
│       │   ├── sendgrid.py            # SendGrid
│       │   ├── mailgun.py             # Mailgun
│       │   ├── ses.py                 # Amazon SES
│       │   ├── brevo.py               # Brevo
│       │   ├── scaleway.py            # Scaleway
│       │   ├── twilio.py              # Twilio SMS/Voice
│       │   ├── vonage.py              # Vonage
│       │   ├── smspartner.py          # SMSPartner
│       │   ├── telegram.py            # Telegram
│       │   ├── signal.py              # Signal
│       │   ├── messenger.py           # Facebook Messenger
│       │   ├── slack.py               # Slack
│       │   ├── teams.py               # Microsoft Teams
│       │   ├── fcm.py                 # Firebase Cloud Messaging
│       │   ├── apn.py                 # Apple Push Notification
│       │   ├── notification.py        # In-app notifications
│       │   ├── laposte.py             # La Poste
│       │   ├── maileva.py             # Maileva
│       │   ├── ar24.py                # AR24
│       │   └── certeurope.py          # Certeurope
│       ├── helpers.py        # Helper functions
│       ├── config.py         # Configuration utilities
│       ├── cli.py            # CLI interface
│       └── __main__.py       # Entry point for package execution
├── tests/                    # Test suite
│   └── ...
├── docs/                     # Documentation
│   └── ...
├── service.py                # Main service entry point script
├── pyproject.toml            # Project configuration
└── ...
```

### Module Organization Principles

- **Single Responsibility**: Each module should have a clear, single purpose
- **Separation of Concerns**: Keep different concerns in separate modules
- **Provider-Based Architecture**: Providers inherit from ProviderKit's ProviderBase
- **Clear Exports**: Use `__init__.py` to define public API
- **Logical Grouping**: Organize related functionality together

### Provider Organization

The `providers/` directory contains message provider implementations:

- **`__init__.py`**: Imports and exports all provider classes
- **`base/`**: Base provider classes and mixins for different message types
  - `email.py`: Base class for email providers
  - `sms.py`: Base class for SMS providers
  - `notification.py`: Base class for push notification providers
  - `postal.py`: Base class for postal mail providers
  - `voice_call.py`: Base class for voice call providers
  - `branded.py`: Base class for branded messaging (Slack, Teams, etc.)
- Each provider file (e.g., `sendgrid.py`, `twilio.py`) implements a specific messaging service
- All providers inherit from appropriate base classes which extend `ProviderBase` from ProviderKit

### Available Providers by Category

**Email providers**:
- DjangoEmailProvider (Django email backend)
- SMTPProvider (generic SMTP)
- SendGridProvider
- MailgunProvider
- SESProvider (Amazon SES)
- BrevoProvider
- ScalewayProvider

**SMS & Voice providers**:
- TwilioProvider
- VonageProvider
- SMSPartnerProvider

**Instant messaging providers**:
- TelegramProvider
- SignalProvider
- MessengerProvider
- SlackProvider
- TeamsProvider

**Postal & LRE providers**:
- LaPosteProvider
- MailevaProvider
- AR24Provider
- CerteuropeProvider

**Push notification providers**:
- FCMProvider (Firebase)
- APNProvider (Apple)
- InAppNotificationProvider

### Helper Functions

The `helpers.py` module provides:
- `get_missive_providers()`: Get available missive providers
- Utility functions for provider management and discovery

### Package Exports

The public API is defined in `src/pymissive/__init__.py`:
- Provider classes
- Helper functions
- Configuration utilities

### ProviderKit Integration

python-missive uses ProviderKit for provider management:
- Providers inherit from `ProviderBase` via category-specific base classes
- Uses ProviderKit's helper functions for provider discovery and management
- Providers can be loaded from configuration or directory scanning

