"""Reading Shapefile (zip) and KML uploads into plain feature records."""
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
    """Raised for unreadable / invalid uploads (user-facing message)."""


@dataclass
class Layer:
    name: str
    crs: CRS | None
    geometries: list            # shapely geometries (or None)
    properties: list[dict]      # JSON-safe attribute dicts
    geojson_geoms: list         # GeoJSON dicts (or None)


@dataclass
class ReadResult:
    file_type: str
    layers: list[Layer] = field(default_factory=list)


# --------------------------------------------------------------------- zip
def safe_extract_zip(zip_path: Path, dest: Path) -> list[Path]:
    """Extract a zip defensively: zip-slip, zip-bomb and absurd file counts."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise FileReadError("Upload is not a valid zip archive.") from exc

    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > 1000:
            raise FileReadError("Zip contains too many files.")
        if sum(i.file_size for i in infos) > settings.max_unzipped_bytes:
            raise FileReadError("Zip contents exceed the allowed uncompressed size.")

        dest_root = dest.resolve()
        out: list[Path] = []
        for info in infos:
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(dest_root) + os.sep):
                raise FileReadError("Zip contains an unsafe path.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            out.append(target)
        return out


# ------------------------------------------------------------------ reading
def _gdf_to_layer(name: str, gdf: gpd.GeoDataFrame, default_crs: str | None) -> Layer:
    crs = gdf.crs
    if crs is None and default_crs:
        crs = CRS.from_user_input(default_crs)

    # GeoPandas' GeoJSON writer already makes attributes JSON-safe
    # (NaN -> null, Timestamp -> ISO string, numpy scalars -> python).
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
    layers: list[Layer] = []
    try:
        names = [n for n, _ in pyogrio.list_layers(path)]
        for name in names:
            gdf = gpd.read_file(path, layer=name, engine="pyogrio")
            if len(gdf) == 0:
                continue
            layers.append(_gdf_to_layer(name, gdf, default_crs))
    except Exception as exc:  # noqa: BLE001
        raise FileReadError(f"Could not read geospatial data: {exc}") from exc
    return layers


def read_kml(path: Path) -> ReadResult:
    # KML is defined as WGS84 lon/lat, so default to EPSG:4326 if GDAL omits it.
    layers = _read_with_pyogrio(path, default_crs="EPSG:4326")
    return ReadResult("kml", layers)


def read_shapefile_zip(zip_path: Path, workdir: Path) -> ReadResult:
    files = safe_extract_zip(zip_path, workdir)
    shps = sorted(f for f in files if f.suffix.lower() == ".shp")
    if not shps:
        raise FileReadError("Zip does not contain a .shp file.")

    layers: list[Layer] = []
    for shp in shps:
        stem = shp.with_suffix("")
        have = {f.suffix.lower() for f in files if f.with_suffix("") == stem}
        missing = {".shx", ".dbf"} - have
        if missing:
            raise FileReadError(
                f"Shapefile '{shp.name}' is missing required component(s): "
                + ", ".join(sorted(missing))
            )
        layers.extend(_read_with_pyogrio(shp, default_crs=None))  # no .prj -> CRS stays None
    return ReadResult("shapefile", layers)


def read_upload(path: Path, filename: str, workdir: Path) -> ReadResult:
    ext = Path(filename).suffix.lower()
    if ext == ".kml":
        return read_kml(path)
    if ext == ".zip":
        return read_shapefile_zip(path, workdir)
    raise FileReadError("Unsupported file type. Upload a .kml or a .zip containing a Shapefile.")
