"""CRS helpers: describing CRSs and choosing a projected CRS for measuring."""
from __future__ import annotations

import math
from functools import lru_cache

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry


def crs_label(crs: CRS | None) -> str | None:
    """Short human-readable identifier, e.g. 'EPSG:4326'."""
    if crs is None:
        return None
    auth = crs.to_authority(min_confidence=70)
    if auth:
        return f"{auth[0]}:{auth[1]}"
    return crs.name or "UNKNOWN"


def utm_epsg_for(lon: float, lat: float) -> int:
    """EPSG code of the WGS84 UTM zone containing (lon, lat).

    Beyond 84°N / 80°S UTM is undefined, so UPS polar stereographic is used
    (EPSG:3413 north, EPSG:3031 south).
    """
    if lat >= 84:
        return 3413
    if lat <= -80:
        return 3031
    zone = int(math.floor((lon + 180) / 6)) % 60 + 1
    return (32600 if lat >= 0 else 32700) + zone


@lru_cache(maxsize=256)
def get_crs(code: str) -> CRS:
    return CRS.from_user_input(code)


@lru_cache(maxsize=512)
def get_transformer(src_wkt: str, dst_epsg: int) -> Transformer:
    return Transformer.from_crs(CRS.from_wkt(src_wkt), get_crs(f"EPSG:{dst_epsg}"), always_xy=True)


def pick_projected_crs(geom: BaseGeometry, src: CRS) -> tuple[CRS, bool]:
    """Return (crs_to_measure_in, needs_transform).

    * Projected source CRS  -> measure in place (no transform, no extra error).
    * Geographic source CRS -> the UTM zone of the geometry's representative
      point. The point is first converted to WGS84 lon/lat so that non-WGS84
      geographic CRSs (NAD83, etc.) are handled too.
    """
    if not src.is_geographic:
        return src, False

    pt = geom.representative_point()
    lon, lat = pt.x, pt.y
    if not src.equals(get_crs("EPSG:4326")):
        lon, lat = Transformer.from_crs(src, "EPSG:4326", always_xy=True).transform(lon, lat)
    return get_crs(f"EPSG:{utm_epsg_for(lon, lat)}"), True


def unit_factor_to_metre(crs: CRS) -> float:
    """Linear-unit conversion factor to metres (e.g. 0.3048 for metre-feet)."""
    try:
        return float(crs.axis_info[0].unit_conversion_factor)
    except (IndexError, AttributeError, TypeError):
        return 1.0
