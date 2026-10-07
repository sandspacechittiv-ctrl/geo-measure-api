import pytest
from pyproj import CRS
from shapely.geometry import Point, Polygon, GeometryCollection

from app.services.crs import utm_epsg_for
from app.services.measurements import measure_geometry

WGS84 = CRS.from_epsg(4326)


@pytest.mark.parametrize(
    "lon,lat,epsg",
    [(80.6, 16.5, 32644), (-74.0, 40.7, 32618), (151.2, -33.9, 32756),
     (0.0, 0.0, 32631), (179.9, 10, 32660), (-179.9, 10, 32601),
     (10, 85, 3413), (10, -85, 3031)],
)
def test_utm_selection(lon, lat, epsg):
    assert utm_epsg_for(lon, lat) == epsg


def test_empty_and_none():
    assert measure_geometry(None, WGS84)["status"] == "UNSUPPORTED"
    assert measure_geometry(Polygon(), WGS84)["status"] == "UNSUPPORTED"


def test_collection_unsupported():
    assert measure_geometry(GeometryCollection([Point(0, 0)]), WGS84)["status"] == "UNSUPPORTED"


def test_invalid_polygon_flagged():
    bowtie = Polygon([(80, 16), (80.01, 16.01), (80.01, 16), (80, 16.01)])
    r = measure_geometry(bowtie, WGS84)
    assert r["status"] == "OK" and "invalid" in r["message"].lower()


def test_non_wgs84_geographic_crs():
    nad83 = CRS.from_epsg(4269)
    sq = Polygon([(-74.0, 40.7), (-73.99, 40.7), (-73.99, 40.71), (-74.0, 40.71)])
    r = measure_geometry(sq, nad83)
    assert r["status"] == "OK" and r["projected_crs"] == "EPSG:32618"
