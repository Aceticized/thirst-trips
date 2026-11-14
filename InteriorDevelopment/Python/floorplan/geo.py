"""Latitude/longitude <-> metres around a chosen origin (x = east, y = north)."""

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6371000.0


@dataclass
class LocalFrame:
    lat0: float
    lon0: float

    def to_local(self, lat: float, lon: float) -> tuple[float, float]:
        """Fine for a building or a campus; it ignores the curvature of the Earth."""
        x = math.radians(lon - self.lon0) * EARTH_RADIUS_M * math.cos(math.radians(self.lat0))
        y = math.radians(lat - self.lat0) * EARTH_RADIUS_M
        return x, y

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        lat = self.lat0 + math.degrees(y / EARTH_RADIUS_M)
        lon = self.lon0 + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.radians(self.lat0))))
        return lat, lon


def wrap180(degrees: float) -> float:
    """Any angle as an equivalent angle between -180 and 180."""
    return (degrees + 180.0) % 360.0 - 180.0
