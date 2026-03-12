# Django Missive

🚀 A complete Django library for managing **multi-channel missive sending**: email, SMS, WhatsApp, postal mail, and in-app notifications.

## ✨ Features

### Main features

- 📧 **Multi-channel**: 14 supported types (Email, SMS, WhatsApp, Telegram, Signal, Messenger, RCS, Postal mail, LRE, Voice calls, Push notifications, Slack, Teams)
- 🔌 **15+ integrated providers**: SendGrid, Mailgun, Twilio, La Poste, Telegram, FCM, APN, Slack, Teams, etc.
- 📎 **Flexible attachments**: Local files OR external URLs (S3, Google Drive)
- 🔔 **Unified webhooks**: Single endpoint `/missive/webhook/{provider}/`
- 📊 **Full tracking**: History, statuses, events
- 🎯 **Recipient model**: Centralized contact details (email, phone, address)
- 🔍 **Built-in validation**: Pre-send risk checks
- 👨‍💼 **Complete Django admin**: Management interface with validation actions
- 🔗 **GenericForeignKey**: Flexible link with your business models
- 📝 **Reusable templates**: Create missive templates
- 📊 **Advanced monitoring**: Services, credits, SLA and health check per provider
- 🔄 **Automatic fallback**: Switch to backup provider on failure

### Technical architecture

- ✅ Compatible with Django 3.2+ and Python 3.9+
- ✅ Modular structure with mixins (providers/base/)
- ✅ Comprehensive unit tests (8/8 ✅)
- ✅ Exhaustive documentation (16 .md files)
- ✅ CI/CD with GitHub Actions
- ✅ Type hints and mypy
- ✅ Code formatted with Black + isort

## Installation

### 🔧 Development mode (local project)

```bash
# Core only (Django + validation)
pip install -r requirements.txt

# Development (tests, linters)
pip install -r requirements-dev.txt

# All providers
pip install -r requirements-all.txt
```

### 📦 Production mode (future - after PyPI publication)

```bash
# Base installation
pip install django-missive

# With specific providers
pip install django-missive[email]        # Email (SendGrid, Mailgun, SES)
pip install django-missive[sms]          # SMS & Voice (Twilio, Vonage)
pip install django-missive[messaging]    # Telegram, Signal, Messenger
pip install django-missive[push]         # Push notifications (FCM, APN)
pip install django-missive[professional] # Slack, Teams
pip install django-missive[postal]       # Postal, LRE
pip install django-missive[all]          # All providers
```

## Quick Start

1. Add `django_pymissive` to your `INSTALLED_APPS` in `settings.py`:

```python
INSTALLED_APPS = [
    ...
    'django_pymissive',
]
```

2. Run migrations:

```bash
python manage.py migrate django_pymissive
```

3. Include the URLconf in your project `urls.py`:

```python
from django.urls import path, include

urlpatterns = [
    ...
    path('missive/', include('django_pymissive.urls')),  # Webhooks
]
```

This will create the following URLs:
- `/missive/webhook/{provider}/` - Unified webhook for all providers

4. Configure providers in `settings.py`:

```python
# Django Missive configuration
MISSIVE_PROVIDERS = {
    # Providers by missive type (uses python-missive)
    'EMAIL': {
        'backend': 'pymissive.providers.sendgrid.SendGridProvider',
        'config': {
            'SENDGRID_API_KEY': os.getenv('SENDGRID_API_KEY'),
        }
    },
    'SMS': {
        'backend': 'pymissive.providers.twilio.TwilioProvider',
        'config': {
            'TWILIO_ACCOUNT_SID': os.getenv('TWILIO_ACCOUNT_SID'),
            'TWILIO_AUTH_TOKEN': os.getenv('TWILIO_AUTH_TOKEN'),
            'TWILIO_PHONE_NUMBER': '+33123456789',
        }
    },
    'POSTAL': {
        'backend': 'pymissive.providers.laposte.LaPosteProvider',
        'config': {
            'LAPOSTE_API_KEY': os.getenv('LAPOSTE_API_KEY'),
        }
    },
}

# Default email
DEFAULT_FROM_EMAIL = 'noreply@example.com'
```

## 🚀 Quick usage

### Send an email

