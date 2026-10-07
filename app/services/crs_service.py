import logging
from typing import Tuple, Optional, Any
from pyproj import CRS, Transformer
from shapely.ops import transform
import shapely.geometry

logger = logging.getLogger("geo_measure_api.crs")


def parse_crs(crs_input: Any) -> Tuple[CRS, str]:
    """
    Parses various input forms into a pyproj.CRS object.
    Returns (CRS object, CRS string identifier).
    Defaults to EPSG:4326 if unparseable or missing.
    """
    if crs_input is None:
        return CRS.from_epsg(4326), "EPSG:4326"

    try:
        if isinstance(crs_input, str):
            crs_obj = CRS.from_user_input(crs_input)
            crs_str = crs_obj.to_string()
            # If to_string is verbose WKT, try getting EPSG code if available
            epsg = crs_obj.to_epsg()
            if epsg:
                crs_str = f"EPSG:{epsg}"
            return crs_obj, crs_str
        elif isinstance(crs_input, int):
            return CRS.from_epsg(crs_input), f"EPSG:{crs_input}"
        elif isinstance(crs_input, CRS):
            epsg = crs_input.to_epsg()
            crs_str = f"EPSG:{epsg}" if epsg else crs_input.name
            return crs_input, crs_str
        else:
            crs_obj = CRS.from_user_input(str(crs_input))
            epsg = crs_obj.to_epsg()
            return crs_obj, f"EPSG:{epsg}" if epsg else "EPSG:4326"
    except Exception as e:
        logger.warning(f"Failed to parse CRS input '{crs_input}': {e}. Defaulting to EPSG:4326.")
        return CRS.from_epsg(4326), "EPSG:4326"


def calculate_utm_epsg(lon: float, lat: float) -> int:
    """
    Calculates the EPSG code for the appropriate WGS 84 UTM zone
    given a longitude and latitude.
    """
    # Normalize longitude to [-180, 180]
    lon = (lon + 180) % 360 - 180
    zone_number = int((lon + 180) / 6) + 1
    zone_number = max(1, min(60, zone_number))

    if lat >= 0:
        return 32600 + zone_number  # WGS 84 / UTM Zone XX North
    else:
        return 32700 + zone_number  # WGS 84 / UTM Zone XX South


def determine_projected_crs(
    geometries: list, source_crs: CRS
) -> Tuple[CRS, str, str]:
    """
    Determines an appropriate projected coordinate reference system (in meters)
    for geometry measurements.

    Returns:
        (target_crs_obj, target_crs_str, selection_strategy_explanation)
    """
    # If source CRS is already projected, check unit
    if source_crs.is_projected:
        axis_info = source_crs.axis_info
        unit_name = axis_info[0].unit_name.lower() if axis_info else "metre"
        if "metre" in unit_name or "meter" in unit_name or "m" == unit_name:
            epsg = source_crs.to_epsg()
            crs_str = f"EPSG:{epsg}" if epsg else source_crs.name
            return source_crs, crs_str, f"Utilizing native projected CRS ({crs_str})"

    # Collect centroids/bounds of all valid geometries to find spatial center
    valid_geoms = [g for g in geometries if g is not None and not g.is_empty]
    
    if not valid_geoms:
        # Default to UTM Zone 33N if no geometries present
        target_crs = CRS.from_epsg(32633)
        return target_crs, "EPSG:32633", "Default fallback projected CRS (EPSG:32633)"

    # Compute bounding box of all geometries
    minx, miny, maxx, maxy = None, None, None, None
    for g in valid_geoms:
        g_bounds = g.bounds
        if minx is None:
            minx, miny, maxx, maxy = g_bounds
        else:
            minx = min(minx, g_bounds[0])
            miny = min(miny, g_bounds[1])
            maxx = max(maxx, g_bounds[2])
            maxy = max(maxy, g_bounds[3])

    center_lon = (minx + maxx) / 2.0
    center_lat = (miny + maxy) / 2.0

    # Polar region check
    if center_lat > 84:
        # Arctic Polar Stereographic
        target_epsg = 3413
        strategy = f"Polar region (lat={center_lat:.2f} > 84°) -> Arctic Polar Stereographic (EPSG:3413)"
    elif center_lat < -80:
        # Antarctic Polar Stereographic
        target_epsg = 3031
        strategy = f"Polar region (lat={center_lat:.2f} < -80°) -> Antarctic Polar Stereographic (EPSG:3031)"
    else:
        # Calculate UTM Zone
        target_epsg = calculate_utm_epsg(center_lon, center_lat)
        strategy = f"Auto-selected UTM Zone for spatial centroid ({center_lon:.4f}°, {center_lat:.4f}°) -> EPSG:{target_epsg}"

    target_crs = CRS.from_epsg(target_epsg)
    return target_crs, f"EPSG:{target_epsg}", strategy


def transform_geometry(geometry: Any, source_crs: CRS, target_crs: CRS) -> Any:
    """
    Reprojects a Shapely geometry from source_crs to target_crs.
    If source_crs and target_crs are equivalent, returns geometry unchanged.
    """
    if geometry is None or geometry.is_empty:
        return geometry

    if source_crs == target_crs:
        return geometry

    try:
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        return transform(transformer.transform, geometry)
    except Exception as e:
        logger.error(f"Error transforming geometry from {source_crs} to {target_crs}: {e}")
        raise ValueError(f"Geometry transformation failed: {e}")
