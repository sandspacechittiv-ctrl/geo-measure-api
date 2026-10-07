import io
import zipfile

import pytest
from pyproj import Geod
from shapely.geometry import LineString, Polygon

from . import fixtures as fx

GEOD = Geod(ellps="WGS84")


def upload(client, name, data, ctype="application/octet-stream"):
    return client.post("/api/files/", files={"file": (name, data, ctype)})


def by_index(resp_json):
    return {f["index"]: f for f in resp_json["features"]}


# ---------------------------------------------------------------- KML
def test_kml_upload_and_measurements(client):
    r = upload(client, "survey.kml", fx.kml_text().encode())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "COMPLETED"
    assert body["crs"] == "EPSG:4326"
    assert body["feature_count"] == 4
    assert body["filename"] == "survey.kml"

    info = client.get(f"/api/files/{body['id']}/").json()
    assert info["feature_count"] == 4

    m = client.get(f"/api/files/{body['id']}/measurements/").json()
    feats = by_index(m)

    # Polygon area vs. geodesic ground truth (UTM distortion << 0.1% here)
    true_area = abs(GEOD.geometry_area_perimeter(fx.SQUARE)[0])
    poly = feats[0]["measurement"]
    assert feats[0]["geometry_type"] == "Polygon"
    assert poly["status"] == "OK" and poly["type"] == "area"
    assert poly["projected_crs"] == "EPSG:32644"
    assert poly["value"] == pytest.approx(true_area, rel=1e-3)

    true_len = GEOD.geometry_length(fx.LINE)
    line = feats[1]["measurement"]
    assert line["type"] == "length" and line["unit"] == "meters"
    assert line["value"] == pytest.approx(true_len, rel=1e-3)

    assert feats[2]["measurement"]["status"] == "NOT_REQUIRED"      # Point
    assert feats[3]["measurement"]["status"] == "UNSUPPORTED"       # GeometryCollection
    assert feats[3]["geometry_type"] == "GeometryCollection"
    assert feats[0]["properties"]["Name"] == "Plot A"
    assert "geometry" in feats[0] and feats[0]["geometry"] is None  # hidden by default

    assert m["total_area_sq_m"] == pytest.approx(true_area, rel=1e-3)


def test_features_endpoint_returns_geometry(client):
    fid = upload(client, "s.kml", fx.kml_text().encode()).json()["id"]
    feats = client.get(f"/api/files/{fid}/features/").json()
    assert feats[0]["geometry"]["type"] == "Polygon"
    assert feats[0]["crs"] == "EPSG:4326"


def test_include_geometry_flag(client):
    fid = upload(client, "s.kml", fx.kml_text().encode()).json()["id"]
    m = client.get(f"/api/files/{fid}/measurements/?include_geometry=true").json()
    assert m["features"][0]["geometry"]["type"] == "Polygon"


def test_pagination(client):
    fid = upload(client, "s.kml", fx.kml_text().encode()).json()["id"]
    m = client.get(f"/api/files/{fid}/measurements/?page=2&page_size=3").json()
    assert [f["index"] for f in m["features"]] == [3]


# ---------------------------------------------------------- Shapefile
def test_shapefile_wgs84(client):
    r = upload(client, "plots.zip", fx.shapefile_zip_bytes())
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert r.json()["crs"] == "EPSG:4326"
    feats = by_index(client.get(f"/api/files/{fid}/measurements/").json())
    one = abs(GEOD.geometry_area_perimeter(fx.SQUARE)[0])
    assert feats[0]["measurement"]["value"] == pytest.approx(one, rel=1e-3)
    assert feats[1]["geometry_type"] == "MultiPolygon"
    assert feats[1]["measurement"]["value"] == pytest.approx(2 * one, rel=2e-3)
    assert feats[0]["properties"]["name"] == "p0"


def test_shapefile_already_projected_is_not_reprojected(client):
    # 100m x 200m rectangle in UTM 44N: area must be exactly 20,000 m²
    rect = Polygon([(500000, 1800000), (500100, 1800000), (500100, 1800200), (500000, 1800200)])
    r = upload(client, "utm.zip", fx.shapefile_zip_bytes(crs="EPSG:32644", geoms=[rect]))
    assert r.status_code == 201, r.text
    assert r.json()["crs"] == "EPSG:32644"
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    meas = m["features"][0]["measurement"]
    assert meas["value"] == pytest.approx(20000.0)
    assert meas["projected_crs"] == "EPSG:32644"


def test_shapefile_in_us_feet_converts_to_metres(client):
    # EPSG:2272 = NAD83 / Pennsylvania South (US survey feet)
    sq = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    r = upload(client, "ft.zip", fx.shapefile_zip_bytes(crs="EPSG:2272", geoms=[sq]))
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    # 1000 ft x 1000 ft = 1e6 ft² ≈ 92,903 m² (international ft; US survey ft differs by ~2e-6)
    assert m["features"][0]["measurement"]["value"] == pytest.approx(92903.04, rel=1e-3)


def test_shapefile_without_prj_degrades_gracefully(client):
    r = upload(client, "noprj.zip", fx.shapefile_zip_bytes(include_prj=False))
    assert r.status_code == 201
    assert r.json()["crs"] is None
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    assert m["features"][0]["measurement"]["status"] == "ERROR"
    assert "CRS" in m["features"][0]["measurement"]["message"]


# --------------------------------------------------------- Error paths
def test_unsupported_extension(client):
    assert upload(client, "a.geojson", b"{}").status_code == 415


def test_empty_file(client):
    assert upload(client, "a.kml", b"").status_code == 400


def test_corrupt_kml_is_failed_not_500(client):
    r = upload(client, "bad.kml", b"this is not xml")
    assert r.status_code == 422
    assert r.json()["status"] == "FAILED"
    fid = r.json()["id"]
    assert client.get(f"/api/files/{fid}/").json()["status"] == "FAILED"
    assert client.get(f"/api/files/{fid}/measurements/").status_code == 409


def test_zip_without_shp(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "hi")
    r = upload(client, "x.zip", buf.getvalue())
    assert r.status_code == 422 and "shp" in r.json()["error"]


def test_zip_slip_rejected(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.shp", "x")
    r = upload(client, "x.zip", buf.getvalue())
    assert r.status_code == 422 and "unsafe" in r.json()["error"]


def test_not_a_zip(client):
    r = upload(client, "x.zip", b"garbage")
    assert r.status_code == 422


def test_unknown_id_404(client):
    assert client.get("/api/files/nope/").status_code == 404
    assert client.get("/api/files/nope/measurements/").status_code == 404


def test_delete(client):
    fid = upload(client, "s.kml", fx.kml_text().encode()).json()["id"]
    assert client.delete(f"/api/files/{fid}/").status_code == 204
    assert client.get(f"/api/files/{fid}/").status_code == 404
