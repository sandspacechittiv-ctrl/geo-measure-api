"""
Geospatial Data Extraction & Reader Module.

This module safely extracts and parses uploaded Shapefile ZIP archives and KML files into structured,
JSON-serializable feature layers.

Security Features:
1. Zip-Slip (Path Traversal) Prevention: Enforces destination root validation for extracted files.
2. Zip-Bomb Guard: Enforces strict caps on max file counts and total uncompressed file bytes.
3. Shapefile Integrity Checks: Verifies presence of mandatory sidecar files (.shp, .shx, .dbf).
"""
from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import pyogrio
from pyproj import CRS

from ..config import settings


class FileReadError(Exception):
    """Custom exception raised for unreadable, invalid, or corrupted geospatial uploads."""


@dataclass
class Layer:
    """Represents a single layer of extracted features from a geospatial dataset."""
    name: str
    crs: CRS | None
    geometries: list            # Raw Shapely geometry objects
    properties: list[dict]      # Attribute properties as JSON-serializable dictionaries
    geojson_geoms: list         # GeoJSON geometry representations


@dataclass
class ReadResult:
    """Result wrapper containing file format type and extracted layers."""
    file_type: str
    layers: list[Layer] = field(default_factory=list)


# --------------------------------------------------------------------- ZIP Security & Extraction
def safe_extract_zip(zip_path: Path, dest: Path) -> list[Path]:
    """
    Safely extracts a ZIP archive into the destination directory.

    Protections:
    - BadZipFile handling for corrupt archives.
    - Limits max file count inside zip (<= 1000).
    - Checks uncompressed size against configured limits (prevents decompression bombs).
    - Validates target paths against destination root (prevents path traversal / zip-slip attacks).
    """
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise FileReadError("Uploaded file is not a valid ZIP archive.") from exc

    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]

        # 1. Zip bomb check - file count
        if len(infos) > 1000:
            raise FileReadError("ZIP archive contains too many files (limit: 1000).")

        # 2. Zip bomb check - uncompressed size
        if sum(i.file_size for i in infos) > settings.max_unzipped_bytes:
            raise FileReadError("ZIP archive contents exceed maximum allowed uncompressed size.")

        dest_root = dest.resolve()
        out: list[Path] = []

        for info in infos:
            target = (dest / info.filename).resolve()

            # 3. Path traversal (Zip-Slip) protection
            if not str(target).startswith(str(dest_root) + os.sep):
                raise FileReadError("ZIP archive contains an unsafe relative path (zip-slip attempt).")

            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            out.append(target)

        return out


# ------------------------------------------------------------------ Geospatial Readers
def _gdf_to_layer(name: str, gdf: gpd.GeoDataFrame, default_crs: str | None) -> Layer:
    """
    Converts a GeoPandas GeoDataFrame into a structured, JSON-serializable Layer.

    GeoPandas' .to_json() automatically handles NaN values (converts to null),
    Timestamps (ISO strings), and numpy types.
    """
    crs = gdf.crs
    if crs is None and default_crs:
        crs = CRS.from_user_input(default_crs)

    # Convert to GeoJSON dictionary for clean attribute property extraction
    gj = json.loads(gdf.to_json(na="null", show_bbox=False, drop_id=True))
    feats = gj["features"]

    return Layer(
        name=name,
        crs=CRS.from_user_input(crs) if crs is not None else None,
        geometries=list(gdf.geometry),
        properties=[f["properties"] or {} for f in feats],
        geojson_geoms=[f["geometry"] for f in feats],
    )


def _read_with_pyogrio(path: Path, default_crs: str | None) -> list[Layer]:
    """
    Reads vector data layers using GDAL/Pyogrio bindings for maximum reading speed.
    """
    layers: list[Layer] = []
    try:
        names = [n for n, _ in pyogrio.list_layers(path)]
        for name in names:
            gdf = gpd.read_file(path, layer=name, engine="pyogrio")
            if len(gdf) == 0:
                continue
            layers.append(_gdf_to_layer(name, gdf, default_crs))
    except Exception as exc:  # noqa: BLE001
        raise FileReadError(f"Failed to read geospatial data: {exc}") from exc
    return layers


def read_kml(path: Path) -> ReadResult:
    """
    Reads a KML file. KML is defined by OGC specifications to use WGS84 geographic (EPSG:4326).
    """
    layers = _read_with_pyogrio(path, default_crs="EPSG:4326")
    return ReadResult("kml", layers)


def read_shapefile_zip(zip_path: Path, workdir: Path) -> ReadResult:
    """
    Extracts and reads a Shapefile ZIP archive.

    Checks:
    - Ensures at least one .shp file exists.
    - Ensures matching mandatory sidecar files (.shx index and .dbf attribute table) are present.
    """
    files = safe_extract_zip(zip_path, workdir)
    shps = sorted(f for f in files if f.suffix.lower() == ".shp")
    if not shps:
        raise FileReadError("ZIP archive does not contain a .shp Shapefile.")

    layers: list[Layer] = []
    for shp in shps:
        stem = shp.with_suffix("")
        have = {f.suffix.lower() for f in files if f.with_suffix("") == stem}
        missing = {".shx", ".dbf"} - have

        # Verify mandatory Shapefile sidecar components
        if missing:
            raise FileReadError(
                f"Shapefile '{shp.name}' is missing required component(s): "
                + ", ".join(sorted(missing))
            )

        # If .prj is missing, CRS remains None (unassigned)
        layers.extend(_read_with_pyogrio(shp, default_crs=None))

    return ReadResult("shapefile", layers)


def read_upload(path: Path, filename: str, workdir: Path) -> ReadResult:
    """
    Dispatches file parsing according to file extension (.kml or .zip).
    """
    ext = Path(filename).suffix.lower()
    if ext == ".kml":
        return read_kml(path)
    if ext == ".zip":
        return read_shapefile_zip(path, workdir)
    raise FileReadError("Unsupported file type. Please upload a .kml or a .zip containing a Shapefile.")
