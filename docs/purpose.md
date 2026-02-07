## Project Purpose

**python-missive** is a Python library for multi-channel message delivery. It provides a unified interface to multiple messaging providers (email, SMS, push notifications, postal mail, etc.) using ProviderKit for provider management.

### Core Functionality

The library enables you to:

1. **Send messages across multiple channels** with various providers:
   - Email messaging (transactional and marketing)
   - SMS and voice calls
   - Instant messaging (Telegram, Signal, Messenger, Slack, Teams)
   - Push notifications (FCM, APN)
   - Postal mail and registered letters (LRE)

2. **Manage multiple providers** through ProviderKit:
   - Provider discovery and enumeration
   - Provider selection and fallback mechanisms
   - Configuration management per provider
   - Dependency validation (API keys, packages)

3. **Unified provider interface**:
   - Consistent API across all providers
   - Service-based architecture
   - Support for provider-specific features
   - Standardized configuration

### Architecture

The library uses a provider-based architecture built on ProviderKit:

- Each messaging service is implemented as a provider inheriting from base provider classes
- Base provider classes extend `ProviderBase` from ProviderKit
- Providers are organized in the `providers/` directory by category
- Common functionality is shared through base provider mixins
- Provider discovery and management is handled by ProviderKit

### Available Services

Providers implement services based on their capabilities:

- **Email providers**: `send_email`, `send_bulk_email`
- **SMS providers**: `send_sms`, `send_bulk_sms`
- **Voice providers**: `make_call`, `send_voice_message`
- **Messaging providers**: `send_message`, `send_media`
- **Push notification providers**: `send_notification`, `send_bulk_notification`
- **Postal providers**: `send_letter`, `send_registered_letter`

### Supported Providers

**Email providers**:
- Django Email (uses Django's email backend)
- SMTP (generic SMTP)
- SendGrid
- Mailgun
- Amazon SES
- Brevo (ex-Sendinblue)
- Scaleway

**SMS & Voice providers**:
- Twilio
- Vonage (ex-Nexmo)
- SMSPartner

**Instant messaging providers**:
- Telegram
- Signal
- Facebook Messenger
- Slack
- Microsoft Teams

**Postal & registered letter providers**:
- La Poste (French postal service)
- Maileva
- AR24 (registered electronic mail)
- Certeurope

**Push notification providers**:
- FCM (Firebase Cloud Messaging)
- APN (Apple Push Notification)
- In-App Notifications

### Use Cases

- Multi-channel messaging infrastructure
- Transactional emails and notifications
- SMS alerts and 2FA codes
- Push notifications for mobile apps
- Team communication (Slack, Teams)
- Postal mail for official documents
- Registered letters for legal compliance
- Multi-provider setup with automatic fallback
- Integration with Django applications (via django-missive)

