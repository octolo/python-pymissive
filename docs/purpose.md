## Project Purpose

**Geoaddress** is a Python library for address geocoding and reverse geocoding. It provides a unified interface to multiple geocoding providers (Nominatim, Google Maps, Mapbox, etc.) using ProviderKit for provider management.

### Core Functionality

The library enables you to:

1. **Search addresses** with multiple geocoding providers:
   - Address geocoding (address → coordinates)
   - Reverse geocoding (coordinates → address)
   - Address validation and normalization
   - Address autocomplete

2. **Manage multiple providers** through ProviderKit:
   - Provider discovery and enumeration
   - Provider selection and fallback mechanisms
   - Configuration management per provider
   - Dependency validation (API keys, packages)

3. **Standardized address format**:
   - Consistent address field structure across all providers
   - Field descriptions for address components
   - Support for international addresses
   - Structured address data (address_line1, city, postal_code, country, etc.)

### Architecture

The library uses a provider-based architecture built on ProviderKit:

- Each geocoding service is implemented as a provider inheriting from `GeoaddressProvider`
- `GeoaddressProvider` extends `ProviderBase` from ProviderKit
- Providers are organized in the `providers/` directory
- Common functionality is shared through the base `GeoaddressProvider` class
- Provider discovery and management is handled by ProviderKit

### Available Services

All providers implement the following services:

- **`addresses_autocomplete`**: Search for addresses by query string
- **`reverse_geocode`**: Convert coordinates (lat/lon) to address

### Supported Providers

**Free providers** (no API key required):
- **Nominatim**: OpenStreetMap-based geocoding
- **Photon**: Komoot's OpenStreetMap geocoding service

**Paid/API key providers**:
- **Google Maps**: Google's geocoding API
- **Mapbox**: Mapbox Geocoding API
- **LocationIQ**: LocationIQ Geocoding API
- **OpenCage**: OpenCage Geocoding API
- **Geocode Earth**: Geocode Earth API
- **Geoapify**: Geoapify Geocoding API
- **Maps.co**: Maps.co Geocoding API
- **HERE**: HERE Geocoding API

### Address Fields

The library uses a standardized address format with the following fields:

- `text`: Full formatted address string
- `reference`: Backend reference ID (place ID)
- `address_line1`: Street number and name
- `address_line2`: Building, apartment, floor (optional)
- `address_line3`: Additional address info (optional)
- `city`: City name
- `postal_code`: Postal/ZIP code
- `state`: State/region/province
- `region`: Region or administrative area
- `country`: Country name
- `country_code`: ISO country code (e.g., FR, US, GB)
- `municipality`: Municipality or local administrative unit
- `neighbourhood`: Neighbourhood, quarter, or district
- `address_type`: Address type or place type
- `latitude`: Latitude coordinate (float)
- `longitude`: Longitude coordinate (float)
- `osm_id`: OpenStreetMap ID
- `osm_type`: OpenStreetMap type
- `confidence`: Confidence score (0-100%)
- `relevance`: Relevance score (0-100%)
- `backend`: Backend display name
- `backend_name`: Simple backend name (e.g., nominatim)
- `geoaddress_id`: Combined backend_name-reference ID

### Use Cases

- Address search and autocomplete
- Geocoding addresses to coordinates
- Reverse geocoding coordinates to addresses
- Address validation and normalization
- Multi-provider address lookup with fallback
- Address data standardization across different geocoding services
- Integration with mapping and location-based applications

