"""
Geospatial Measurement Engine.

Pure functional module for computing spatial measurements (Area in m², Length in m) from Shapely geometries
and CRS definitions.

Key Rules:
1. Polygon / MultiPolygon -> Calculated Area in square meters (m²).
2. LineString / MultiLineString / LinearRing -> Calculated Length in meters (m).
3. Point / MultiPoint -> Status 'NOT_REQUIRED' (Points do not have spatial extent).
4. Unsupported / Invalid / Empty Geometries -> Handled gracefully with 'UNSUPPORTED' or 'ERROR' status.
5. Altitude (Z coordinate) is dropped (force_2d) to compute planar 2D geographic measurements.
"""
from __future__ import annotations

import numpy as np
import shapely
from pyproj import CRS
from shapely import force_2d
from shapely.geometry.base import BaseGeometry

from .crs import crs_label, get_transformer, pick_projected_crs, unit_factor_to_metre

# Geometry category mappings
AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString", "LinearRing"}
NO_MEASURE_TYPES = {"Point", "MultiPoint"}

AREA_UNIT = "square_meters"
LENGTH_UNIT = "meters"


def measure_geometry(geom: BaseGeometry | None, src_crs: CRS | None) -> dict:
    """
    Calculates measurement for a single geometry instance.

    Guarantees exception safety: per-feature errors are isolated and returned as status dictionaries.

    Args:
        geom (BaseGeometry | None): The input Shapely geometry to measure.
        src_crs (CRS | None): The native Coordinate Reference System of the geometry.

    Returns:
        dict: Measurement result dictionary containing status, measurement type, value, unit,
              projected_crs, and warning messages if applicable.
    """
    # 1. Guard against empty or missing geometry objects
    if geom is None or geom.is_empty:
        return {"status": "UNSUPPORTED", "message": "Geometry is missing or empty."}

    gtype = geom.geom_type

    # 2. Check Point / MultiPoint geometries
    if gtype in NO_MEASURE_TYPES:
        return {"status": "NOT_REQUIRED", "message": f"No measurement defined for {gtype}."}

    # 3. Check unsupported geometry types (e.g. GeometryCollection, PolyhedralSurface)
    if gtype not in AREA_TYPES | LENGTH_TYPES:
        return {"status": "UNSUPPORTED", "message": f"Measurement not supported for {gtype}."}

    # 4. Check if native CRS is present
    if src_crs is None:
        return {"status": "ERROR", "message": "Source CRS is undefined; cannot measure safely."}

    try:
        # Determine projected CRS (e.g., UTM zone) and check if transformation is required
        target, needs_transform = pick_projected_crs(geom, src_crs)

        # Force 2D geometry (strip 3D altitude / Z-coordinates common in KML)
        g = force_2d(geom)

        # Reproject geometry coordinates if source was geographic
        if needs_transform:
            tr = get_transformer(src_crs.to_wkt(), target.to_epsg())
            g = shapely.transform(g, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))

        # Linear unit conversion factor (e.g. 0.3048 for feet to meters)
        factor = unit_factor_to_metre(target)

        # Compute area (squared factor) or length (linear factor)
        if gtype in AREA_TYPES:
            value, kind, unit = g.area * (factor**2), "area", AREA_UNIT
        else:
            value, kind, unit = g.length * factor, "length", LENGTH_UNIT

        result = {
            "status": "OK",
            "type": kind,
            "value": round(float(value), 4),
            "unit": unit,
            "projected_crs": crs_label(target),
        }

        # Flag invalid polygons (e.g., self-intersecting bow-tie polygons)
        if gtype in AREA_TYPES and not geom.is_valid:
            result["message"] = "Geometry is invalid (e.g. self-intersection); area may be unreliable."

        return result

    except Exception as exc:  # Protect batch processing from individual geometry failures
        return {"status": "ERROR", "message": f"Measurement failed: {exc}"}
