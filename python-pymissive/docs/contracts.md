# Public contracts

`pymissive` is the framework-agnostic catalogue and provider layer. A framework
integration may persist missives, campaigns and delivery state. It should take
types, supports, provider events and recipient field names from this package
rather than defining a second vocabulary.

## Package boundary

This package owns:

- canonical missive types and the support that groups them;
- provider service names such as `send_letter` and `preview_registered_letter`;
- provider event names and their categories;
- the normalized recipient field names returned by providers;
- provider send, retrieve, preview and webhook behavior.

A framework integration owns persistence, workflow statuses, queries,
transactions, campaigns and rendering. Application-specific labels, permissions,
templates and contact-selection rules stay in the application.

Importing `pymissive.config` or `pymissive.config.recipient` does not require
Django.

## Missive types and supports

`MISSIVE_TYPES` is the catalogue of canonical type keys. `GENERIC_SUPPORT`
groups those keys into `email`, `phone`, `address` and `application`.

Use these helpers instead of maintaining another mapping:

- `normalize_missive_type` returns a canonical type, or `""` when the value is
  not a type;
- `missive_support_for_type` returns the support that owns a type, or `""`;
- `normalize_support` accepts either a support or a type and returns the
  canonical support, or `""`;
- `missive_types_for_support` returns a new list of types for that support.

Every type belongs to exactly one support, and every support entry names types
that exist in `MISSIVE_TYPES`. Hyphens in a known type are treated as
underscores. Unknown values, including historical names such as `postal`,
`courrier`, `mail` and `app`, return an empty result. They must not be turned
into a filter that matches every missive.

`provider_service_name(service, missive_type)` builds names such as
`preview_registered_letter`. An unknown type raises `ValueError`.

The catalogue on a provider base class lists possible service names. It does
not prove that a concrete provider implements one. Test the provider instance
with `hasattr`.

## Provider events

`SUCCESSFUL_EVENTS`, `FAILED_EVENTS` and `INFO_EVENTS` describe external
delivery progress. Their keys do not overlap, and `ALL_EVENTS` is exactly their
union.

`SENT_EVENTS` is `("sent", "accepted", "delivered")`. These events show that a
missive left the sender side. `delivered` is included because a delivery proves
an earlier send even when the provider never emitted `sent`. The order is part
of the contract: an integration that dates the send from the oldest matching
event depends on this set.

Provider events are not a persisted workflow-status enum. A framework may map
them onto its own statuses and query predicates. Those statuses remain owned by
the framework integration.

## Normalized recipients

`pymissive.config.recipient.RECIPIENT_FIELDS` names the normalized recipient
values. The documented fields are:

| Field | Meaning |
|---|---|
| `recipient_type` | Generic role, such as recipient, cc, bcc or notification. It is not an application permission. |
| `name` | Display name. A preview may carry a name before a deliverable channel value exists. |
| `email`, `phone`, `address`, `notification_id` | Channel value for the recipient's support. A recipient exposes the field that matches that support. |
| `internal_id` | Identifier owned by the local integration. |
| `external_id` | Identifier owned by the provider. |
| `substitute_id` | Another stable local reference when the provider needs one. |
| `sent_at`, `delivered_at` | Optional provider timestamps. Their field format is `datetime`. |
| `tracking_number` | Optional carrier reference. |

This catalogue names fields. It does not validate addresses, define database
uniqueness, or choose which stored contact represents a recipient.

## Provider preview

A provider preview asks the provider for a staged proof or preview payload. It
does not resolve campaigns, steps, targets, templates or render context. That
preparation belongs to the framework integration, which may call a provider
preview method after it has resolved those objects.

`MailevaProvider` implements `preview_letter` and
`preview_registered_letter`. Both stage the postal payload and return normalized
provider data, including the provider id, a `draft` event, recipients and
attachments. They do not submit the sending.

Other shipped providers have no postal preview method. Absence of the method is
the capability signal. Do not add an empty `preview_*` method that only raises
`NotImplementedError`.

## Left to framework integrations

The following behavior is intentionally outside this package:

- persisted missives, recipients, campaigns, steps, targets and drafts;
- workflow statuses and database filters;
- related-object queries and statistics;
- transactions and atomic replacement of stored recipients;
- contact identity and storage deduplication;
- campaign send recaps;
- campaign preview preparation and template rendering;
- application metadata, permissions and channel labels.
