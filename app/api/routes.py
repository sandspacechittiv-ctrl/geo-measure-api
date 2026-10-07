import shutil
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException, status
from app.config import UPLOAD_DIR, ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES
from app.api.schemas import (
    FileUploadResponse,
    FileInfoResponse,
    MeasurementsResponse,
    ProcessingStatus,
    ErrorResponse,
)
from app.storage.repository import file_repository
from app.services.file_processor import process_geospatial_file
from app.services.measurement_service import calculate_feature_measurements

logger = logging.getLogger("geo_measure_api.routes")

router = APIRouter(prefix="/api/files", tags=["Geospatial Files"])


@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process a geospatial file (.zip Shapefile or .kml)",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file format or size limit exceeded"},
        422: {"model": ErrorResponse, "description": "Failed to parse geospatial data"},
        500: {"model": ErrorResponse, "description": "Internal server processing error"},
    },
)
async def upload_file(file: UploadFile = File(...)):
    """
    Uploads a geospatial file (.zip Shapefile or .kml), processes its features,
    detects its CRS, reprojects coordinates to projected CRS (UTM), and computes feature measurements.
    """
    filename = file.filename or "uploaded_file"
    file_ext = Path(filename).suffix.lower()

    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{file_ext}'. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Create storage record
    record = file_repository.create(filename)
    saved_path = UPLOAD_DIR / f"{record.id}_{filename}"

    try:
        # Save file to upload directory
        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # File size check
        file_size = saved_path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            saved_path.unlink(missing_ok=True)
            file_repository.update_failed(record.id, "File size exceeds 50MB limit.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size exceeds maximum permitted limit of 50 MB.",
            )

        # Extract features and CRS
        features, source_crs_obj, source_crs_str = process_geospatial_file(saved_path, filename)

        # Calculate measurements in projected CRS
        measurements_resp = calculate_feature_measurements(
            features=features,
            source_crs=source_crs_obj,
            source_crs_str=source_crs_str,
            file_id=record.id,
            filename=filename,
        )

        # Update record in repository
        updated_record = file_repository.update_completed(
            record_id=record.id,
            feature_count=len(features),
            crs=source_crs_str,
            measurements=measurements_resp,
        )

        return FileUploadResponse(
            id=updated_record.id,
            filename=updated_record.filename,
            feature_count=updated_record.feature_count,
            crs=updated_record.crs,
            status=updated_record.status,
            message="Geospatial file uploaded and processed successfully.",
        )

    except HTTPException:
        raise
    except ValueError as ve:
        logger.warning(f"Validation error processing file {record.id}: {ve}")
        file_repository.update_failed(record.id, str(ve))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Geospatial processing failed: {str(ve)}",
        )
    except Exception as e:
        logger.error(f"Unexpected error processing file {record.id}: {e}", exc_info=True)
        file_repository.update_failed(record.id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An internal error occurred while processing the geospatial file: {str(e)}",
        )


@router.get(
    "/",
    response_model=List[FileInfoResponse],
    summary="List all uploaded geospatial files",
)
async def list_files():
    """
    Returns a list of all uploaded geospatial files and their current status.
    """
    records = file_repository.list_all()
    return [r.to_info_response() for r in records]


@router.get(
    "/{file_id}/",
    response_model=FileInfoResponse,
    summary="Get metadata for an uploaded geospatial file",
    responses={
        404: {"model": ErrorResponse, "description": "File record not found"},
    },
)
async def get_file_info(file_id: str):
    """
    Returns metadata about an uploaded geospatial file by ID.
    """
    record = file_repository.get(file_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with ID '{file_id}' was not found.",
        )
    return record.to_info_response()


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Get feature measurements for an uploaded file",
    responses={
        404: {"model": ErrorResponse, "description": "File record not found"},
        400: {"model": ErrorResponse, "description": "File processing has not completed successfully"},
    },
)
async def get_file_measurements(file_id: str):
    """
    Returns feature measurements (Area for Polygons, Length for LineStrings)
    reprojected to projected coordinate reference system (UTM).
    """
    record = file_repository.get(file_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with ID '{file_id}' was not found.",
        )

    if record.status == ProcessingStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File processing failed: {record.error_message}",
        )

    if record.status == ProcessingStatus.PROCESSING or record.measurements is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is still processing or measurements are unavailable.",
        )

    return record.measurements


@router.delete(
    "/{file_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an uploaded file record",
)
async def delete_file(file_id: str):
    """
    Deletes a file record and any associated uploaded binary files.
    """
    record = file_repository.get(file_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with ID '{file_id}' was not found.",
        )
    
    # Remove file from uploads folder
    for p in UPLOAD_DIR.glob(f"{file_id}_*"):
        p.unlink(missing_ok=True)

    file_repository._records.pop(file_id, None)
    return None
