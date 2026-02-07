## Project Structure

Geoaddress follows a standard Python package structure with a provider-based architecture using ProviderKit for provider management.

### General Structure

```
python-geoaddress/
├── src/
│   └── geoaddress/           # Main package directory
│       ├── __init__.py       # Package exports and field descriptions
│       ├── providers/        # Address provider implementations
│       │   ├── __init__.py   # GeoaddressProvider base class
│       │   ├── nominatim.py  # Nominatim provider (OpenStreetMap)
│       │   ├── photon.py     # Photon provider (Komoot/OSM)
│       │   ├── google_maps.py # Google Maps provider
│       │   ├── mapbox.py     # Mapbox provider
│       │   ├── locationiq.py # LocationIQ provider
│       │   ├── opencage.py   # OpenCage provider
│       │   ├── geocode_earth.py # Geocode Earth provider
│       │   ├── geoapify.py   # Geoapify provider
│       │   ├── maps_co.py    # Maps.co provider
│       │   ├── here.py       # HERE provider
│       │   └── google.py     # Google provider
│       ├── commands/         # Command infrastructure
│       │   └── address.py    # Address command
│       ├── helpers.py        # Helper functions (get_address_providers, addresses_autocomplete, etc.)
│       ├── cli.py            # CLI interface
│       └── __main__.py       # Entry point for package execution
├── tests/                    # Test suite
│   └── ...
├── docs/                     # Documentation
│   └── ...
├── service.py                # Main service entry point script
├── pyproject.toml            # Project configuration
└── ...
```

### Module Organization Principles

- **Single Responsibility**: Each module should have a clear, single purpose
- **Separation of Concerns**: Keep different concerns in separate modules
- **Provider-Based Architecture**: Providers inherit from ProviderKit's ProviderBase
- **Clear Exports**: Use `__init__.py` to define public API
- **Logical Grouping**: Organize related functionality together

### Provider Organization

The `providers/` directory contains address provider implementations:

- **`__init__.py`**: Defines `GeoaddressProvider` base class that extends `ProviderBase` from ProviderKit
- Each provider file (e.g., `nominatim.py`, `google_maps.py`) implements a specific geocoding service
- All providers inherit from `GeoaddressProvider` which provides common functionality
- Providers implement services: `addresses_autocomplete`, `reverse_geocode`

### Available Providers

- **Free providers** (no API key required):
  - Nominatim (OpenStreetMap)
  - Photon (Komoot/OSM)

- **Paid/API key providers**:
  - Google Maps
  - Mapbox
  - LocationIQ
  - OpenCage
  - Geocode Earth
  - Geoapify
  - Maps.co
  - HERE

### Helper Functions

The `helpers.py` module provides:
- `get_address_providers()`: Get address providers from various sources
- `addresses_autocomplete()`: Search addresses using providers
- `reverse_geocode()`: Reverse geocoding (coordinates → address)

### Package Exports

The public API is defined in `src/geoaddress/__init__.py`:
- `GEOADDRESS_FIELDS_DESCRIPTIONS`: Dictionary describing address field meanings

### ProviderKit Integration

Geoaddress uses ProviderKit for provider management:
- Providers inherit from `ProviderBase` via `GeoaddressProvider`
- Uses ProviderKit's helper functions for provider discovery and management
- Providers can be loaded from JSON, configuration, or directory scanning

