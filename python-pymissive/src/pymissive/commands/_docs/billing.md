# billing

Retrieve billing/usage data from provider.

`retrieve` with `--start-date` and `--end-date` calls **`retrieve_billings_*`** (bulk listing via ``retrieve_billings(start_date, end_date)``). With `--external-id` it calls **`get_billings_*`** for a single missive.

## Synopsis

```
pymissive billing retrieve --provider <name> --start-date <iso> --end-date <iso> [--type registered_letter]
pymissive billing retrieve --provider <name> [--type registered_letter] [--external-id ID]
```

## Required options

| Option | Description |
|--------|-------------|
| `--provider` | Provider name (e.g. maileva) |

## Optional options

| Option | Description |
|--------|-------------|
| `--type` | Missive type (default: registered_letter) |
| `--external-id` | External ID for per-missive billing |
| `--start-date` | Start date for bulk billing retrieval |
| `--end-date` | End date for bulk billing retrieval |
| `--dir` | Provider config directory |
| `--json` | Path to provider config JSON |

## Examples

```bash
# Bulk retrieve (provider retrieve_billings_* ; start_date and end_date required)
pymissive billing retrieve --provider maileva --type registered_letter \
  --start-date 2026-08-01 --end-date 2026-08-31

pymissive billing retrieve --provider maileva --external-id MY_ID
```
