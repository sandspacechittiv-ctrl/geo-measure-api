import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_upload_kml_file():
    kml_path = SAMPLE_DIR / "survey_mixed.kml"
    with open(kml_path, "rb") as f:
        response = client.post("/api/files/", files={"file": ("survey_mixed.kml", f, "application/vnd.google-earth.kml+xml")})

    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["filename"] == "survey_mixed.kml"
    assert data["feature_count"] == 3
    assert data["status"] == "COMPLETED"

    file_id = data["id"]

    # Test GET /api/files/{id}/
    info_resp = client.get(f"/api/files/{file_id}/")
    assert info_resp.status_code == 200
    info_data = info_resp.json()
    assert info_data["id"] == file_id
    assert info_data["feature_count"] == 3

    # Test GET /api/files/{id}/measurements/
    meas_resp = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_resp.status_code == 200
    meas_data = meas_resp.json()
    assert meas_data["file_id"] == file_id
    assert meas_data["feature_count"] == 3
    assert len(meas_data["features"]) == 3

    # Polygon check
    poly_feat = next(f for f in meas_data["features"] if f["geometry_type"] == "Polygon")
    assert poly_feat["measurement"]["status"] == "OK"
    assert poly_feat["measurement"]["type"] == "area"
    assert poly_feat["measurement"]["value"] > 0

    # LineString check
    line_feat = next(f for f in meas_data["features"] if f["geometry_type"] == "LineString")
    assert line_feat["measurement"]["status"] == "OK"
    assert line_feat["measurement"]["type"] == "length"
    assert line_feat["measurement"]["value"] > 0

    # Point check
    point_feat = next(f for f in meas_data["features"] if f["geometry_type"] == "Point")
    assert point_feat["measurement"]["status"] == "NOT_REQUIRED"


def test_upload_shapefile_zip():
    zip_path = SAMPLE_DIR / "shapefile_polygons.zip"
    with open(zip_path, "rb") as f:
        response = client.post("/api/files/", files={"file": ("shapefile_polygons.zip", f, "application/zip")})

    assert response.status_code == 201
    data = response.json()
    assert data["feature_count"] == 2
    assert data["status"] == "COMPLETED"

    file_id = data["id"]
    meas_resp = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_resp.status_code == 200
    meas_data = meas_resp.json()
    assert meas_data["feature_count"] == 2


def test_upload_invalid_file_extension():
    response = client.post("/api/files/", files={"file": ("document.pdf", b"dummy content", "application/pdf")})
    assert response.status_code == 415
    data = response.json()
    assert "Unsupported file type" in data["detail"]


def test_get_nonexistent_file():
    response = client.get("/api/files/nonexistent_id/")
    assert response.status_code == 404
