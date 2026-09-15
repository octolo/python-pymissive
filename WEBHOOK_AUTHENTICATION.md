# Webhook authentication (Brevo, Scaleway, Maileva)

Applies to both packages: **python-pymissive** (one secret, outbound
registration, inbound verifier) and **django-pymissive** (HTTP gate, URL
building).

Authentication is **opt-in per provider**.

- No `WEBHOOK_SECRET` → same as today: the body is ingested as-is.
- `WEBHOOK_SECRET` set → `WebhookView` checks the request **before**
  `handle_events`. No matching proof → **403**, nothing is stored.

`handle_events` / `retrieve_events` stay payload-only.

---

## Generic model

One secret. One inbound check. Each provider translates the secret into
whatever its API accepts when creating the webhook.

```
WEBHOOK_SECRET
        │
        ├── outbound (create_webhook_*)
        │     Brevo    → auth: { type: bearer, token }
        │     Maileva  → authentication: { basic: { login, password } }
        │     Scaleway → path /<token>/  (SNS cannot set headers)
        │
        └── inbound (WebhookView)
              Authorization: Bearer <secret>
              Authorization: Basic base64(login:secret)
              URL token == secret
```

The gate does not care which provider called. `pymissive.webhook_auth` accepts
any of the three proofs with `hmac.compare_digest`.

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
        "WEBHOOK_BASIC_LOGIN": os.getenv("MAILEVA_WEBHOOK_BASIC_LOGIN", "pymissive"),
    },
}
```

Generate the value with `pymissive webhook secret --provider <name>` or the
Django admin **Generate webhook secret** action (see below). Re-create the
webhook after setting it so the provider starts sending the proof.

---

## Brevo

Brevo does not sign the body. It can attach Bearer, Basic, or custom headers
([secured webhooks](https://developers.brevo.com/docs/secured-webhooks)).

With `WEBHOOK_SECRET`, `create_webhook_*` registers
`auth={"type": "bearer", "token": <secret>}`. Callbacks send
`Authorization: Bearer <secret>`. The URL path does not change.

---

## Maileva

[POST /subscriptions](https://www.maileva.com/catalogue-api/notifications-webhooks/#tag/Abonnements/paths/~1subscriptions/post)
accepts an optional `authentication` object
([notification_center v2](https://www.maileva.com/app/uploads/2023/09/api-notification_center-v2-10.yaml)):

```yaml
authentication:
  basic:
    login: company.name
    password: Company2020!
  oauth2:
    oauth2_server: https://api.mycompany.com/authentication/oauth2/token
    client_id: …
    client_secret: …
    grant_type: client_credentials
```

We use **Basic**, not OAuth2 (OAuth2 would require us to expose a token
endpoint). With `WEBHOOK_SECRET`, create/update send:

```json
"authentication": {
  "basic": { "login": "<WEBHOOK_BASIC_LOGIN>", "password": "<WEBHOOK_SECRET>" }
}
```

`WEBHOOK_BASIC_LOGIN` defaults to `pymissive`. Maileva then POSTs with
`Authorization: Basic …`. The gate checks the **password** only (`login`
is a label). The callback URL stays
`/missive/webhook/maileva/lre/` — no secret in the path or in access logs.

Without a secret, subscriptions stay `{callback_url, event_type, resource_type}`
as today.

---

## Scaleway

Email events arrive as an AWS SNS envelope. SNS cannot attach Bearer or Basic.
`webhook_uses_url_token()` is True: `build_webhook_url` adds the secret as
the last path segment when it is set.

`/missive/webhook/scaleway/email/<token>/`

The unauthenticated URL then answers 403. Re-create the SNS subscription so
it points at the token URL.

---

## Generating the secret

`sha256(provider + UTC date + extra)`, url-safe. Same inputs → same value.

### CLI

`extra` is mouse-motion samples:

```bash
pymissive webhook secret --provider brevo
pymissive webhook secret --provider maileva --seconds 8
```

### Django admin

`extra` is `settings.SECRET_KEY`, plus an optional **Salt** field to mint a
new token. Webhook changelist → **Generate webhook secret**. Staff-only. Not
stored in the database.

---

## Enabling

1. Generate a secret per provider you want to lock.
2. Map it to `WEBHOOK_SECRET` in `PROVIDERKIT_PROVIDERS_CONFIG` (or env).
3. Re-create / update the webhook so the provider receives Bearer (Brevo),
   Basic (Maileva), or the token URL (Scaleway).
4. Leave the key unset to keep the current open behaviour.

A 403 is intentional (no retry, unlike 503). Rotate by generating a new
token, changing the env var, then re-registering.
