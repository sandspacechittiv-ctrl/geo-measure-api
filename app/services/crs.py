"""
Geospatial Coordinate Reference System (CRS) Utility Module.

This module provides helper functions to:
1. Parse and extract standardized CRS labels (e.g., 'EPSG:4326').
2. Calculate the optimal UTM (Universal Transverse Mercator) zone or UPS polar stereographic
   EPSG code for geographic coordinates to ensure high planar measurement accuracy.
3. Reproject geometries safely from geographic degrees to projected meter units.
4. Convert linear units (e.g., US Survey Feet to meters).
"""
from __future__ import annotations

import math
from functools import lru_cache

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry


def crs_label(crs: CRS | None) -> str | None:
    """
    Extracts a short, standardized authority label (e.g., 'EPSG:4326') from a pyproj CRS object.

    Args:
        crs (CRS | None): The pyproj CRS object to inspect.

    Returns:
        str | None: Standardized EPSG authority code, string representation, or 'UNKNOWN'.
    """
    if crs is None:
        return None
    auth = crs.to_authority(min_confidence=70)
    if auth:
        return f"{auth[0]}:{auth[1]}"
    return crs.name or "UNKNOWN"


def utm_epsg_for(lon: float, lat: float) -> int:
    """
    Determines the EPSG code of the WGS84 UTM zone containing the given (lon, lat) coordinate.

    UTM Zone Selection Strategy:
    - Longitude determines UTM Zone number: 1 to 60 (6-degree bands).
    - Latitude determines Northern (326xx) vs Southern (327xx) hemisphere.
    - Polar Regions (lat > 84°N or lat < -80°S) use Universal Polar Stereographic (UPS):
      - North Pole: EPSG:3413 (Arctic Polar Stereographic)
      - South Pole: EPSG:3031 (Antarctic Polar Stereographic)

    Args:
        lon (float): Longitude in decimal degrees [-180, 180].
        lat (float): Latitude in decimal degrees [-90, 90].

    Returns:
        int: Recommended projected CRS EPSG code.
    """
    if lat >= 84:
        return 3413  # Arctic Polar Stereographic
    if lat <= -80:
        return 3031  # Antarctic Polar Stereographic

    # Calculate 6-degree UTM longitude zone (1 to 60)
    zone = int(math.floor((lon + 180) / 6)) % 60 + 1

    # EPSG 326xx for Northern Hemisphere, EPSG 327xx for Southern Hemisphere
    return (32600 if lat >= 0 else 32700) + zone


@lru_cache(maxsize=256)
def get_crs(code: str) -> CRS:
    """
    Retrieves and caches a pyproj.CRS instance for the given EPSG or WKT identifier string.
    LRU cache prevents redundant CRS parsing overhead.
    """
    return CRS.from_user_input(code)


@lru_cache(maxsize=512)
def get_transformer(src_wkt: str, dst_epsg: int) -> Transformer:
    """
    Retrieves and caches a pyproj Transformer instance between source WKT and target EPSG.
    """
    return Transformer.from_crs(CRS.from_wkt(src_wkt), get_crs(f"EPSG:{dst_epsg}"), always_xy=True)


def pick_projected_crs(geom: BaseGeometry, src: CRS) -> tuple[CRS, bool]:
    """
    Determines the target projected CRS to use for area and length calculations.

    Strategy:
    1. Native Projected Source CRS: If the source is already projected (e.g. UTM, State Plane),
       measure directly in place without reprojection error.
    2. Geographic Source CRS (e.g. EPSG:4326): Compute the spatial representative point
       (centroid) of the feature, convert to WGS84 decimal degrees if necessary, and select
       the corresponding UTM zone or Polar Stereographic projection.

    Returns:
        tuple[CRS, bool]: (target_crs_object, needs_reprojection_flag)
    """
    if not src.is_geographic:
        # Native projected CRS - measure in place
        return src, False

    # Extract internal representative point (guaranteed to be inside the geometry)
    pt = geom.representative_point()
    lon, lat = pt.x, pt.y

    # If source is non-WGS84 geographic (e.g. NAD83), reproject to WGS84 to compute UTM zone
    if not src.equals(get_crs("EPSG:4326")):
        lon, lat = Transformer.from_crs(src, "EPSG:4326", always_xy=True).transform(lon, lat)

    return get_crs(f"EPSG:{utm_epsg_for(lon, lat)}"), True


def unit_factor_to_metre(crs: CRS) -> float:
    """
    Extracts the linear unit conversion factor from the target CRS to SI meters.
    Example: 0.3048 for US Survey Feet / International Feet to meters.
    """
    try:
        return float(crs.axis_info[0].unit_conversion_factor)
    except (IndexError, AttributeError, TypeError):
        return 1.0
