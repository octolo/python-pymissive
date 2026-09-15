# Webhook authentication (Brevo, Scaleway, Maileva)

Applies to both packages: **python-pymissive** (provider `config_keys`,
`create_webhook_*`, payload normalisation) and **django-pymissive** (HTTP
gate, URL building, ingestion).

Inbound events hit `/missive/webhook/<provider>/<missive_type>/` and become
delivery history. Authentication is **opt-in per provider**.

- No `WEBHOOK_SECRET` → same as today: the body is ingested as-is.
- `WEBHOOK_SECRET` set → the HTTP layer checks the request **before**
  `handle_events`. Mismatch or missing proof → **403**, nothing is stored.

The secret is not stored on `Missive` / `MissiveConfig`, and not in the
database. Generate it, then put it next to the other provider keys.

```python
PROVIDERKIT_PROVIDERS_CONFIG = {
    "brevo": {
        "EMAIL_API_KEY": os.getenv("BREVO_EMAIL_API_KEY"),
        "WEBHOOK_SECRET": os.getenv("BREVO_WEBHOOK_SECRET"),  # optional
    },
    "scaleway": {
        "ACCESS_KEY": os.getenv("SCALEWAY_ACCESS_KEY"),
        "SECRET_ACCESS_KEY": os.getenv("SCALEWAY_SECRET_ACCESS_KEY"),
        "WEBHOOK_SECRET": os.getenv("SCALEWAY_WEBHOOK_SECRET"),  # optional
    },
    "maileva": {
        "USERNAME": os.getenv("MAILEVA_USERNAME"),
        "PASSWORD": os.getenv("MAILEVA_PASSWORD"),
        "CLIENTID": os.getenv("MAILEVA_CLIENTID"),
        "SECRET": os.getenv("MAILEVA_SECRET"),
        "WEBHOOK_SECRET": os.getenv("MAILEVA_WEBHOOK_SECRET"),  # optional
    },
}
```

Without Django, the same `WEBHOOK_SECRET` lives on the provider instance
(`config_keys` / env). `create_webhook_*` still registers Bearer (Brevo) or
the token URL (Scaleway, Maileva). The caller is responsible for checking the
inbound request the same way `WebhookView` does.

`handle_events` / `retrieve_events` stay payload-only. Pull from the provider
API is already authenticated with the API credentials; it never sends a Bearer
or URL token.

---

## Brevo

Brevo does not sign the body (no HMAC). It can attach credentials on each
callback if we register them: Bearer, Basic Auth, or custom headers
([secured webhooks](https://developers.brevo.com/docs/secured-webhooks)).

**When `WEBHOOK_SECRET` is unset**

`create_webhook_email` / `sms` / `whatsapp` stay unchanged. Callbacks to
`/missive/webhook/brevo/<missive_type>/` are accepted without a header.

**When `WEBHOOK_SECRET` is set**

1. `create_webhook_*` registers `auth={"type": "bearer", "token": <secret>}`.
2. Brevo POSTs with `Authorization: Bearer <secret>`.
3. The gate compares the token to config with `hmac.compare_digest`.
4. Missing or wrong Bearer → 403.

Re-create (or update) the webhook after setting the secret, otherwise Brevo
keeps calling the old subscription with no header and every callback is
rejected.

The URL path does not need to change for Brevo. The secret lives in the header,
not in access logs.

---

## Scaleway

Scaleway email events arrive as an **AWS SNS** envelope (`Type`, `Message`,
`SubscribeURL`, `Signature`, `SigningCertURL`). There is no Brevo-style Bearer
API. SNS credentials (`SNS_ACCESS_KEY`, `SNS_SECRET_KEY`) are for **outbound**
topic/subscription management, not inbound proof.

**When `WEBHOOK_SECRET` is unset**

`/missive/webhook/scaleway/email/` stays open. `SubscriptionConfirmation`
triggers a GET on `SubscribeURL` only when the host is
``sns.mnq.<region>.scaleway.com`` and ``Action=ConfirmSubscription``.

**When `WEBHOOK_SECRET` is set**

The shared secret cannot be sent as a header by SNS. It is embedded in the
HTTPS endpoint we subscribe:

`/missive/webhook/scaleway/email/<token>/`

`build_webhook_url` adds that segment only when the secret is set. The gate
accepts the request if the path token matches. The unauthenticated URL then
answers 403.

SNS message-signature verification (cert URL allowlist + `Signature`) is the
stronger check and is not part of this opt-in secret. Until that exists, the
URL token is the gate.

After setting the secret, re-create the webhook so the SNS subscription points
at the token URL. Confirmation (`SubscribeURL`) only succeeds on that URL.

---

## Maileva

Maileva subscriptions store a `callback_url` only. No signing secret, no
Bearer, no custom headers on the notification.

**When `WEBHOOK_SECRET` is unset**

`create_webhook_lre` keeps registering
`/missive/webhook/maileva/lre/`. Anyone who can POST a valid-looking JSON
(`sending_id` / `resource_id` + event) can write LRE history.

**When `WEBHOOK_SECRET` is set**

Same pattern as Scaleway: the secret is the last path segment.

`/missive/webhook/maileva/lre/<token>/`

`build_webhook_url` / webhook registration use that URL when creating or
updating subscriptions. The gate compares the path token to `WEBHOOK_SECRET`.
The old path without a token returns 403.

Re-create or update the Maileva subscriptions after setting the secret, or
callbacks keep hitting the open URL and start failing.

The token will appear in Maileva’s admin and in access logs. That is the
trade-off: it is the only channel Maileva gives us.

---

## Generating the secret

The token is `sha256(provider + UTC date + extra)`, url-safe. Same inputs
give the same value.

### CLI (python-pymissive)

`extra` is mouse-motion samples collected for N seconds:

```bash
pymissive webhook secret --provider brevo
pymissive webhook secret --provider maileva --seconds 8
```

A window opens. Move the mouse until it closes. The token is printed on
stdout. Each run is unique because the pointer path is unique.

### Django admin (django-pymissive)

`extra` is `settings.SECRET_KEY`. Webhook changelist → **Generate webhook
secret**, pick the provider. The same provider on the same UTC day, with the
same Django secret, yields the same token (useful to recover a value you
did not save). Tomorrow’s date produces a new one.

Staff-only (`view` on the webhook admin). The token is shown in a readonly
field; it is not written to the database.

## Enabling

1. Generate a secret (CLI or admin) per provider you want to lock.
2. Export it (`BREVO_WEBHOOK_SECRET`, `SCALEWAY_WEBHOOK_SECRET`,
   `MAILEVA_WEBHOOK_SECRET`) and map it to `WEBHOOK_SECRET` in
   `PROVIDERKIT_PROVIDERS_CONFIG` (Django) or the provider config / env
   (agnostic).
3. Re-create / update the webhook so the provider receives the Bearer (Brevo)
   or the new URL (Scaleway, Maileva).
4. Leave the key unset on any provider that must stay on the current open
   behaviour.

A 403 is intentional: providers should not retry a rejected credential the way
they retry a 503 (lost event). Rotate by generating a new token, changing the
env var, then re-registering the webhook.
