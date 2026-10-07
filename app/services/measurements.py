"""Measurement logic. Pure functions: geometry + CRS in, result dict out."""
from __future__ import annotations

import numpy as np
import shapely
from pyproj import CRS
from shapely import force_2d
from shapely.geometry.base import BaseGeometry

from .crs import crs_label, get_transformer, pick_projected_crs, unit_factor_to_metre

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString", "LinearRing"}
NO_MEASURE_TYPES = {"Point", "MultiPoint"}

AREA_UNIT = "square_meters"
LENGTH_UNIT = "meters"


def measure_geometry(geom: BaseGeometry | None, src_crs: CRS | None) -> dict:
    """Measure one geometry. Never raises: failures are reported in the result."""
    if geom is None or geom.is_empty:
        return {"status": "UNSUPPORTED", "message": "Geometry is missing or empty."}

    gtype = geom.geom_type
    if gtype in NO_MEASURE_TYPES:
        return {"status": "NOT_REQUIRED", "message": f"No measurement defined for {gtype}."}
    if gtype not in AREA_TYPES | LENGTH_TYPES:
        return {"status": "UNSUPPORTED", "message": f"Measurement not supported for {gtype}."}
    if src_crs is None:
        return {"status": "ERROR", "message": "Source CRS is undefined; cannot measure safely."}

    try:
        target, needs_transform = pick_projected_crs(geom, src_crs)
        g = force_2d(geom)  # KML carries altitude; measurements are planar
        if needs_transform:
            tr = get_transformer(src_crs.to_wkt(), target.to_epsg())
            g = shapely.transform(g, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))

        factor = unit_factor_to_metre(target)
        if gtype in AREA_TYPES:
            value, kind, unit = g.area * factor**2, "area", AREA_UNIT
        else:
            value, kind, unit = g.length * factor, "length", LENGTH_UNIT

        result = {
            "status": "OK",
            "type": kind,
            "value": round(float(value), 4),
            "unit": unit,
            "projected_crs": crs_label(target),
        }
        if gtype in AREA_TYPES and not geom.is_valid:
            result["message"] = "Geometry is invalid (e.g. self-intersection); area may be unreliable."
        return result
    except Exception as exc:  # noqa: BLE001 - one bad feature must not sink the file
        return {"status": "ERROR", "message": f"Measurement failed: {exc}"}