```python
from django_pymissive.models import Missive, MissiveType, MissiveEventType

# Create an email missive
missive = Missive.objects.create(
    sender=request.user,
    missive_type=MissiveType.EMAIL,
    recipient_email="client@example.com",
    subject="Order confirmed",
    body="<p>Your order #123 is confirmed</p>",
    body_text="Your order #123 is confirmed",
    status=MissiveEventType.PENDING,
)

# Sending can be handled via async tasks or manually
```

### Use the model to create missives

```python
from django_pymissive.models import Missive, MissiveType, MissiveEventType

# Create a recipient with all contact details
missive = Missive.objects.create(
    sender=request.user,
    missive_type=MissiveType.EMAIL,
    recipient_first_name="Jean",
    recipient_last_name="Dupont",
    recipient_email="jean@acme.com",
    recipient_phone="+33600000000",
    recipient_address_line1="123 Rue de la Paix",
    recipient_postal_code="75001",
    recipient_city="Paris",
    recipient_country="FR",
    subject="Welcome",
    body="<p>Hello Jean, welcome!</p>",
    status=MissiveEventType.PENDING,
)

# Create an SMS with the same contact details
sms = Missive.objects.create(
    sender=request.user,
    missive_type=MissiveType.SMS,
    recipient_phone="+33600000000",
    body="Your verification code: 123456",
    status=MissiveEventType.PENDING,
)
```

### Provider monitoring (via python-missive)

```python
from pymissive.providers.sendgrid import SendGridProvider

# Configure and verify the provider
provider = SendGridProvider(config={
    'SENDGRID_API_KEY': 'your-api-key'
})

# Verify configuration
is_configured = provider.is_configured()
print(f"Provider configured: {is_configured}")

# Send a test email
result = provider.send_email(
    from_email='sender@example.com',
    to_email='recipient@example.com',
    subject='Test',
    body='<p>Test message</p>'
)
```

### Validate and send

```python
from django_pymissive.models import Missive, MissiveEventType

# Retrieve a missive
missive = Missive.objects.get(id=123)

# Check it is ready to be sent
if missive.status == MissiveEventType.PENDING:
    # Mark as sent (actual sending is done via the configured provider)
    missive.status = MissiveEventType.SENT
    missive.save()
```

## Development

### Quick Start

This project includes `service.py` - a cross-platform development tool that works on **all operating systems**.

```bash
# Setup development environment
python service.py dev install-dev

# Run tests
python service.py dev test

# Format code
python service.py dev format

# Build package
python service.py dev build
```

**Linux/macOS users** can make it executable:
```bash
chmod +x service.py
./service.py dev install-dev
./service.py dev test
```

### Available Commands

**Development:**
- `python service.py dev venv` - Create virtual environment
- `python service.py dev install` - Install in production mode
- `python service.py dev install-dev` - Install in development mode

**Testing:**
- `python service.py dev test` - Run tests with pytest
- `python service.py dev test-verbose` - Run tests with verbose output
- `python service.py dev coverage` - Run tests with coverage report

**Code Quality:**
- `python service.py quality lint` - Run linters (flake8, mypy)
- `python service.py quality format` - Format code (black, isort)
- `python service.py quality check` - Run all checks (lint + format check)

**Building:**
- `python service.py dev build` - Build wheel and source distribution
- `python service.py dev clean` - Remove all build artifacts
- `python service.py dev clean-test` - Remove test artifacts (htmlcov, .coverage, etc.)

**Publishing:**
- `python service.py dev upload-test` - Upload to TestPyPI
- `python service.py dev upload` - Upload to PyPI
- `python service.py dev release` - Full release workflow

**Utilities:**
- `python service.py dev show-version` - Show current version
- `python service.py dev venv-clean` - Recreate virtual environment

Run `python service.py dev help` to see all available commands.

### Django Development Server

Test the library with a Django development server:

```bash
# Run migrations and create superuser (admin/admin)
python service.py dev migrate

# Start development server
python service.py dev runserver
```

Access the admin interface at http://127.0.0.1:8000/admin/ (login: admin/admin)

See [docs/development.md](docs/development.md) for detailed development guide (if available).

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

### 0.1.0 (Initial Release)

- Initial release
- Basic functionality

## Support

If you encounter any issues or have questions, please file an issue on the [GitHub issue tracker](https://github.com/yourusername/django-missive/issues).

