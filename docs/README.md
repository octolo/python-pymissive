## Assistant Guidelines

This file provides general guidelines for the AI assistant working on this project.

For detailed information, refer to:
- `AI.md` - Condensed reference guide for AI assistants (start here)
- `purpose.md` - Project purpose and goals
- `structure.md` - Project structure and module organization
- `development.md` - Development guidelines and best practices

### Quick Reference

- Always use `./service.py dev <command>` or `python dev.py <command>` for project tooling
- Always use `./service.py quality <command>` or `python quality.py <command>` for quality checks
- Maintain clean module organization and separation of concerns
- Default to English for all code artifacts (comments, docstrings, logging, error strings, documentation snippets, etc.)
- Follow Python best practices and quality standards
- Keep dependencies minimal and prefer standard library
- Ensure all public APIs have type hints and docstrings
- Write tests for new functionality

### Missive-Specific Guidelines

- **Provider development**: All providers must inherit from the appropriate base class (EmailProvider, SMSProvider, etc.)
- **ProviderKit integration**: Use ProviderKit for provider management, discovery, and configuration
- **API keys**: Never hardcode API keys, use environment variables with provider-specific prefixes
- **Error handling**: Handle API rate limits and failures gracefully with retry logic and fallback mechanisms

### Provider Implementation Checklist

When creating a new provider:
- [ ] Inherit from the appropriate base provider class
- [ ] Define `name`, `display_name`, and `description`
- [ ] Set `required_packages` if needed
- [ ] Configure `config_keys` and `config_defaults`
- [ ] Implement required service methods
- [ ] Handle errors gracefully
- [ ] Add tests for the provider

