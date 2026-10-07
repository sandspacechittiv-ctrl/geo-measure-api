import os
import zipfile
import tempfile
import xml.etree.ElementTree as ET
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point, MultiPolygon, MultiLineString, MultiPoint, GeometryCollection, shape
from shapely.geometry.base import BaseGeometry

from app.services.crs_service import parse_crs

logger = logging.getLogger("geo_measure_api.file_processor")


class ExtractedFeature:
    def __init__(
        self,
        feature_id: Any,
        geometry_type: str,
        geometry: Optional[BaseGeometry],
        properties: Dict[str, Any],
    ):
        self.feature_id = feature_id
        self.geometry_type = geometry_type
        self.geometry = geometry
        self.properties = properties


def clean_properties(props: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures feature property values are JSON-serializable."""
    cleaned = {}
    for k, v in props.items():
        if isinstance(v, (int, float, str, bool)) or v is None:
            cleaned[str(k)] = v
        else:
            cleaned[str(k)] = str(v)
    return cleaned


def process_shapefile_zip(zip_path: Path) -> Tuple[List[ExtractedFeature], Any, str]:
    """
    Extracts a ZIP archive containing shapefile components (.shp, .dbf, .shx, .prj)
    and reads features and CRS using GeoPandas.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(tmp_path)

        # Search for .shp file recursively
        shp_files = list(tmp_path.glob("**/*.shp"))
        if not shp_files:
            raise ValueError("No .shp file found inside the uploaded ZIP archive.")

        shp_file = shp_files[0]
        logger.info(f"Processing Shapefile: {shp_file}")

        gdf = gpd.read_file(shp_file)

        raw_crs = gdf.crs
        crs_obj, crs_str = parse_crs(raw_crs)

        features = []
        for idx, row in gdf.iterrows():
            geom = row.geometry
            geom_type = geom.geom_type if geom is not None else "Unknown"
            
            # Extract non-geometry properties
            props = row.drop('geometry', errors='ignore').to_dict()
            props = clean_properties(props)

            features.append(
                ExtractedFeature(
                    feature_id=idx,
                    geometry_type=geom_type,
                    geometry=geom,
                    properties=props,
                )
            )

        return features, crs_obj, crs_str


def parse_kml_coordinates(coords_text: str) -> List[Tuple[float, float]]:
    """
    Parses a string of KML coordinates 'lon,lat,alt lon,lat,alt ...'
    into a list of (lon, lat) tuples.
    """
    coords = []
    if not coords_text:
        return coords

    # Split by whitespace or newlines
    tokens = coords_text.strip().split()
    for token in tokens:
        parts = token.strip().split(",")
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                coords.append((lon, lat))
            except ValueError:
                continue
    return coords


def parse_kml_geometry(elem: ET.Element, ns: dict) -> Optional[BaseGeometry]:
    """Recursively parses a KML geometry XML element into a Shapely geometry."""
    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

    if tag == "Point":
        coord_elem = elem.find(".//kml:coordinates", ns) or elem.find(".//coordinates")
        if coord_elem is not None and coord_elem.text:
            pts = parse_kml_coordinates(coord_elem.text)
            if pts:
                return Point(pts[0])

    elif tag == "LineString":
        coord_elem = elem.find(".//kml:coordinates", ns) or elem.find(".//coordinates")
        if coord_elem is not None and coord_elem.text:
            pts = parse_kml_coordinates(coord_elem.text)
            if len(pts) >= 2:
                return LineString(pts)

    elif tag == "Polygon":
        outer_elem = (
            elem.find(".//kml:outerBoundaryIs//kml:coordinates", ns)
            or elem.find(".//outerBoundaryIs//coordinates")
        )
        if outer_elem is not None and outer_elem.text:
            outer_pts = parse_kml_coordinates(outer_elem.text)
            if len(outer_pts) >= 3:
                inner_rings = []
                inner_elems = elem.findall(".//kml:innerBoundaryIs//kml:coordinates", ns) or elem.findall(".//innerBoundaryIs//coordinates")
                for inner_el in inner_elems:
                    if inner_el.text:
                        in_pts = parse_kml_coordinates(inner_el.text)
                        if len(in_pts) >= 3:
                            inner_rings.append(in_pts)
                return Polygon(outer_pts, holes=inner_rings)

    elif tag == "MultiGeometry":
        sub_geoms = []
        for child in elem:
            child_geom = parse_kml_geometry(child, ns)
            if child_geom:
                sub_geoms.append(child_geom)
        if sub_geoms:
            # Try combining matching geometry types if homogeneous
            geom_types = set(g.geom_type for g in sub_geoms)
            if geom_types == {"Polygon"}:
                return MultiPolygon(sub_geoms)
            elif geom_types == {"LineString"}:
                return MultiLineString(sub_geoms)
            elif geom_types == {"Point"}:
                return MultiPoint(sub_geoms)
            else:
                return GeometryCollection(sub_geoms)

    return None


def parse_kml_xml(kml_path: Path) -> List[ExtractedFeature]:
    """
    Fallback pure-Python KML XML parser using ElementTree.
    Extracts Placemarks, ExtendedData attributes, and geometries.
    """
    tree = ET.parse(kml_path)
    root = tree.getroot()

    # Extract namespace if present
    ns = {}
    if root.tag.startswith("{"):
        ns_url = root.tag.split("}")[0].strip("{")
        ns = {"kml": ns_url}

    placemarks = root.findall(".//kml:Placemark", ns) if ns else root.findall(".//Placemark")

    features = []
    for idx, pm in enumerate(placemarks):
        props = {}

        # Name and description
        name_elem = pm.find("kml:name", ns) if ns else pm.find("name")
        if name_elem is not None and name_elem.text:
            props["name"] = name_elem.text.strip()

        desc_elem = pm.find("kml:description", ns) if ns else pm.find("description")
        if desc_elem is not None and desc_elem.text:
            props["description"] = desc_elem.text.strip()

        # ExtendedData / Data / SimpleData
        ext_data = pm.find("kml:ExtendedData", ns) if ns else pm.find("ExtendedData")
        if ext_data is not None:
            # Data tags
            data_tags = ext_data.findall("kml:Data", ns) if ns else ext_data.findall("Data")
            for d in data_tags:
                key = d.attrib.get("name")
                val_el = d.find("kml:value", ns) if ns else d.find("value")
                if key and val_el is not None and val_el.text:
                    props[key] = val_el.text.strip()

            # SimpleData tags
            sdata_tags = ext_data.findall(".//kml:SimpleData", ns) if ns else ext_data.findall(".//SimpleData")
            for sd in sdata_tags:
                key = sd.attrib.get("name")
                if key and sd.text:
                    props[key] = sd.text.strip()

        # Parse Geometry inside Placemark
        geom = None
        for child in pm:
            tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag_name in ("Point", "LineString", "Polygon", "MultiGeometry"):
                geom = parse_kml_geometry(child, ns)
                if geom:
                    break

        geom_type = geom.geom_type if geom is not None else "Unknown"

        features.append(
            ExtractedFeature(
                feature_id=props.get("name", idx),
                geometry_type=geom_type,
                geometry=geom,
                properties=clean_properties(props),
            )
        )

    return features


def process_kml_file(kml_path: Path) -> Tuple[List[ExtractedFeature], Any, str]:
    """
    Processes a .kml file. Attempts GeoPandas read first, and falls back to
    robust ElementTree XML parsing if GDAL driver is unavailable.
    """
    crs_obj, crs_str = parse_crs("EPSG:4326")

    try:
        # Attempt GeoPandas first
        gdf = gpd.read_file(kml_path)
        features = []
        for idx, row in gdf.iterrows():
            geom = row.geometry
            geom_type = geom.geom_type if geom is not None else "Unknown"
            props = row.drop('geometry', errors='ignore').to_dict()
            features.append(
                ExtractedFeature(
                    feature_id=idx,
                    geometry_type=geom_type,
                    geometry=geom,
                    properties=clean_properties(props),
                )
            )
        if gdf.crs:
            crs_obj, crs_str = parse_crs(gdf.crs)
        return features, crs_obj, crs_str
    except Exception as e:
        logger.info(f"GeoPandas KML read failed or driver missing ({e}). Using pure Python KML XML parser.")
        features = parse_kml_xml(kml_path)
        return features, crs_obj, crs_str


def process_geospatial_file(file_path: Path, filename: str) -> Tuple[List[ExtractedFeature], Any, str]:
    """
    Dispatches file processing based on extension (.zip or .kml).
    """
    ext = Path(filename).suffix.lower()
    if ext == ".zip":
        return process_shapefile_zip(file_path)
    elif ext == ".kml":
        return process_kml_file(file_path)
    else:
        raise ValueError(f"Unsupported file format '{ext}'. Only .zip (Shapefile) and .kml are supported.")
