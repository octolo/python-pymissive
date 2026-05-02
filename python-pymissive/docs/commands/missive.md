# missive

Create, send, update, delete, or cancel missives via provider.

`cancel` requests a provider **cancel** API (stop an in-flight sending). `delete missive` calls **`delete_*`** (remove sending on the provider, often broader than cancel). Some providers only implement one of the two (e.g. Maileva LRE: **delete** only).

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `send` | Send a missive (email, SMS, postal, etc.) |
| `retrieve` | Retrieve data (webhooks, email, postal, sms) |
| `create` | Create webhook |
| `update` | Update webhook |
| `delete` | Delete webhook **or** delete a missive/sending (`delete missive`, provider `delete_*`) |
| `cancel` | Cancel via provider `cancel_*` (not available on all providers) |

## Synopsis

```bash
# Send
pymissive missive send --provider <name> --missive_type <type> --recipients '<json>' [options]

# Create webhook
pymissive missive create webhook --provider <name> --type <email|sms|postal> [--domain example.com]

# Update webhook
pymissive missive update webhook --provider <name> --type <email|sms> --webhook-id <id>

# Delete webhook
pymissive missive delete webhook --provider <name> --type <email|sms> --webhook-id <id>

# Delete sending on provider (provider delete_* ; e.g. Maileva LRE)
pymissive missive delete missive --provider <name> [--type lre] --external-id <id>

# Cancel missive (provider cancel_* ; not Maileva LRE)
pymissive missive cancel --provider <name> [--type postal] --external-id <id>
```

## Common options

| Option | Description |
|--------|-------------|
| `--provider` | Provider name (e.g. brevo, scaleway, maileva) |
| `--type` | Missive type for webhooks (email, sms, postal) |
| `--missive-type` | Missive type for send (email, sms, lre, etc.) |
| `--dir` | Provider config directory |
| `--json` | Path to provider config JSON |

## Send options

| Option | Description |
|--------|-------------|
| `--recipients` | JSON array of recipients (alternative to individual recipient options) |
| `--recipient_name` | Recipient display name |
| `--recipient_email` | Recipient email (single recipient) |
| `--recipient_phone` | Recipient phone (single recipient) |
| `--recipient_address` | Recipient address as JSON (single recipient, e.g. postal) |
| `--subject` | Subject line |
| `--body-html` | HTML body |
| `--body-text` | Plain text body |
| `--sender_email` | Sender email |
| `--sender_name` | Sender name |

## Examples

```bash
# Send email (with --recipients JSON array)
pymissive missive send --provider brevo --missive_type email \
  --subject "Hello" --recipients '[{"email":"user@example.com"}]' --sender_email from@example.com

# Send email (single recipient via options)
pymissive missive send --provider brevo --missive_type email \
  --subject "Hello" --recipient_email user@example.com --recipient_name "John" \
  --sender_email from@example.com --sender_name "My App"

# Send SMS (single recipient)
pymissive missive send --provider brevo --missive_type sms \
  --body_text "Code: 1234" --recipient_phone "+33612345678" --recipient_name "Jane"

# Send postal (recipient address as JSON)
pymissive missive send --provider maileva --missive_type postal \
  --recipient_address '{"address_line1":"10 rue Example","city":"Paris","postal_code":"75001","country":"France"}'

# Retrieve webhooks
pymissive missive retrieve webhooks --provider brevo

# Create webhook
pymissive missive create webhook --provider brevo --type email --domain example.com

# Delete webhook
pymissive missive delete webhook --provider brevo --type email --webhook-id 123

# Delete sending on provider (Maileva: delete_lre)
pymissive missive delete missive --provider maileva --type lre --external-id SENDING_ID

# Cancel (only if provider implements cancel_*)
pymissive missive cancel --provider <provider> --type <type> --external-id SENDING_ID
```

## Recipients format

- **Email**: `{"email": "x@y.com", "name": "John"}`
- **Phone**: `{"phone": "+33612345678", "name": "Jane"}`
- **Address**: `{"address": {"address_line1": "...", "city": "...", "postal_code": "...", "country": "France"}}`
