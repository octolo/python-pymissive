# webhook

Generate an opt-in `WEBHOOK_SECRET` from the provider name, the UTC date, and
mouse-motion entropy.

## Synopsis

```
pymissive webhook secret --provider <name> [--seconds 5]
```

A window opens. Move the mouse until it closes. The token is printed on stdout.

## Required options

| Option | Description |
|--------|-------------|
| `--provider` | Provider name (e.g. brevo, maileva, scaleway) |

## Optional options

| Option | Description |
|--------|-------------|
| `--seconds` | How long to sample the pointer (default: 5) |

## Examples

```bash
pymissive webhook secret --provider brevo
pymissive webhook secret --provider maileva --seconds 8
```

Put the printed value in `WEBHOOK_SECRET` (see `WEBHOOK_AUTHENTICATION.md` at
the monorepo root). Django can generate the same kind of token from
`SECRET_KEY` via the webhook admin, without the mouse.
