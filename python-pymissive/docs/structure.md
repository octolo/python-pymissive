## Project Structure

python-missive follows a standard Python package structure with a provider-based architecture using ProviderKit for provider management.

### General Structure

```
python-missive/
├── src/
│   └── pymissive/            # Main package directory
│       ├── __init__.py       # Package exports
│       ├── providers/
│       │   ├── base/         # Shared mixins + MissiveProviderBase
│       │   ├── brevo/        # Provider entry point + static configuration
│       │   ├── maileva/      # API, send, retrieve, webhook and helpers
│       │   ├── scaleway.py, partner.py
│       │   ├── slack.py, teams.py, discord.py
│       │   └── hand_delivery.py, fake.py
│       ├── commands/         # CLI commands and packaged help
│       ├── config/           # Types and field definitions
│       ├── cli.py, __main__.py
│       └── utils.py
├── tests/                    # Test suite
├── docs/                     # Documentation
└── pyproject.toml            # Build, dependencies and tool configuration
```

### Module Organization Principles

- **Single Responsibility**: Each module should have a clear, single purpose
- **Separation of Concerns**: Keep different concerns in separate modules
- **Provider-Based Architecture**: Providers inherit from ProviderKit's ProviderBase
- **Clear Exports**: Use `__init__.py` to define public API
- **Logical Grouping**: Organize related functionality together

### Provider Organization

The `providers/` directory contains message provider implementations:

- **`base/`**: `MissiveProviderBase` plus the mixins that hold real behaviour
  (`acknowledgement`, `attachments`, `branded`). Channel types (`email`, `sms`,
  `registered_letter`, …) are services in the config; ProviderKit raises if the method is missing.
- **`brevo/` and `maileva/`**: larger providers grouped into packages while
  retaining the public imports `pymissive.providers.brevo` and
  `pymissive.providers.maileva`.
- Each shipped provider module or package implements a specific messaging service
- All providers inherit from `MissiveProviderBase` (which extends ProviderKit's `ProviderBase`)

### Available Providers by Category

**Email providers**:
- BrevoAPIProvider
- ScalewayProvider

**SMS providers**:
- BrevoAPIProvider
- PartnerProvider

**Instant messaging providers**:
- SlackProvider
- TeamsProvider
- DiscordProvider

**Postal & registered letter providers**:
- MailevaProvider

**Other providers**:
- HandDeliveryProvider
- FakeProvider

Providers that are only planned are listed in the README. They do not have
placeholder modules in the package.

### Helper Functions

Provider discovery lives in ProviderKit (`providerkit.helpers.get_providers`).
`pymissive.utils` holds the few framework-agnostic helpers that belong here
(for example `is_disable_send`).

### Package Exports

`src/pymissive/__init__.py` exposes the package version. Provider classes are
imported from their provider module or package, for example
`pymissive.providers.brevo.BrevoAPIProvider`, and are also available through
ProviderKit discovery.

### ProviderKit Integration

python-missive uses ProviderKit for provider management:
- Providers inherit from `ProviderBase` via category-specific base classes
- Uses ProviderKit's helper functions for provider discovery and management
- Providers can be loaded from configuration or directory scanning

