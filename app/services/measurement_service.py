import logging
from typing import List, Dict, Any, Optional, Tuple
from shapely.geometry import mapping
from pyproj import CRS

from app.services.crs_service import (
    determine_projected_crs,
    transform_geometry,
)
from app.services.file_processor import ExtractedFeature
from app.api.schemas import (
    FeatureMeasurement,
    MeasurementDetails,
    FeatureStatus,
    MeasurementsResponse,
)

logger = logging.getLogger("geo_measure_api.measurement")


def format_area(area_sq_m: float) -> str:
    """Formats area in square meters into human readable text."""
    if area_sq_m >= 1_000_000:
        return f"{area_sq_m / 1_000_000:,.4f} km² ({area_sq_m:,.2f} m²)"
    elif area_sq_m >= 10_000:
        hectares = area_sq_m / 10_000
        return f"{hectares:,.2f} ha ({area_sq_m:,.2f} m²)"
    else:
        return f"{area_sq_m:,.2f} m²"


def format_length(length_m: float) -> str:
    """Formats length in meters into human readable text."""
    if length_m >= 1_000:
        return f"{length_m / 1000:,.4f} km ({length_m:,.2f} m)"
    else:
        return f"{length_m:,.2f} m"


def calculate_feature_measurements(
    features: List[ExtractedFeature],
    source_crs: CRS,
    source_crs_str: str,
    file_id: str,
    filename: str,
) -> MeasurementsResponse:
    """
    Calculates measurements for each feature by transforming geometries
    from source_crs to an appropriate projected CRS (in meters).
    """
    # Extract Shapely geometries
    geoms = [f.geometry for f in features]

    # Determine optimal projected CRS (e.g., UTM zone or local equal area)
    projected_crs_obj, projected_crs_str, crs_strategy = determine_projected_crs(
        geoms, source_crs
    )

    measured_count = 0
    feature_measurements: List[FeatureMeasurement] = []

    for feature in features:
        geom = feature.geometry
        geom_type = feature.geometry_type
        props = feature.properties
        f_id = feature.feature_id

        # GeoJSON mapping of raw geometry for output
        geojson_geom = mapping(geom) if geom is not None and not geom.is_empty else None

        if geom is None or geom.is_empty:
            feature_measurements.append(
                FeatureMeasurement(
                    feature_id=f_id,
                    geometry_type=geom_type,
                    geometry=geojson_geom,
                    properties=props,
                    measurement=None,
                    status=FeatureStatus.ERROR,
                    message="Geometry is missing or empty",
                )
            )
            continue

        # Check supported geometry types
        base_type = geom_type.replace("Multi", "")

        try:
            # Reproject geometry to projected CRS
            proj_geom = transform_geometry(geom, source_crs, projected_crs_obj)

            if base_type == "Polygon":
                area_sq_m = float(proj_geom.area)
                measured_count += 1
                feature_measurements.append(
                    FeatureMeasurement(
                        feature_id=f_id,
                        geometry_type=geom_type,
                        geometry=geojson_geom,
                        properties=props,
                        measurement=MeasurementDetails(
                            type="area",
                            value=round(area_sq_m, 4),
                            unit="square_meters",
                            formatted=format_area(area_sq_m),
                        ),
                        status=FeatureStatus.SUCCESS,
                        message=None,
                    )
                )

            elif base_type == "LineString":
                length_m = float(proj_geom.length)
                measured_count += 1
                feature_measurements.append(
                    FeatureMeasurement(
                        feature_id=f_id,
                        geometry_type=geom_type,
                        geometry=geojson_geom,
                        properties=props,
                        measurement=MeasurementDetails(
                            type="length",
                            value=round(length_m, 4),
                            unit="meters",
                            formatted=format_length(length_m),
                        ),
                        status=FeatureStatus.SUCCESS,
                        message=None,
                    )
                )

            elif base_type == "Point":
                feature_measurements.append(
                    FeatureMeasurement(
                        feature_id=f_id,
                        geometry_type=geom_type,
                        geometry=geojson_geom,
                        properties=props,
                        measurement=None,
                        status=FeatureStatus.NO_MEASUREMENT_REQUIRED,
                        message="Point geometry does not require measurement calculation",
                    )
                )

            else:
                # Unsupported geometry type (e.g. GeometryCollection, PolyhedralSurface, etc.)
                feature_measurements.append(
                    FeatureMeasurement(
                        feature_id=f_id,
                        geometry_type=geom_type,
                        geometry=geojson_geom,
                        properties=props,
                        measurement=None,
                        status=FeatureStatus.UNSUPPORTED_GEOMETRY_TYPE,
                        message=f"Measurement calculation is not supported for geometry type '{geom_type}'",
                    )
                )

        except Exception as e:
            logger.error(f"Error calculating measurement for feature {f_id}: {e}")
            feature_measurements.append(
                FeatureMeasurement(
                    feature_id=f_id,
                    geometry_type=geom_type,
                    geometry=geojson_geom,
                    properties=props,
                    measurement=None,
                    status=FeatureStatus.ERROR,
                    message=f"Failed to process feature measurement: {str(e)}",
                )
            )

    return MeasurementsResponse(
        file_id=file_id,
        filename=filename,
        crs=source_crs_str,
        projected_crs=projected_crs_str,
        crs_strategy=crs_strategy,
        feature_count=len(features),
        measured_count=measured_count,
        features=feature_measurements,
    )
