# Geospatial File Measurement API

A production-grade, high-performance **FastAPI** backend service that accepts **Shapefile (`.zip`)** or **KML (`.kml`)** uploads, extracts geospatial features, reprojects coordinates from geographic CRS (e.g., EPSG:4326 lat/long degrees) to an automatically selected **Projected Coordinate Reference System (UTM / Polar Stereographic in meters)**, and calculates accurate spatial measurements (**Area** for Polygons, **Length** for LineStrings).

It also includes an **Interactive Web Dashboard UI** (`http://localhost:8000/`) with Leaflet.js map visualization, drag-and-drop file upload, real-time feature breakdown table, and OpenAPI/Swagger documentation (`http://localhost:8000/docs`).

---

## Quick Setup & Local Execution

### Prerequisites
- Python 3.10+ (tested on Python 3.12)
- Virtual Environment (`venv`)

### 1. Installation

Clone the repository and set up a virtual environment:

```bash
git clone <your-repository-url>
cd geo-measure-api

# Create & activate virtual environment
python -m venv .venv

# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Application Locally

Launch the Uvicorn development server:

```bash
uvicorn app.main:app --reload --port 8000
```

- **Interactive Web UI Dashboard**: [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc API Specification**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### 3. Run Automated Tests

To execute the test suite (37 unit & integration tests covering CRS transformations, KML/Shapefile parsing, measurements, and API endpoints):

```bash
pytest -v
```

---

## API Documentation

### 1. Upload & Process File
**Endpoint**: `POST /api/files/`  
**Content-Type**: `multipart/form-data`  
**Accepts**: `.kml` or `.zip` (Shapefile containing `.shp`, `.shx`, `.dbf`, and optional `.prj`)

**cURL Example**:
```bash
curl -X POST "http://localhost:8000/api/files/" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@survey_mixed.kml;type=application/vnd.google-earth.kml+xml"
```

**Example Response (`201 Created`)**:
```json
{
  "id": "e86fdf789214465198a03cc9dc2edd11",
  "filename": "survey_mixed.kml",
  "file_type": "kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error": null,
  "created_at": "2026-10-07T18:30:00.000000Z"
}
```

---

### 2. Get File Information
**Endpoint**: `GET /api/files/{id}/`

**cURL Example**:
```bash
curl -X GET "http://localhost:8000/api/files/e86fdf789214465198a03cc9dc2edd11/"
```

**Example Response (`200 OK`)**:
```json
{
  "id": "e86fdf789214465198a03cc9dc2edd11",
  "filename": "survey_mixed.kml",
  "file_type": "kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error": null,
  "created_at": "2026-10-07T18:30:00.000000Z"
}
```

---

### 3. Get Feature Measurements
**Endpoint**: `GET /api/files/{id}/measurements/`  
**Query Parameters**:
- `page` (default: 1)
- `page_size` (default: 100, max: 1000)
- `include_geometry` (default: `false`)

**cURL Example**:
```bash
curl -X GET "http://localhost:8000/api/files/e86fdf789214465198a03cc9dc2edd11/measurements/?include_geometry=true"
```

**Example Response (`200 OK`)**:
```json
{
  "file_id": "e86fdf789214465198a03cc9dc2edd11",
  "filename": "survey_mixed.kml",
  "crs": "EPSG:4326",
  "feature_count": 3,
  "total_area_sq_m": 1180570.92,
  "total_length_m": 2134.47,
  "page": 1,
  "page_size": 100,
  "features": [
    {
      "index": 0,
      "geometry_type": "Polygon",
      "crs": "EPSG:4326",
      "properties": {
        "Name": "Forest Reserve Zone A"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[13.4000, 52.5200], [13.4100, 52.5200], [13.4100, 52.5250], [13.4000, 52.5250], [13.4000, 52.5200]]]
      },
      "measurement": {
        "status": "OK",
        "type": "area",
        "value": 1180570.92,
        "unit": "square_meters",
        "projected_crs": "EPSG:32633",
        "message": null
      }
    },
    {
      "index": 1,
      "geometry_type": "LineString",
      "crs": "EPSG:4326",
      "properties": {
        "Name": "Water Transmission Line"
      },
      "geometry": null,
      "measurement": {
        "status": "OK",
        "type": "length",
        "value": 2134.47,
        "unit": "meters",
        "projected_crs": "EPSG:32633",
        "message": null
      }
    },
    {
      "index": 2,
      "geometry_type": "Point",
      "crs": "EPSG:4326",
      "properties": {
        "Name": "Sensor #101"
      },
      "geometry": null,
      "measurement": {
        "status": "NOT_REQUIRED",
        "type": "none",
        "value": 0.0,
        "unit": "none",
        "projected_crs": null,
        "message": "No measurement defined for Point."
      }
    }
  ]
}
```

---

### 4. Additional Endpoints
- `GET /api/files/{id}/features/`: Returns extracted features paginated with original GeoJSON coordinates and properties.
- `DELETE /api/files/{id}/`: Removes uploaded file and feature records from database.

---

## Architecture & System Design

```
geo-measure-api/
├── app/
│   ├── main.py              # FastAPI application entrypoint & middleware setup
│   ├── config.py            # Environment settings (upload limits, DB configuration)
│   ├── database.py          # SQLAlchemy database connection & session lifecycle
│   ├── models.py            # UploadedFile & Feature ORM database schemas
│   ├── schemas.py           # Pydantic request/response validation schemas
│   ├── api/
│   │   └── files.py         # HTTP REST route controllers
│   ├── services/
│   │   ├── file_reader.py   # Shapefile (.zip) & KML parsing + security hardening
│   │   ├── crs.py           # Native CRS detection & UTM zone reprojection selection
│   │   ├── measurements.py  # Spatial measurement logic (Area in m², Length in m)
│   │   └── processor.py     # Orchestrator (Stream file -> Read -> Reproject -> Measure -> Persist)
│   └── templates/
│       └── index.html       # Glassmorphism visual web dashboard with Leaflet.js map
├── sample_data/             # Test KML files & shapefile generator script
├── tests/                   # Full pytest suite (API, CRS, measurements, reader)
├── Dockerfile               # Production Docker deployment container
├── requirements.txt         # Dependency declarations
└── README.md
```

### File Processing Flow
1. **Upload & Validation**: `POST /api/files/` streams the uploaded file to a temporary location, enforcing strict size limits (`50 MB`), zip-slip safety, and file extension checks (`.kml`, `.zip`).
2. **Feature Extraction**: `file_reader.py` opens the KML or extracted Shapefile using GeoPandas / Pyogrio, reading every layer while handling attributes and metadata into JSON-safe dictionaries.
3. **CRS Reprojection**: `crs.py` inspects the input CRS. If geographic (e.g. `EPSG:4326`), it calculates the spatial centroid and selects the optimal **Universal Transverse Mercator (UTM)** zone (`EPSG:32601` - `32660` for North, `32701` - `32760` for South) or polar projection (`EPSG:3413` / `EPSG:3031`).
4. **Measurement Calculation**: `measurements.py` transforms geometries into projected coordinates (in meters):
   - **Polygon / MultiPolygon**: Area in square meters ($m^2$).
   - **LineString / MultiLineString**: Length in meters ($m$).
   - **Point / MultiPoint**: Marked as `NOT_REQUIRED`.
   - **Unsupported/Corrupt Geometries**: Handled gracefully (`UNSUPPORTED` / `ERROR` status) without crashing.
5. **Persistence**: Feature records and computed measurements are saved in the database with status `COMPLETED`.

---

## Technical Design Decisions & Tradeoffs

| Decision | Rationale | Alternatives Considered |
|---|---|---|
| **FastAPI Framework** | High performance, async support, automatic OpenAPI/Swagger docs, lightweight. | Django + DRF (heavier, requires GeoDjango/system GDAL C-libraries). |
| **GeoPandas + Pyogrio** | High-performance C-bindings for GDAL/OGR; handles both Shapefiles & KML natively with JSON-safe property serialization. | Hand-written XML parsing or `pyshp` (more prone to edge-case bugs and format inconsistencies). |
| **Per-Feature UTM Projection Strategy** | Guarantees high planar distance/area precision (<0.1% distortion within zone) without manual CRS parameter entry. | Calculating raw degrees (inaccurate), global Web Mercator EPSG:3857 (severe area distortion near poles). |
| **Per-Feature Error Isolation** | Ensures a single corrupt or empty geometry does not cause the entire file processing to fail. | Aborting the whole batch on first invalid feature. |
| **SQLAlchemy + SQLite Database** | Zero external dependencies, persistent, easily swappable with PostgreSQL/PostGIS via environment configuration. | In-memory only state (lost on restart). |

---

## Key Learnings & Future Scope

### Learnings
1. **CRS Handling Nuances**: Geographic coordinate systems (latitude/longitude degrees) cannot be directly used for planar area or length calculations. Converting to an appropriate projected system (like UTM) or using geodesic algorithms (via `pyproj.Geod`) is essential for real-world geospatial accuracy.
2. **Shapefile Sidecar Dependencies**: A Shapefile is a collection of files (`.shp`, `.shx`, `.dbf`, `.prj`). When `.prj` is missing, assuming a default CRS can introduce errors; explicit reporting of missing CRS maintains auditability.
3. **Zip Security**: Processing user-uploaded zip archives requires explicit zip-slip (path traversal) and zip-bomb safeguards.

### Future Scope
- **Asynchronous Task Queue**: Integrate Celery or Redis Queue (RQ) for processing multi-gigabyte geospatial datasets in background workers.
- **Additional Vector Formats**: Expand support for GeoJSON, GeoPackage (`.gpkg`), KML/KMZ archives, and FlatGeobuf.
- **Geodesic Measurement Engine**: Offer exact geodesic measurements (`pyproj.Geod`) alongside planar projected measurements.
- **Spatial Indexing & Queries**: Migrate to PostGIS to enable spatial bounding-box filtering, spatial intersects, and spatial buffering directly within SQL endpoints.
- **Export Capabilities**: Provide export endpoints for calculated measurements in CSV, GeoJSON, and Excel formats.
