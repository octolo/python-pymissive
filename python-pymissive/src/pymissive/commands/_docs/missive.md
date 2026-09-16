# missive

Create, send, update, delete, or cancel missives via provider.

`cancel` requests a provider **cancel** API (stop an in-flight sending). `delete missive` calls **`delete_*`** (remove sending on the provider, often broader than cancel). Some providers only implement one of the two (e.g. Maileva registered letter: **delete** only).

`retrieve events` calls **`retrieve_events_*`** (bulk event listing via ``retrieve_events(start_date, end_date)``). The parent provider implements the method as ``NotImplementedError``; providers override it. `retrieve billings` calls **`retrieve_billings_*`** (bulk invoiced lines via ``retrieve_billings(start_date, end_date)``). `retrieve` (`retrieve_email`, `retrieve_sms`, `retrieve_registered_letter`, …) fetches missive information from partner ID (`external_id`) or internal ID. `retrieve tracking_number` calls **`tracking_number_*`** (carrier tracking references per recipient, e.g. Maileva `registered_number`).

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `send` | Send a missive (email, SMS, letter, registered_letter, etc.) |
| `retrieve` | Retrieve data (webhooks, email, letter, registered_letter, sms, events, billings, tracking_number) |
| `create` | Create webhook |
| `update` | Update webhook |
| `delete` | Delete webhook **or** delete a missive/sending (`delete missive`, provider `delete_*`) |
| `cancel` | Cancel via provider `cancel_*` (not available on all providers) |

## Synopsis

```bash
# Send
pymissive missive send --provider <name> --missive_type <type> --recipients '<json>' [options]

# Create webhook
pymissive missive create webhook --provider <name> --type <email|sms|letter|registered_letter> [--domain example.com]

# Update webhook
pymissive missive update webhook --provider <name> --type <email|sms> --webhook-id <id>

# Delete webhook
pymissive missive delete webhook --provider <name> --type <email|sms> --webhook-id <id>

# Delete sending on provider (provider delete_* ; e.g. Maileva registered letter)
pymissive missive delete missive --provider <name> [--type registered_letter] --external-id <id>

# Cancel missive (provider cancel_* ; not Maileva registered letter)
pymissive missive cancel --provider <name> [--type letter] --external-id <id>

# Retrieve events in bulk (provider retrieve_events_* ; start_date and end_date required)
pymissive missive retrieve events --provider <name> --type <email|sms|registered_letter> --start-date <iso> --end-date <iso>

# Retrieve billings in bulk (provider retrieve_billings_* ; start_date and end_date required)
pymissive missive retrieve billings --provider <name> --type <registered_letter|email> --start-date <iso> --end-date <iso>

# Retrieve carrier tracking numbers (provider tracking_number_* ; e.g. Maileva registered letter)
pymissive missive retrieve tracking_number --provider maileva --type registered_letter --external-id <id>
```

## Common options

| Option | Description |
|--------|-------------|
| `--provider` | Provider name (e.g. brevo, scaleway, maileva) |
| `--type` | Missive type for webhooks and retrieve (email, sms, letter, registered_letter) |
| `--missive-type` | Missive type for send (email, sms, letter, registered_letter, etc.) |
| `--external-id` | External ID (partner / provider identifier) |
| `--start-date` | Start date for bulk event or billing retrieval |
| `--end-date` | End date for bulk event or billing retrieval |
| `--dir` | Provider config directory |
| `--json` | Path to provider config JSON |

## Send options

| Option | Description |
|--------|-------------|
| `--recipients` | JSON array of recipients (alternative to individual recipient options) |
| `--recipient_name` | Recipient display name |
| `--recipient_email` | Recipient email (single recipient) |
| `--recipient_phone` | Recipient phone (single recipient) |
| `--recipient_address` | Recipient address as JSON (single recipient, letter / registered_letter) |
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

# Send letter (recipient address as JSON)
pymissive missive send --provider maileva --missive_type letter \
  --recipient_address '{"address_line1":"10 rue Example","city":"Paris","postal_code":"75001","country":"France"}'

# Retrieve webhooks
pymissive missive retrieve webhooks --provider brevo

# Retrieve events in bulk (when the provider implements retrieve_events)
pymissive missive retrieve events --provider brevo --type email \
  --start-date 2026-01-01 --end-date 2026-01-31

# Retrieve billings in bulk (when the provider implements retrieve_billings)
pymissive missive retrieve billings --provider maileva --type registered_letter \
  --start-date 2026-08-01 --end-date 2026-08-31

# Retrieve carrier tracking numbers (Maileva: tracking_number_registered_letter)
pymissive missive retrieve tracking_number --provider maileva --type registered_letter --external-id SENDING_ID

# Create webhook
pymissive missive create webhook --provider brevo --type email --domain example.com

# Delete webhook
pymissive missive delete webhook --provider brevo --type email --webhook-id 123

# Delete sending on provider (Maileva: delete_registered_letter)
pymissive missive delete missive --provider maileva --type registered_letter --external-id SENDING_ID

# Cancel (only if provider implements cancel_*)
pymissive missive cancel --provider <provider> --type <type> --external-id SENDING_ID
```

## Recipients format

- **Email**: `{"email": "x@y.com", "name": "John"}`
- **Phone**: `{"phone": "+33612345678", "name": "Jane"}`
- **Address**: `{"address": {"address_line1": "...", "city": "...", "postal_code": "...", "country": "France"}}`
