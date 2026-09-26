"""Great-circle distance.

MVP logistics uses straight-line (Haversine) distance between facilities.
Road distance, transport mode and freight quotes are a documented future
extension (docs/matching-engine.md); the location score says so explicitly.
"""

import math

from app.matching.types import GeoPoint

EARTH_RADIUS_KM = 6371.0088  # IUGG mean Earth radius


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def bounding_box(center: GeoPoint, radius_km: float) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lon, max_lon) enclosing a radius — a cheap SQL pre-filter."""
    dlat = math.degrees(radius_km / EARTH_RADIUS_KM)
    cos_lat = max(math.cos(math.radians(center.lat)), 1e-6)
    dlon = min(180.0, math.degrees(radius_km / (EARTH_RADIUS_KM * cos_lat)))
    return center.lat - dlat, center.lat + dlat, center.lon - dlon, center.lon + dlon
