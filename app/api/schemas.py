from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from enum import Enum


class ProcessingStatus(str, Enum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FeatureStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_MEASUREMENT_REQUIRED = "NO_MEASUREMENT_REQUIRED"
    UNSUPPORTED_GEOMETRY_TYPE = "UNSUPPORTED_GEOMETRY_TYPE"
    ERROR = "ERROR"


class MeasurementDetails(BaseModel):
    type: str = Field(..., description="Measurement type e.g. 'area' or 'length'")
    value: float = Field(..., description="Calculated numerical measurement value")
    unit: str = Field(..., description="Unit of measurement e.g. 'square_meters' or 'meters'")
    formatted: Optional[str] = Field(None, description="Human-readable formatted string e.g. '15.42 hectares'")


class FeatureMeasurement(BaseModel):
    feature_id: Any = Field(..., description="Identifier or index of the feature")
    geometry_type: str = Field(..., description="Type of geometry (Polygon, LineString, Point, etc.)")
    geometry: Optional[Dict[str, Any]] = Field(None, description="GeoJSON geometry representation")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Feature attributes and properties")
    measurement: Optional[MeasurementDetails] = Field(None, description="Measurement result if applicable")
    status: FeatureStatus = Field(..., description="Processing status for this individual feature")
    message: Optional[str] = Field(None, description="Status message or error explanation if unsupported")


class FileUploadResponse(BaseModel):
    id: str = Field(..., description="Unique file identifier")
    filename: str = Field(..., description="Original name of the uploaded file")
    feature_count: int = Field(..., description="Total number of geospatial features extracted")
    crs: str = Field(..., description="Detected coordinate reference system")
    status: ProcessingStatus = Field(..., description="Overall file processing status")
    message: Optional[str] = Field(None, description="Success or info message")


class FileInfoResponse(BaseModel):
    id: str = Field(..., description="Unique file identifier")
    filename: str = Field(..., description="Original file name")
    feature_count: int = Field(..., description="Number of features contained")
    crs: str = Field(..., description="Native/detected CRS of the file")
    status: ProcessingStatus = Field(..., description="Processing status")
    created_at: str = Field(..., description="File upload timestamp")
    error_message: Optional[str] = Field(None, description="Error details if processing failed")


class MeasurementsResponse(BaseModel):
    file_id: str = Field(..., description="Unique file identifier")
    filename: str = Field(..., description="Name of the file")
    crs: str = Field(..., description="Original detected CRS")
    projected_crs: str = Field(..., description="Target projected CRS used for calculation")
    crs_strategy: str = Field(..., description="Strategy used for projected CRS selection")
    feature_count: int = Field(..., description="Total number of features")
    measured_count: int = Field(..., description="Number of features successfully measured")
    features: List[FeatureMeasurement] = Field(..., description="List of measured features")


class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Error message details")
