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

- ✅ Compatible with Django 3.2+ and Python 3.10+
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

# Applied on save when sender fields are empty.
# Campaigns receive every provided key. Missives only receive the fields
# for their type, and only when the campaign does not already have a sender.
PYMISSIVE_DEFAULT_SENDER = {
    "name": "Octolo",
    "email": "contact@octolo.tech",
    "phone": "+33123456789",
    "address": {
        "organization": "Octolo",
        "address_line1": "1 rue de la Paix",
        "postal_code": "75002",
        "city": "Paris",
        "country": "France",
    },
}
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

## Counters and annotations

### Supports rather than types

A support groups the missive types of one physical channel
(`pymissive.config.GENERIC_SUPPORT`): `address` covers `lre` and
`hand_delivery`, `email` covers `email`, `email_marketing` and `ere`, and so on.
Plain mail is not a type of its own — it is `lre` without
`acknowledgement_of_receipt`, which is what providers key the mode on. Count per
support instead of listing types by hand:

```python
from pymissive.config import missive_types_for_support, normalize_support

normalize_support("courrier")        # 'address'
normalize_support("postal")          # 'address' (legacy synonym)
missive_types_for_support("address") # ['lre', 'hand_delivery']
```

Counters are opt-in on both sides, under the same name — `with_counts()` on the
campaign as on its runs, so a template can switch between the two:

```python
MissiveCampaign.objects.with_counts()
# count_missive, count_sent / count_pending / count_error,
# count_support_<support> (+ _sent, _error), count_missive_<status>,
# count_type_<type>, count_thread_<type>,
# count_recipient (+ _<status>), count_event, count_related_object,
# count_attachment, pct_recipient_<status>
```

`MissiveCampaign.objects` itself annotates only what costs no `GROUP BY`:
`last_send_date` and `last_ended_at` (subqueries), `has_sent_missives` and
`has_open_run` (booleans). A `.get(pk=…)` stays a primary key lookup — asking for
the counters everywhere made it four times slower, and the recipient and event
joins multiply each other on top of that (5 000 missives with 2 recipients and 8
events each is 80 000 intermediate rows for every `COUNT(DISTINCT)`).

Reading a counter on a campaign nobody annotated still works: the whole set is
fetched in one query and cached on the instance. Convenient for a detail page,
ruinous for a list — measured on 100 campaigns, reading three counters costs 11 ms
annotated and 500 ms through the fallback. Call `with_counts()` as soon as you
iterate.

Name the ones you display: `with_counts("count_missive", "pct_recipient_success")`
annotates those two (plus the counters a percentage divides) instead of all sixty.
They share one scan of the joined rows, so the cost follows the number of
aggregates — naming the handful the admin changelist shows measured 2,5 times
faster than taking every counter along. An unknown name raises `ValueError`
rather than quietly falling back to one query per row.

`count_sent` / `count_pending` / `count_error` and `count_support_*` cover
`thread_type=MISSIVE` only, on a campaign as on a run,
since the `HISTORY` rows a resend leaves behind are not new sends. They say where
the payload stands *now*, so they follow the missives: the total of a finished run
drops when a newer run takes over a draft it never sent, or when a retry archives
one of its attempts.

The historical counters keep the archived threads instead — `count_missive` and
`count_type_<type>` on the campaign, `count_missive_<status>` and
`count_thread_<type>` on both — which is what keeps the failures of a finished
run readable once a later run has retried them (`run.history_count` says how many
of its attempts were archived that way). Per-status counts may therefore sum
above `count_total`.

Never filter on `status="draft"` to tell sent from pending: databases predating
the `draft` default hold an empty status too. Use the shared predicates:

```python
from django_pymissive.models.choices import (
    error_missive_q, missive_type_filter, pending_missive_q, sent_missive_q,
)

Missive.objects.filter(sent_missive_q())
campaign.to_missive.filter(pending_missive_q())
Missive.objects.filter(**missive_type_filter("courrier"))
```

### Annotating your own models

