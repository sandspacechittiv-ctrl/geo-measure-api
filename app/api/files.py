"""
Geospatial Files API Controller Routes.

This module handles HTTP requests for:
- POST /api/files/                -> File upload & streaming processing
- GET /api/files/{id}/            -> File status & metadata retrieval
- GET /api/files/{id}/features/   -> Paginated feature geometries and properties
- GET /api/files/{id}/measurements/ -> Per-feature measurement details (Area in m², Length in m)
- DELETE /api/files/{id}/         -> Delete uploaded file and feature records
"""
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Feature, FileStatus, UploadedFile
from ..schemas import FeatureOut, FileOut, MeasurementsOut
from ..services.processor import process_file

# Router prefix declaration
router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_EXT = {".kml", ".zip"}
CHUNK_SIZE = 1024 * 1024  # 1 MB streaming chunk size


def _get_file_or_404(db: Session, file_id: str) -> UploadedFile:
    """Helper to fetch a file record by ID or raise HTTP 404 Not Found."""
    rec = db.get(UploadedFile, file_id)
    if rec is None:
        raise HTTPException(404, f"File with ID '{file_id}' was not found.")
    return rec


def _require_completed(rec: UploadedFile) -> None:
    """Ensures file processing has completed successfully before serving features or measurements."""
    if rec.status == FileStatus.FAILED:
        raise HTTPException(409, f"File processing failed: {rec.error}")
    if rec.status != FileStatus.COMPLETED:
        raise HTTPException(409, "File is still currently processing.")


async def _save_upload(upload: UploadFile, dest: Path) -> None:
    """
    Streams file bytes to disk in 1 MB chunks to prevent RAM spikes on large uploads,
    enforcing maximum permitted size limits.
    """
    size = 0
    with open(dest, "wb") as out:
        while chunk := await upload.read(CHUNK_SIZE):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise HTTPException(413, f"Uploaded file size exceeds maximum limit of {settings.max_upload_bytes} bytes.")
            out.write(chunk)
    if size == 0:
        raise HTTPException(400, "Uploaded file is empty.")


@router.post("/", response_model=FileOut, status_code=201, responses={422: {"model": FileOut}})
async def upload_file(
    file: Annotated[UploadFile, File(description="A .kml file or a .zip containing a Shapefile")],
    db: Session = Depends(get_db),
):
    """
    Uploads and processes a geospatial file (.zip Shapefile or .kml).

    Flow:
    1. Validates file extension (.zip or .kml).
    2. Persists an initial database record with status 'PROCESSING' for auditability.
    3. Streams upload to temporary disk location.
    4. Offloads CPU-bound parsing & spatial reprojection to an asynchronous threadpool worker.
    5. Returns completed file metadata and processing status.
    """
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() not in ALLOWED_EXT:
        raise HTTPException(415, "Unsupported file type. Please upload a .kml or a .zip (Shapefile).")

    # Initialize audit record
    rec = UploadedFile(
        filename=filename,
        file_type="kml" if filename.lower().endswith(".kml") else "shapefile",
        status=FileStatus.PROCESSING,
    )
    db.add(rec)
    db.commit()

    with tempfile.TemporaryDirectory(prefix="upload_") as tmp:
        path = Path(tmp) / f"upload{Path(filename).suffix.lower()}"
        try:
            await _save_upload(file, path)
        except HTTPException:
            db.delete(rec)
            db.commit()
            raise

        # Offload heavy GIS parsing/reprojection to background threadpool
        await run_in_threadpool(process_file, db, rec, path)

    out = FileOut.model_validate(rec)
    if rec.status == FileStatus.FAILED:
        return JSONResponse(status_code=422, content=out.model_dump(mode="json"))
    return out


@router.get("/{file_id}/", response_model=FileOut)
def get_file(file_id: str, db: Session = Depends(get_db)):
    """
    Returns file metadata, feature count, native CRS, and processing status.
    """
    return _get_file_or_404(db, file_id)


def _paged_features(db: Session, file_id: str, page: int, page_size: int) -> list[Feature]:
    """Helper to query database for paginated feature records."""
    stmt = (
        select(Feature)
        .where(Feature.file_id == file_id)
        .order_by(Feature.index)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(stmt))


@router.get("/{file_id}/features/", response_model=list[FeatureOut])
def list_features(
    file_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Returns paginated list of extracted features: feature index, geometry type, GeoJSON geometry, CRS, and attributes.
    """
    _require_completed(_get_file_or_404(db, file_id))
    return _paged_features(db, file_id, page, page_size)


@router.get("/{file_id}/measurements/", response_model=MeasurementsOut)
def get_measurements(
    file_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    include_geometry: bool = Query(False, description="Include GeoJSON geometry in each feature"),
    db: Session = Depends(get_db),
):
    """
    Returns per-feature measurements (Area in m² for Polygons, Length in m for LineStrings)
    reprojected into UTM projected coordinate reference system, along with file totals.
    """
    rec = _get_file_or_404(db, file_id)
    _require_completed(rec)

    feats = _paged_features(db, file_id, page, page_size)
    items = [FeatureOut.model_validate(f) for f in feats]

    # Optionally omit bulky geometry payload to optimize response size
    if not include_geometry:
        for it in items:
            it.geometry = None

    # Calculate overall file summary totals
    total_area = total_len = 0.0
    for (m,) in db.execute(select(Feature.measurement).where(Feature.file_id == file_id)):
        if m.get("status") == "OK":
            if m["type"] == "area":
                total_area += m["value"]
            else:
                total_len += m["value"]

    return MeasurementsOut(
        file_id=rec.id,
        filename=rec.filename,
        crs=rec.crs,
        feature_count=rec.feature_count,
        total_area_sq_m=round(total_area, 4),
        total_length_m=round(total_len, 4),
        page=page,
        page_size=page_size,
        features=items,
    )


@router.delete("/{file_id}/", status_code=204)
def delete_file(file_id: str, db: Session = Depends(get_db)):
    """
    Deletes a file record and all its associated features from the database.
    """
    db.delete(_get_file_or_404(db, file_id))
    db.commit()
