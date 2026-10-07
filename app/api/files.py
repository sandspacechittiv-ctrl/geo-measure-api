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

router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_EXT = {".kml", ".zip"}
CHUNK = 1024 * 1024


def _get_file_or_404(db: Session, file_id: str) -> UploadedFile:
    rec = db.get(UploadedFile, file_id)
    if rec is None:
        raise HTTPException(404, "File not found.")
    return rec


def _require_completed(rec: UploadedFile) -> None:
    if rec.status == FileStatus.FAILED:
        raise HTTPException(409, f"File processing failed: {rec.error}")
    if rec.status != FileStatus.COMPLETED:
        raise HTTPException(409, "File is still being processed.")


async def _save_upload(upload: UploadFile, dest: Path) -> None:
    """Stream to disk, enforcing the size cap without loading it all in memory."""
    size = 0
    with open(dest, "wb") as out:
        while chunk := await upload.read(CHUNK):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise HTTPException(413, f"File exceeds {settings.max_upload_bytes} bytes.")
            out.write(chunk)
    if size == 0:
        raise HTTPException(400, "Uploaded file is empty.")


@router.post("/", response_model=FileOut, status_code=201, responses={422: {"model": FileOut}})
async def upload_file(
    file: Annotated[UploadFile, File(description="A .kml file or a .zip containing a Shapefile")],
    db: Session = Depends(get_db),
):
    """Upload and synchronously process a geospatial file."""
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() not in ALLOWED_EXT:
        raise HTTPException(415, "Unsupported file type. Upload a .kml or a .zip (Shapefile).")

    rec = UploadedFile(
        filename=filename,
        file_type="kml" if filename.lower().endswith(".kml") else "shapefile",
        status=FileStatus.PROCESSING,
    )
    db.add(rec)
    db.commit()  # persist first so a failed parse still leaves an auditable record

    with tempfile.TemporaryDirectory(prefix="upload_") as tmp:
        path = Path(tmp) / f"upload{Path(filename).suffix.lower()}"
        try:
            await _save_upload(file, path)
        except HTTPException:
            db.delete(rec)
            db.commit()
            raise
        # CPU-bound parsing; FastAPI runs this endpoint on the event loop, so
        # offload to a threadpool to keep the server responsive.
        await run_in_threadpool(process_file, db, rec, path)

    out = FileOut.model_validate(rec)
    if rec.status == FileStatus.FAILED:
        return JSONResponse(status_code=422, content=out.model_dump(mode="json"))
    return out


@router.get("/{file_id}/", response_model=FileOut)
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _get_file_or_404(db, file_id)


def _paged_features(db: Session, file_id: str, page: int, page_size: int) -> list[Feature]:
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
    """Extracted features: index, geometry type, geometry, CRS, properties."""
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
    """Per-feature measurements (paginated) plus file-level totals."""
    rec = _get_file_or_404(db, file_id)
    _require_completed(rec)

    feats = _paged_features(db, file_id, page, page_size)
    items = [FeatureOut.model_validate(f) for f in feats]
    if not include_geometry:
        for it in items:
            it.geometry = None

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
    db.delete(_get_file_or_404(db, file_id))
    db.commit()
