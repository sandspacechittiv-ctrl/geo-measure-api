import pytest
from pyproj import CRS
from shapely.geometry import Polygon, LineString
from app.services.crs_service import (
    parse_crs,
    calculate_utm_epsg,
    determine_projected_crs,
    transform_geometry,
)


def test_parse_crs():
    crs_obj, crs_str = parse_crs("EPSG:4326")
    assert crs_str == "EPSG:4326"
    assert crs_obj.is_geographic

    crs_obj_3857, crs_str_3857 = parse_crs("EPSG:3857")
    assert crs_str_3857 == "EPSG:3857"
    assert crs_obj_3857.is_projected


def test_calculate_utm_epsg():
    # Berlin (approx 13.40° E, 52.52° N) -> UTM Zone 33N (EPSG:32633)
    epsg_berlin = calculate_utm_epsg(13.40, 52.52)
    assert epsg_berlin == 32633

    # Bangalore (approx 77.59° E, 12.97° N) -> UTM Zone 43N (EPSG:32643)
    epsg_blr = calculate_utm_epsg(77.59, 12.97)
    assert epsg_blr == 32643

    # Sydney (approx 151.20° E, -33.86° S) -> UTM Zone 56S (EPSG:32756)
    epsg_sydney = calculate_utm_epsg(151.20, -33.86)
    assert epsg_sydney == 32756


def test_determine_projected_crs_selection():
    source_crs = CRS.from_epsg(4326)
    poly = Polygon([(77.5900, 12.9700), (77.5950, 12.9700), (77.5950, 12.9750), (77.5900, 12.9750)])
    
    proj_crs, proj_str, strategy = determine_projected_crs([poly], source_crs)
    assert proj_str == "EPSG:32643"
    assert "UTM Zone" in strategy


def test_transform_geometry():
    source_crs = CRS.from_epsg(4326)
    target_crs = CRS.from_epsg(32643)

    # 1 degree square approximately ~110km
    poly = Polygon([(77.0, 12.0), (77.1, 12.0), (77.1, 12.1), (77.0, 12.1), (77.0, 12.0)])
    reprojected = transform_geometry(poly, source_crs, target_crs)

    assert reprojected is not None
    assert reprojected.area > 100_000_000  # > 100 sq km
