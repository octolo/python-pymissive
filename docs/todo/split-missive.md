# Split `Missive` — god object

Scope: `django-pymissive/src/django_pymissive/models/missive.py` (~1 760 lines).
This is **not a bug**. Nothing here double-sends, opens the webhook, or blocks
a deploy. It is architecture debt: the file does too many jobs, so every real
fix is slower and riskier.

This document is the plan.

---

## The problem

`Missive` should mostly be **the database row**: type, status, `external_id`,
links to campaign / recipients / attachments.

Today the same file is also:

| Role | Examples |
| --- | --- |
| Django schema | fields, `save`, defaults, managers |
| Campaign inheritance | `get_locally_or_campaign_value`, `apply_campaign_config`, `set_locally_ifnull` |
| Provider client | `call_provider_service`, send / retrieve / cancel / delete |
| State machine | `set_status`, `reclaim_stale_processing`, send transitions |
| Template pipeline | `*_compiled`, `apply_body_processors` |
| PDF generation | `body_to_pdf`, `generate_first_document`, `ensure_first_document` |
| Admin presentation | `mark_safe`, `show_attachments_linked`, `show_preview_browser` |
| URLs / tokens | `get_browser_preview_path`, `token_missive`, `get_webhook_url` |
| Serialization | `get_serialized_data`, `get_serialized_attachments` |
| Cloning | `duplicate_missive` + recipients / attachments / related objects |
| Validation | `can_send`, `check_email`, `check_registered_letter`, `check_letter`, … |

Local imports (`from ..views.preview`, `from ..events`, `from ..billings`,
…) exist to break cycles: everyone imports `Missive`, so loading the model
pulls in the views, which reload the model.

A status fix can break PDF, and the other way around. That is not a behaviour
defect; it is a maintenance cost.

---

## What stays on the model

This is the **row**'s job:

- fields and `save` (defaults only on a full write, not on `update_fields`)
- campaign inheritance
- `set_status` and the guards (`CANCELLED` is terminal, no return to `DRAFT`)
- `can_send` / `check_*` validations
- data properties (`sender`, `recipients`, `is_postal_like` once extracted
  from `views.preview`)

---

## What we extract — order

No big-bang. One package = one PR; existing tests must pass. Current methods
can stay for a while as **one-line façades** that delegate, so admin and
`missive.send_missive()` callers do not break.

### 1. Presentation (simplest, no business risk)

`show_attachments_linked`, `show_attachments_linked_text`,
`show_preview_browser`, `show_preview_browser_text`, `mark_safe` templates.

That does not belong on the SQL row. Destination: admin, or
`django_pymissive/presenters/missive.py`. The model keeps data and URLs, not
HTML.

### 2. Break circular imports

Today `missive.py` imports `views.preview` locally
(`POSTAL_PREVIEW_MISSIVE_TYPES`, `build_preview_context`).

Extract the postal / preview context into a neutral module
(`postal.py` or `preview_context.py`) that imports neither the views nor the
model as an entry point. `is_postal_like` and the letter context no longer
need the views.

### 3. Send / retrieve / cancel

`send_missive`, `resend_missive`, `retrieve_missive`, `call_provider_service`
→ a service (`missive_send.py` or equivalent) that **receives** a `Missive`.

The model keeps `can_send`, status, `external_id`. That is where the real
bugs live (transaction around the provider, `REQUEST` without a recipient,
and so on): a thinner file makes them easier to see.

### 4. PDF + templates

`body_to_pdf`, `generate_first_document`, `*_compiled` already lean on
`processors/`. Leave them as one-line façades, or move them fully into that
package.

### 5. Cloning

`duplicate_missive` / `duplicate_attachments` / `duplicate_recipients` /
`duplicate_related_objects` can follow send, later. Not urgent.

---

## When not to start

This split does not improve security or deliverability. Do it when a real
change would otherwise fight the file size, not as a standalone cleanup.

---

## Done when

- `models/missive.py` no longer imports `views` or `processors`, and contains
  no `mark_safe`
- send / retrieve / cancel no longer hold provider logic on the model
  (façade is fine)
- no behaviour change: the existing Django suite is enough; no extra
  “split” test battery
