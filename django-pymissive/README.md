# django-pymissive

🚀 A Django library for managing **multi-channel missive sending**: email, SMS, registered electronic mail (LRE), hand delivery and team messaging.

## ✨ Features

### Main features

- 📧 **Multi-channel**: 11 declared missive types; `email`, `sms`, `lre`, `hand_delivery` and `branded` have a working provider today
- 🔌 **8 providers** through `pymissive`: Brevo, Scaleway, Maileva, SMSPartner, Slack, Microsoft Teams, Discord, hand delivery
- 📎 **Flexible attachments**: local files OR external URLs (S3, Google Drive)
- 🔔 **Unified webhooks**: one endpoint, `/missive/webhook/<provider>/<missive_type>/`
- 📊 **Full tracking**: history, statuses, events
- 🎯 **Recipient model**: centralized contact details (email, phone, address)
- 🔍 **Built-in validation**: pre-send checks
- 👨‍💼 **Complete Django admin**: management interface with validation actions
- 🔗 **GenericForeignKey**: flexible link with your business models
- 📢 **Campaigns and scheduling**: shared content, scheduled runs, progress tracking

### Technical architecture

- ✅ Django 5.0+ and Python 3.10+ (CI covers Django 5.0, 5.1 and 5.2)
- ✅ Modular structure with mixins (`acknowledgement`, `attachments`, `branded` in `pymissive`)
- ✅ ~500 tests under `tests/`
- ✅ CI/CD with GitHub Actions
- ✅ Linted with ruff

## Installation

```bash
pip install django-pymissive
```

Provider SDKs live in `pymissive`, next to the code importing them, and are
re-exported here as extras. The imports are lazy, so a missing extra only
disables that provider:

```bash
pip install django-pymissive[brevo]     # Brevo: email, SMS, WhatsApp
pip install django-pymissive[scaleway]  # Scaleway: email
pip install django-pymissive[pdf]       # PDF rendering: weasyprint, pypdf, reportlab
```

Maileva, SMSPartner and hand delivery need nothing beyond the base install.

### Working on the library itself

`django-pymissive` pins a matching `pymissive` version, so install the local
core first or pip will try to fetch an unreleased version from PyPI:

```bash
pip install -e ../python-pymissive
pip install -e ".[test]"   # includes [pdf]: pypdf, reportlab, weasyprint
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
- `/missive/webhook/<provider>/<missive_type>/` - Unified webhook, e.g.
  `/missive/webhook/brevo/email/`. Both segments are required: the provider
  name selects the credentials, the missive type selects the
  `handle_webhook_<missive_type>` normalizer.

4. Configure providers in `settings.py`:

Credentials are keyed by provider name in `PROVIDERKIT_PROVIDERS_CONFIG`, using
each provider's own `config_keys`. A provider whose keys are absent simply stays
unusable; it does not break the rest.

```python
PROVIDERKIT_PROVIDERS_CONFIG = {
    "brevo": {
        "EMAIL_API_KEY": os.getenv("BREVO_EMAIL_API_KEY"),
        "SMS_API_KEY": os.getenv("BREVO_SMS_API_KEY"),
    },
    "partner": {
        "SMS_API_KEY": os.getenv("PARTNER_SMS_API_KEY"),
    },
    "maileva": {
        "USERNAME": os.getenv("MAILEVA_USERNAME"),
        "PASSWORD": os.getenv("MAILEVA_PASSWORD"),
        "CLIENTID": os.getenv("MAILEVA_CLIENTID"),
        "SECRET": os.getenv("MAILEVA_SECRET"),
        "SANDBOX": True,
    },
}
```

`tests/settings.py` holds a complete, working example for every provider.

Which provider serves which missive type is chosen per `MissiveConfig` row in
the admin, not in the settings. `Missive.provider` overrides it case by case.

```python
# Default email
DEFAULT_FROM_EMAIL = 'noreply@example.com'

# Applied on save when sender fields are empty.
# Campaigns receive every provided key. Missives only receive the fields
# for their type, and only when the campaign does not already have a sender.
# Seconds without a scheduler heartbeat before a PROCESSING missive or an
# open run is treated as dead (worker crash / SIGKILL). Default 1800.
# PYMISSIVE_STALE_PROCESSING_SECONDS = 1800

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

Recipients are rows of their own, so `send_missive()` and its per-type
shortcuts create the missive, attach one recipient and send it in one call.

```python
from django_pymissive.shortcuts import send_email

missive = send_email(
    name="Jean Dupont",
    email="jean@acme.com",
    subject="Order confirmed",
    body_rich="<p>Your order #123 is confirmed</p>",
    body_text="Your order #123 is confirmed",
    sender_name="Octolo",
    sender_email="contact@octolo.tech",
)
```

### Send an SMS, or stage without sending

```python
from django_pymissive.shortcuts import send_missive, send_sms

send_sms(
    name="Jean Dupont",
    phone="+33600000000",
    body_text="Your verification code: 123456",
)

# and_send=False only creates the rows; call missive.send_missive() later.
draft = send_missive(
    missive_type="email",
    name="Jean Dupont",
    email="jean@acme.com",
    subject="Welcome",
    body_rich="<p>Hello Jean, welcome!</p>",
    and_send=False,
)
```

A `send_<type>()` shortcut exists for every registered missive type, and each
takes the same keyword arguments as `send_missive()` minus `missive_type`.

### Several recipients

```python
from django_pymissive.models import Missive, MissiveRecipientEmail, MissiveType

missive = Missive.objects.create(
    missive_type=MissiveType.EMAIL,
    subject="Newsletter",
    body_rich="<p>Hello!</p>",
    sender_name="Octolo",
    sender_email="contact@octolo.tech",
)
for email in ("a@acme.com", "b@acme.com"):
    MissiveRecipientEmail.objects.create(missive=missive, email=email)

missive.send_missive()
```
### Follow a missive

Status is never assigned by hand: it is derived from the latest event of each
recipient, which providers report through the webhook. The values are
`draft`, `processing`, `success`, `failed`, `partially_success`,
`partially_failed`, `error` and `cancelled`.

```python
from django_pymissive.models import Missive, MissiveStatus

missive = Missive.objects.get(pk=pk)

if missive.status == MissiveStatus.ERROR:
    print(missive.last_send_error())

# Per-recipient timeline
for event in missive.to_missiveevent.order_by("occurred_at"):
    print(event.occurred_at, event.event, event.recipient_id)
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

`Missive.objects` follows the same rule. A plain `.get(pk=…)` — and
`campaign.to_missive` / `scheduler.to_missive` — stay primary-key lookups.
`with_counts()` annotates recipient / event / attachment / billing counters,
`sent_at`, `last_event`, and the history / message thread sizes. The admin
changelist opts in; webhooks and `get_by_external_id` do not.

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
campaign.can_remove              # nothing past draft; enforced on delete
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

### Setup

```bash
pip install -e ../python-pymissive
pip install -e ".[test]"   # includes [pdf]: pypdf, reportlab, weasyprint
```

### Tests and checks

`manage.py` and the test suite run against `tests.settings`, the sandbox
project bundled with the library.

```bash
python manage.py check
python -m pytest

# Linting, from the repository root (same command as CI)
ruff check python-pymissive/src django-pymissive/src
```

### Django development server

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The admin is then at http://127.0.0.1:8000/admin/.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

If you encounter any issues or have questions, please file an issue on the [GitHub issue tracker](https://github.com/octolo/python-missive/issues).

