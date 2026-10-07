"""Orchestrates: read file -> measure each feature -> persist."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Feature, FileStatus, UploadedFile
from .crs import crs_label
from .file_reader import FileReadError, read_upload
from .measurements import measure_geometry

log = logging.getLogger(__name__)
BATCH = 1000


def process_file(db: Session, record: UploadedFile, saved_path: Path) -> UploadedFile:
    """Fill `record` from the file at `saved_path`. Sets COMPLETED or FAILED."""
    try:
        with tempfile.TemporaryDirectory(prefix="geo_") as tmp:
            result = read_upload(saved_path, record.filename, Path(tmp))

        total = sum(len(layer.geometries) for layer in result.layers)
        if total == 0:
            raise FileReadError("File contains no features.")
        if total > settings.max_features:
            raise FileReadError(f"File has {total} features; limit is {settings.max_features}.")

        multi_layer = len(result.layers) > 1
        labels = {crs_label(layer.crs) for layer in result.layers}
        record.crs = labels.pop() if len(labels) == 1 else "MIXED"
        record.file_type = result.file_type

        index, batch = 0, []
        for layer in result.layers:
            layer_label = crs_label(layer.crs)
            for geom, gj, props in zip(layer.geometries, layer.geojson_geoms, layer.properties):
                if multi_layer:
                    props = {**props, "_layer": layer.name}
                batch.append(
                    Feature(
                        file_id=record.id,
                        index=index,
                        geometry_type=geom.geom_type if geom is not None else None,
                        geometry=gj,
                        crs=layer_label,
                        properties=props,
                        measurement=measure_geometry(geom, layer.crs),
                    )
                )
                index += 1
                if len(batch) >= BATCH:
                    db.add_all(batch)
                    db.flush()
                    batch = []
        db.add_all(batch)

        record.feature_count = index
        record.status = FileStatus.COMPLETED
        record.error = None
    except FileReadError as exc:
        db.rollback()
        _mark_failed(db, record, str(exc))
    except Exception:  # noqa: BLE001
        log.exception("Unexpected failure processing file %s", record.id)
        db.rollback()
        _mark_failed(db, record, "Unexpected error while processing the file.")
    else:
        db.commit()
    return record


def _mark_failed(db: Session, record: UploadedFile, message: str) -> None:
    record.status = FileStatus.FAILED
    record.error = message
    record.feature_count = 0
    db.add(record)
    db.commit()
