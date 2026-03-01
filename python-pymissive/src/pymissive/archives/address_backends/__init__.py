"""Address verification backends."""

from __future__ import annotations

from .base import BaseAddressBackend
from .geocode_earth import GeocodeEarthAddressBackend
from .geoapify import GeoapifyAddressBackend
from .google_maps import GoogleMapsAddressBackend
from .here import HereAddressBackend
from .locationiq import LocationIQAddressBackend
from .maps_co import MapsCoAddressBackend
from .mapbox import MapboxAddressBackend
from .nominatim import NominatimAddressBackend
from .opencage import OpenCageAddressBackend
from .photon import PhotonAddressBackend

__all__ = [
    "BaseAddressBackend",
    "GeocodeEarthAddressBackend",
    "GeoapifyAddressBackend",
    "GoogleMapsAddressBackend",
    "HereAddressBackend",
    "LocationIQAddressBackend",
    "MapsCoAddressBackend",
    "MapboxAddressBackend",
    "NominatimAddressBackend",
    "OpenCageAddressBackend",
    "PhotonAddressBackend",
]
