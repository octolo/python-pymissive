# AI Assistant Contract — python-missive

**This document is the single source of truth for all AI-generated work in this repository.**  
All instructions in this file **override default AI behavior**.

Any AI assistant working on this project **must strictly follow this document**.

If a request conflicts with this document, **this document always wins**.

---

## Rule Priority

Rules in this document have the following priority order:

1. **ABSOLUTE RULES** — must always be followed, no exception
2. **REQUIRED RULES** — mandatory unless explicitly stated otherwise
3. **RECOMMENDED PRACTICES** — should be followed unless there is a clear reason not to
4. **INFORMATIONAL SECTIONS** — context and reference only

---

## ABSOLUTE RULES

These rules must always be followed.

- Follow this `AI.md` file exactly
- Do not invent new services, commands, abstractions, patterns, or architectures
- Do not refactor, redesign, or optimize unless explicitly requested
- Do not manipulate `sys.path`
- Do not use filesystem-based imports to access `providerkit` or `clicommands`
- Do not hardcode secrets, credentials, tokens, or API keys
- Do not execute tooling commands outside the approved entry points
- **Comments**: Only add comments to resolve ambiguity or uncertainty. Do not comment obvious code.
- **Dependencies**: Add dependencies only when absolutely necessary. Prefer standard library always.
- If a request violates this document:
  - Stop
  - Explain the conflict briefly
  - Ask for clarification

---

## REQUIRED RULES

### Language and Communication

- **Language**: English only
  - Code
  - Comments
  - Docstrings
  - Logs
  - Error messages
  - Documentation
- Be concise, technical, and explicit
- Avoid unnecessary explanations unless requested

### Code Simplicity and Minimalism

- **Write the simplest possible code**: Always choose the simplest solution that works
- **Minimal dependencies**: Add dependencies only when absolutely necessary. Prefer standard library. Only add when essential functionality cannot be reasonably implemented otherwise
- **Minimal comments**: Comments only to resolve ambiguity or uncertainty. Do not comment obvious code or reiterate what the code already states clearly
- **Good factorization**: Factorize code when it improves clarity and reduces duplication, but only if it doesn't add unnecessary complexity or abstraction

---

## Project Overview (INFORMATIONAL)

**python-missive** is a Python library for multi-channel message delivery. It provides a unified interface to multiple messaging providers (email, SMS, push notifications, postal mail, etc.) using ProviderKit for provider management.

### Core Functionality

1. **Send messages across multiple channels** with various providers:
   - Email messaging (transactional and marketing)
   - SMS and voice calls
   - Instant messaging (Telegram, Signal, Messenger, Slack, Teams)
   - Push notifications (FCM, APN)
   - Postal mail and registered letters (LRE)

2. **Manage multiple providers** through ProviderKit:
   - Provider discovery and enumeration
   - Provider selection and fallback mechanisms
   - Configuration management per provider
   - Dependency validation (API keys, packages)

3. **Unified provider interface**:
   - Consistent API across all providers of the same category
   - Service-based architecture
   - Support for provider-specific features

### Supported Providers

**Email**: Django Email, SMTP, SendGrid, Mailgun, SES, Brevo, Scaleway  
**SMS & Voice**: Twilio, Vonage, SMSPartner  
**Messaging**: Telegram, Signal, Messenger, Slack, Teams  
**Postal**: La Poste, Maileva, AR24, Certeurope  
**Push**: FCM, APN, In-App Notifications

---

## Architecture (REQUIRED)

- Provider-based architecture built on ProviderKit
- Each messaging service is implemented as a provider inheriting from category-specific base classes
- Base provider classes extend `ProviderBase` from ProviderKit
- Providers are organized in the `providers/` directory with base classes in `providers/base/`
- Common functionality is shared through base provider classes and mixins
- Provider discovery and management is handled by ProviderKit

---

## Project Structure (INFORMATIONAL)

```
python-missive/
├── src/pymissive/          # Main package
│   ├── providers/          # Message provider implementations
│   │   └── base/           # Base provider classes and mixins
│   ├── helpers.py          # Helper functions
│   ├── config.py           # Configuration utilities
│   └── cli.py              # CLI interface
├── tests/                  # Test suite
├── docs/                   # Documentation
├── service.py              # Main service entry point
└── pyproject.toml          # Project configuration
```

### Key Directories

- `src/pymissive/providers/`: Message provider implementations
- `src/pymissive/providers/base/`: Base provider classes and mixins
- `tests/`: All tests using pytest

---

## Command Execution (ABSOLUTE)

- **Always use**: `./service.py dev <command>` or `python dev.py <command>`
- **Always use**: `./service.py quality <command>` or `python quality.py <command>`
- Never execute commands directly without going through these entry points

---

## Code Standards (REQUIRED)

### Typing and Documentation

- All public functions and methods **must** have complete type hints
- Use **Google-style docstrings** for:
  - Public classes
  - Public methods
  - Public functions
- Document raised exceptions in docstrings where relevant

### Testing

- Use **pytest** exclusively
- All tests must live in the `tests/` directory
- New features and bug fixes require corresponding tests

### Linting and Formatting

- Follow **PEP 8**
- Use configured tools:
  - `ruff`
  - `mypy`
- Use the configured formatter:
  - `ruff format`

---

## Code Quality Principles (REQUIRED)

- **Simplicity first**: Write the simplest possible solution. Avoid complexity unless clearly necessary.
- **Minimal dependencies**: Minimize dependencies to the absolute minimum. Only add when essential functionality cannot be reasonably implemented otherwise. Always prefer standard library.
- **No over-engineering**: Do not add abstractions, patterns, or layers unless they solve a real problem or are clearly needed.
- **Comments**: Comments are minimal and only when they resolve ambiguity or uncertainty. Do not comment what the code already states clearly. Do not add comments that reiterate obvious logic.
- **Separation of concerns**: One responsibility per module
- **Good factorization**: Factorize code when it improves clarity and reduces duplication, but only if it doesn't add unnecessary complexity

