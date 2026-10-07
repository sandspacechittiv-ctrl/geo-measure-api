import uuid
import datetime
import threading
from typing import Dict, Optional, List
from app.api.schemas import FileInfoResponse, ProcessingStatus, MeasurementsResponse


class FileRecord:
    def __init__(
        self,
        record_id: str,
        filename: str,
        feature_count: int = 0,
        crs: str = "EPSG:4326",
        status: ProcessingStatus = ProcessingStatus.PROCESSING,
        created_at: Optional[str] = None,
        error_message: Optional[str] = None,
        measurements: Optional[MeasurementsResponse] = None,
    ):
        self.id = record_id
        self.filename = filename
        self.feature_count = feature_count
        self.crs = crs
        self.status = status
        self.created_at = created_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.error_message = error_message
        self.measurements = measurements

    def to_info_response(self) -> FileInfoResponse:
        return FileInfoResponse(
            id=self.id,
            filename=self.filename,
            feature_count=self.feature_count,
            crs=self.crs,
            status=self.status,
            created_at=self.created_at,
            error_message=self.error_message,
        )


class FileRepository:
    """Thread-safe storage repository for uploaded geospatial file records."""

    def __init__(self):
        self._records: Dict[str, FileRecord] = {}
        self._lock = threading.Lock()

    def generate_id(self) -> str:
        """Generates a clean 8-character hex ID or UUID."""
        return uuid.uuid4().hex[:8]

    def create(self, filename: str) -> FileRecord:
        with self._lock:
            record_id = self.generate_id()
            record = FileRecord(record_id=record_id, filename=filename)
            self._records[record_id] = record
            return record

    def get(self, record_id: str) -> Optional[FileRecord]:
        with self._lock:
            return self._records.get(record_id)

    def update_completed(
        self, record_id: str, feature_count: int, crs: str, measurements: MeasurementsResponse
    ) -> Optional[FileRecord]:
        with self._lock:
            record = self._records.get(record_id)
            if record:
                record.feature_count = feature_count
                record.crs = crs
                record.status = ProcessingStatus.COMPLETED
                record.measurements = measurements
                return record
            return None

    def update_failed(self, record_id: str, error_message: str) -> Optional[FileRecord]:
        with self._lock:
            record = self._records.get(record_id)
            if record:
                record.status = ProcessingStatus.FAILED
                record.error_message = error_message
                return record
            return None

    def list_all(self) -> List[FileRecord]:
        with self._lock:
            return list(self._records.values())


# Global singleton instance
file_repository = FileRepository()
