"""Builds small KML / Shapefile fixtures on the fly (no binary files in git)."""
import io
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

# ~1.1km x ~1.1km square near Vijayawada, India (UTM zone 44N)
SQUARE = box(80.60, 16.50, 80.61, 16.51)
LINE = LineString([(80.60, 16.50), (80.62, 16.50)])  # ~2.1 km east-west
POINT = Point(80.65, 16.52)


def kml_text() -> str:
    def coords(geom):
        return " ".join(f"{x},{y},0" for x, y in geom.coords)

    ring = coords(SQUARE.exterior)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>Plot A</name><description>square</description>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>{ring}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  <Placemark><name>Road</name>
    <LineString><coordinates>{coords(LINE)}</coordinates></LineString></Placemark>
  <Placemark><name>Well</name>
    <Point><coordinates>{POINT.x},{POINT.y},0</coordinates></Point></Placemark>
  <Placemark><name>Mixed</name>
    <MultiGeometry><Point><coordinates>80.7,16.5,0</coordinates></Point>
    <LineString><coordinates>80.7,16.5,0 80.71,16.5,0</coordinates></LineString></MultiGeometry></Placemark>
</Document></kml>"""


def shapefile_zip_bytes(crs="EPSG:4326", include_prj=True, geoms=None) -> bytes:
    import tempfile

    geoms = geoms or [SQUARE, MultiPolygon([SQUARE, box(80.7, 16.5, 80.71, 16.51)])]
    gdf = gpd.GeoDataFrame({"name": [f"p{i}" for i in range(len(geoms))], "id": range(len(geoms))},
                           geometry=geoms, crs=crs)
    with tempfile.TemporaryDirectory() as tmp:
        shp = Path(tmp) / "plots.shp"
        gdf.to_file(shp)
        if not include_prj:
            shp.with_suffix(".prj").unlink()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for f in Path(tmp).iterdir():
                zf.write(f, f.name)
        return buf.getvalue()