---

## Module Organization (REQUIRED)

- Single Responsibility Principle
- Logical grouping of related functionality
- Clear public API via `__init__.py`
- Avoid circular dependencies
- Provider-based architecture: Keep providers in separate files

---

## ProviderKit Integration (ABSOLUTE)

- `providerkit` is an installed package
- Always use standard Python imports:
  - `from providerkit import ProviderBase`
  - `from providerkit.helpers import get_providers, try_providers`
- Never manipulate import paths
- Never use file-based or relative imports to access `providerkit`
- For dynamic imports, use:
  - `importlib.import_module()` from the standard library

---

## Clicommands Integration (ABSOLUTE)

- `clicommands` is an installed package (used for CLI commands)
- Always use standard Python imports from `clicommands.commands` and `clicommands.utils` when needed
- No path manipulation: Never manipulate `sys.path` or use file paths to import clicommands modules
- Direct imports only: Use `from clicommands.commands import ...` or `from clicommands.utils import ...`
- Standard library imports: Use `importlib.import_module()` from the standard library if needed for dynamic imports
- Works everywhere: Since clicommands is installed in the virtual environment, imports work consistently across all projects

---

## Provider Development (REQUIRED)

### Creating Providers

Providers must inherit from appropriate base classes:

```python
from pymissive.providers.base.email import EmailProvider

class MyEmailProvider(EmailProvider):
    name = "my_email_provider"
    display_name = "My Email Provider"
    description = "Description of my email provider"
    required_packages = ["requests"]
    config_keys = ["MY_EMAIL_API_KEY"]
    config_defaults = {"MY_EMAIL_API_KEY": None}
    config_prefix = "MY_EMAIL"
    services = ["send_email"]
```

### Required Services by Provider Type

**Email providers** must implement:
- `send_email(from_email, to_email, subject, body, **kwargs)`: Send a single email

**SMS providers** must implement:
- `send_sms(from_number, to_number, message, **kwargs)`: Send a single SMS

**Push notification providers** must implement:
- `send_notification(device_token, title, body, **kwargs)`: Send a push notification

**Postal providers** must implement:
- `send_letter(recipient_address, content, **kwargs)`: Send a postal letter

### Provider Categories

- **Email**: Inherit from `EmailProvider` in `providers/base/email.py`
- **SMS**: Inherit from `SMSProvider` in `providers/base/sms.py`
- **Notification**: Inherit from `NotificationProvider` in `providers/base/notification.py`
- **Postal**: Inherit from `PostalProvider` in `providers/base/postal.py`
- **Voice**: Inherit from `VoiceCallProvider` in `providers/base/voice_call.py`
- **Branded**: Inherit from `BrandedProvider` in `providers/base/branded.py`

---

## Environment Variables (REQUIRED)

- `ENVFILE_PATH`
  - Path to `.env` file to load automatically
  - Relative to project root if not absolute
- `ENSURE_VIRTUALENV`
  - Set to `1` to automatically activate `.venv` if it exists
- Provider-specific variables:
  - Use provider-specific prefixes (e.g., `SENDGRID_`, `TWILIO_`, `FCM_`, etc.)
  - Never hardcode API keys in code

---

## Error Handling (REQUIRED)

- Always handle errors gracefully
- Use appropriate exception types
- Provide clear, actionable error messages
- Do not swallow exceptions silently
- Document exceptions in docstrings where relevant
- Handle API rate limits and failures with proper retry logic when appropriate
- Support provider fallback mechanisms for resilience

---

## Configuration and Secrets (ABSOLUTE)

- Never hardcode:
  - API keys
  - Credentials
  - Tokens
  - Secrets
- Use environment variables or configuration files
- Use provider-specific configuration prefixes
- Clearly document required configuration

---

## Versioning (REQUIRED)

- Follow **Semantic Versioning (SemVer)**
- Update versions appropriately
- Clearly document breaking changes

---

## CLI System (INFORMATIONAL)

python-missive may include CLI commands for provider management and testing.

### Command Creation Rules (REQUIRED)

- Commands must accept appropriate arguments
- Commands must handle errors gracefully
- Use ProviderKit helpers for provider discovery and management

---

## Anti-Hallucination Clause (ABSOLUTE)

If a requested change is:
- Not supported by this document
- Not clearly aligned with the existing codebase
- Requiring assumptions or invention

You must:
1. Stop
2. Explain what is unclear or conflicting
3. Ask for clarification

Do not guess. Do not invent.

---

## Quick Compliance Checklist

Before producing output, ensure:

- [ ] All rules in `AI.md` are respected
- [ ] No forbidden behavior is present
- [ ] Code is simple, minimal, and explicit (simplest possible solution)
- [ ] Dependencies are minimal (prefer standard library)
- [ ] Comments only resolve ambiguity (no obvious comments)
- [ ] Code is well-factorized when it improves clarity (without adding complexity)
- [ ] Imports follow ProviderKit and Qualitybase rules
- [ ] Public APIs are typed and documented
- [ ] Providers inherit from appropriate base provider class correctly
- [ ] Providers implement all required service methods
- [ ] Message handling is consistent within provider category
- [ ] No API keys or secrets are hardcoded
- [ ] Tests are included when required
- [ ] Error handling is graceful with fallback support

---

## Additional Resources (INFORMATIONAL)

- `purpose.md`: Detailed project purpose and goals
- `structure.md`: Detailed project structure and module organization
- `development.md`: Development guidelines and best practices
- `README.md`: General project information