Missives point at your models through `MissiveRelatedObject`, campaigns through
`CampaignRelatedObject`. Mix `MissiveRelatedQuerySetMixin` into **your**
queryset to annotate them:

```python
from django_pymissive.managers.related_object import MissiveRelatedQuerySetMixin

class ParticipantQuerySet(MissiveRelatedQuerySetMixin, models.QuerySet):
    pass

class Participant(models.Model):
    objects = ParticipantQuerySet.as_manager()
```

```python
qs = (
    Participant.objects
    # {"uid", "status", "missive_type", "sent_at"} of the newest match, or {}
    .with_last_missive(campaign=campaign, support="email")
    # one integer per counter you name
    .with_missive_count(name="email_count", support="email")
    .with_missive_count(name="sent_count", sent=True)
    # both counters in a single scan: {"missives": N, "events": E}
    .with_missive_counts(prefix="totals")
)
```

Every method takes the same filters — `campaign`, `support`, `missive_type`,
`thread_type`, `metadata`, `sent` — described on
`django_pymissive.managers.related_object.missive_link_q`. The `prefix` /
`name` arguments above name the annotation; `prefix` is refused as a filter,
since these methods own the lookup path to the missive. For an object linked
to a whole campaign (a meeting, a company) rather than to individual missives,
`with_campaign_missive_count()` walks the campaign link instead.

Outside of an annotation, `missive_related_queryset(instance, **filters)` returns
the link rows themselves, newest missive first.

Each annotation is a correlated subquery, re-evaluated for every row it
annotates: the right trade on a paginated page, the wrong one on a full export.
For a batch, `missive_summaries_by_object()` answers in two grouped queries
whatever its size — the link rows, then the events of their missives:

```python
from django_pymissive.managers.related_object import (
    missive_summaries_by_object, object_id_value,
)

summaries = missive_summaries_by_object(Participant, [p.pk for p in participants])
summaries[object_id_value(participant.pk)]
# {"missives": 2, "events": 5, "last": {"uid", "status", "missive_type", "sent_at"}}
```

It takes the same filters, and the values reuse the names the annotations
produce, so a template can read either source. Every object asked for gets an
entry, zeroed with an empty `last` when it has no matching missive. On 1 000
objects carrying three missives each, the five annotations above take ~1 000 ms
where the batch pass takes ~22 ms.

Your model's primary key can be an integer or a UUID: `object_id` is a text
column, holding the pk without its dashes (`uuid.hex`), because PostgreSQL
renders a UUID dashed where SQLite stores 32 hex characters. Go through
`missive_related_queryset()` or the mixin rather than filtering `object_id`
yourself; if you must, normalise with
`django_pymissive.managers.related_object.object_id_value(pk)`.

### Send dates and recipient values

`Missive` has no `sent_at` column and `updated_at` is bumped by any later save,
so neither dates a send. The `sent_at` annotation (on by default) reports the
oldest event proving the missive left, and is `NULL` until then.

To render recipients for a page of missives without a query per row:

```python
MissiveRecipient.objects.targets_by_missive(missive_ids, support="email")
# {"<missive_id>": ["alice@example.com", …]}
```

Values keep their natural type — a string for e-mail, phone and notification id,
the address dict for postal supports — and fall back to the recipient name when
no contact value is on file.

### Before and after a send

```python
campaign.send_preview_payload()  # {"total", "by_support", "by_type"} — what a send would push out
campaign.progress_payload()      # what already went out, per type, plus the runs
campaign.is_processing           # flag set, or a run still open
campaign.can_remove              # nothing sent yet
```

Both payloads cover `thread_type=MISSIVE`, so their totals agree with
`count_sent` / `count_error` and stay below `count_missive`, which counts the
archived and conversation threads too.

The last two read the `has_open_run` / `has_sent_missives` annotations that
`MissiveCampaign.objects` adds, and fall back to one `EXISTS` each, memoised on
the instance. Iterate a list of campaigns through that manager rather than
through `Missive.objects.select_related("campaign")`, which cannot carry the
annotations: the fallback then costs two queries per campaign instead of none.

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

