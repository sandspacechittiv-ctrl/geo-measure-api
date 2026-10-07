from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .models import FileStatus


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    feature_count: int
    crs: str | None
    status: FileStatus
    error: str | None = None
    created_at: datetime


class Measurement(BaseModel):
    status: Literal["OK", "NOT_REQUIRED", "UNSUPPORTED", "ERROR"]
    type: Literal["area", "length"] | None = None
    value: float | None = None
    unit: str | None = None
    projected_crs: str | None = None
    message: str | None = None


class FeatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index: int
    geometry_type: str | None
    crs: str | None
    properties: dict[str, Any]
    geometry: dict[str, Any] | None
    measurement: Measurement


class MeasurementsOut(BaseModel):
    file_id: str
    filename: str
    crs: str | None
    feature_count: int
    total_area_sq_m: float
    total_length_m: float
    page: int
    page_size: int
    features: list[FeatureOut]
