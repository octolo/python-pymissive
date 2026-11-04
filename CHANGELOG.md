# Changelog

## 1.8.5 — 2026-11-04

### Compatibility

- `django-pymissive` now requires `pymissive>=1.8.5,<2`.

### Changes

- After a local `submitted` event, each recipient and the missive recompute
  their status. Recipients no longer stay `draft` until a webhook or a status
  retrieval.

## 1.8.4 — 2026-11-04

### Compatibility

- `django-pymissive` now requires `pymissive>=1.8.4,<2`.

### Changes

- The fake provider can refuse a send at random (`FAILURE_RATE`, default `0.1`)
  before any webhook. A refused send returns no `external_id`, so the missive
  is recorded as an error. Set `FAKE_FAILURE_RATE` or `failure_rate` to change
  the chance; `0` disables it.

## 1.8.3 — 2026-11-04

### Compatibility

- `django-pymissive` now requires `pymissive>=1.8.3,<2`.

### Changes

- A crashed campaign run can be force-released from the scheduler admin, a task
  backend, or `manage.py force_release_run`. The run is ended and unaccepted
  `PROCESSING` missives return to `DRAFT`. Missives that already have an
  `external_id` stay as they are.

## 1.8.2 — 2026-11-04

### Compatibility

- `django-pymissive` now requires `pymissive>=1.8.2,<2`.
- Apply migration `0035_missive_send_via_task`.

### Changes

- A missive can set `send_via_task` to queue its send on the campaign task
  backend. `dispatch_send` sends immediately when the flag is off and enqueues
  `send_missive` when it is on. Admin send, duplication, campaign target
  sends, and the `send_missive` shortcut use `dispatch_send`.
- A campaign exposes `count_target_<type>` for the stored contact values on
  active targets of each missive type. `count_target` is the sum of those
  counters. `CampaignTargetQuerySet.with_target_count()` annotates the same
  count on each target.

## 1.8.1 — 2026-10-29

### Compatibility

- `django-pymissive` now requires `pymissive>=1.8.1,<2`.

### Changes

- A campaign exposes `count_target_pending_<type>` for each missive type.
  `count_target_pending` is the sum of those counters.

## 1.8.0 — 2026-10-29

### Compatibility

- `django-pymissive` now requires `pymissive>=1.8.0,<2`.
- Apply migration `0034_missive_body_rich_snapshot_html_and_more`.

### Changes

- Applications can register target models for deletion cleanup. Pending rows
  are removed immediately while rows linked to a missive remain as history;
  a grouped helper handles large queryset deletions efficiently.

## 1.7.0 — 2026-10-29

### Compatibility

- `django-pymissive` now requires `pymissive>=1.7.0,<2`.
- The new optional HTML snapshot fields need a migration.

### Changes

- Each rich-text field on a missive or a campaign has an optional HTML
  snapshot. The matching read-more property keeps the opening HTML balanced.
  `PYMISSIVE_SNAPSHOT_HTML_READ_MORE_LENGTH` sets its length and defaults to
  500 characters.
- A campaign target can be previewed before it has a missive. That page is
  limited to staff with permission to view the target.

## 1.6.0 — 2026-10-28

### Compatibility

- `django-pymissive` now requires `pymissive>=1.6.0,<2`.
- Apply migration `0033_missivesetting_campaignrecipienttarget`.
- The `create` and `update` provider actions are gone. Hand delivery and
  Maileva no longer expose `create_*`, `update_*`, or
  `prepare_registered_letter`. Sending still goes through `send`.

### Changes

- A campaign target can store the checked contacts for each role (recipient,
  cc, bcc, notification) on `CampaignRecipientTarget`. Drafts use those
  lists. With no row for a role, the channel's own contacts stay recipients.
- `PYMISSIVE_RECIPIENT_ALLOWED` lists the contacts that keep their real
  address. Anyone else is rewritten with `PYMISSIVE_OVERRIDE_RECIPIENT`, or
  the send is refused when that override is empty. The list may be a dotted
  path, including `staff_emails`, `admin_emails`, and `admin_staff_emails`.
- `PYMISSIVE_DRY_RUN="allowed"` calls the provider only when every recipient
  is on that allow-list. `True` still keeps every send local.
- `PYMISSIVE_FORCE_FAKE_PROVIDER` routes every missive to the local fake
  provider, which accepts the send even when `PYMISSIVE_ALLOW_FAKE_PROVIDER`
  is off.
- The configuration admin lists every setting this package reads, with its
  default and the value currently configured.
- Scheduler progress animations cover more of the send flow.

## 1.5.0 — 2026-10-26

### Compatibility

- Python 3.11 or newer is now required.
- Django 5.0 through 5.2 is supported.
- `django-pymissive` now requires `pymissive>=1.5.0,<2`.

### Changes

- Brevo and Maileva implementations are organized as provider packages while
  preserving `pymissive.providers.brevo` and
  `pymissive.providers.maileva` imports.
- Campaign selection, scheduler tracking and cancellation handling were
  strengthened.
- Import allowlists and Teams webhook URL validation were hardened.
- Both distributions now include typing markers, and CI verifies Mypy and
  wheel package data.

Applications still running Python 3.10 must upgrade Python before installing
this release.
