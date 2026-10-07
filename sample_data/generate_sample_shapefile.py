"""
Script to generate valid test Shapefile .zip archives in sample_data directory.
"""
import zipfile
import tempfile
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point

OUTPUT_DIR = Path(__file__).resolve().parent

def create_polygons_shapefile_zip():
    polygons = [
        Polygon([(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]),
        Polygon([(2.0, 2.0), (2.0, 4.0), (4.0, 4.0), (4.0, 2.0), (2.0, 2.0)]),
    ]
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "name": ["Plot A", "Plot B"],
            "category": ["Residential", "Commercial"],
        },
        geometry=polygons,
        crs="EPSG:4326"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        shp_path = Path(tmpdir) / "parcels.shp"
        gdf.to_file(shp_path)

        zip_path = OUTPUT_DIR / "shapefile_polygons.zip"
        with zipfile.ZipFile(zip_path, "w") as zip_out:
            for file_path in Path(tmpdir).glob("parcels.*"):
                zip_out.write(file_path, arcname=file_path.name)

    print(f"Generated: {zip_path}")


def create_linestrings_shapefile_zip():
    lines = [
        LineString([(77.59, 12.97), (77.60, 12.98), (77.61, 12.99)]),
        LineString([(77.50, 12.90), (77.55, 12.95)]),
    ]
    gdf = gpd.GeoDataFrame(
        {
            "id": [101, 102],
            "name": ["Highway 1", "Feeder Road 2"],
            "speed_limit": [80, 40],
        },
        geometry=lines,
        crs="EPSG:4326"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        shp_path = Path(tmpdir) / "roads.shp"
        gdf.to_file(shp_path)

        zip_path = OUTPUT_DIR / "shapefile_roads.zip"
        with zipfile.ZipFile(zip_path, "w") as zip_out:
            for file_path in Path(tmpdir).glob("roads.*"):
                zip_out.write(file_path, arcname=file_path.name)

    print(f"Generated: {zip_path}")


if __name__ == "__main__":
    create_polygons_shapefile_zip()
    create_linestrings_shapefile_zip()
