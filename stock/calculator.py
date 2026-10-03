from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import warnings as python_warnings
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = Path(tempfile.gettempdir()) / "terrabovina-stock-cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
for variable in ("TMP", "TEMP", "CPL_TMPDIR", "XDG_CACHE_HOME"):
    os.environ[variable] = str(CACHE_DIR)
os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("VSI_CACHE_SIZE", "5000000")

try:
    import joblib
    import numpy as np
    import pandas as pd
    import rasterio
    from pyproj import Geod
    from rasterio.enums import Resampling
    from rasterio.mask import mask as raster_mask
    from rasterio.warp import reproject, transform_geom
    from shapely.geometry import Point, Polygon, shape
except ImportError as exc:
    print("Faltan dependencias. Ejecute primero:")
    print(r"  .\.venv\Scripts\python.exe -m pip install -r requirements.txt")
    raise SystemExit(f"Dependencia ausente: {exc}") from exc

from feature_engineering import add_agronomic_features
from .gis_utils import polygon_area_ha, resolve_gis_context
from .nearby_reference import fallback_scope
import models_utils  # noqa: F401: necesario para deserializar WeightedEnsemble


PARAMS_PATH = BASE_DIR / "data" / "parametros_regionales.json"
MODEL_PATH = BASE_DIR.parent / "modelo_final DMP" / "models" / "final_model.joblib"

MAPBIOMAS_API_BASE = "https://dev.plataforma.mapbiomas.org/api/v1/argentina"
MAPBIOMAS_URL = f"{MAPBIOMAS_API_BASE}/maps/pixel-history"
MAPBIOMAS_THEMES_URL = f"{MAPBIOMAS_API_BASE}/themes?page=1&pageSize=1000&expand=true"
STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"

MAPBIOMAS_CLASSES = {
    1: "Bosques",
    3: "Bosques cerrados",
    4: "Bosques abiertos",
    6: "Bosques inundables",
    10: "Vegetación natural herbácea y arbustiva",
    66: "Arbustales cerrados",
    77: "Arbustales abiertos",
    63: "Mosaicos de arbustos y herbáceas",
    12: "Herbáceas",
    11: "Herbaceas Inundables",
    73: "Turberas",
    14: "Áreas de uso agropecuario",
    18: "Agricultura",
    19: "Cultivos temporarios",
    36: "Cultivos perennes",
    15: "Pasturas",
    9: "Silvicultura",
    21: "Mosaico de usos",
    22: "Área sin vegetación",
    24: "Áreas urbanas",
    25: "Otras áreas no vegetadas",
    26: "Cuerpos de agua",
    34: "Hielo en superficie y nieve permanente",
    33: "Ríos, lagunas, lagos y océano",
    27: "No observado",
}
MAPBIOMAS_PIXEL_VALUES = sorted(MAPBIOMAS_CLASSES)
SCL_INVALID_CLASSES = {0, 1, 3, 8, 9, 10, 11}


class StockError(RuntimeError):
    pass


class StockInputError(StockError):
    """Entrada inválida que el cliente puede corregir."""


class StockCoverageError(StockError):
    """Cobertura observada fuera del dominio del modelo, no una falla de red."""

    def __init__(self, coverage):
        self.coverage = coverage
        super().__init__(
            f"No se puede estimar el stock: MapBiomas clasifica esta superficie como '{coverage}'. "
            "El modelo actual de stock no admite esta cobertura."
        )


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    return "_".join("".join(c for c in text if not unicodedata.combining(c)).replace("-", " ").split())


def rounded(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def http_json(
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = 45,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"User-Agent": "TerraBovina-Stock3/1.0"}
    headers.update(extra_headers or {})
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise StockError(f"HTTP {exc.code} en {url}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise StockError(f"No se pudo consultar {url}: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StockError(f"Respuesta inválida de {url}.") from exc


def validate_input(data: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    try:
        target_date = datetime.strptime(str(data["fecha"]), "%Y-%m-%d").date()
    except (KeyError, ValueError) as exc:
        raise StockInputError("El campo fecha debe tener formato YYYY-MM-DD.") from exc
    if target_date > date.today():
        raise StockInputError(f"La fecha {target_date} es futura respecto de {date.today()}.")

    geojson = data.get("geojson")
    if not isinstance(geojson, dict) or geojson.get("type") != "Polygon":
        raise StockInputError("geojson debe ser un Polygon.")
    try:
        rings = geojson['coordinates']
        if not rings or any(len(ring) < 4 or ring[0] != ring[-1] or any(len(point) != 2 for point in ring) for ring in rings):
            raise ValueError('Los anillos deben ser cerrados y tener coordenadas 2D.')
        polygon = shape(geojson)
    except Exception as exc:
        raise StockInputError(f"GeoJSON inválido: {exc}") from exc
    if not isinstance(polygon, Polygon) or polygon.is_empty or not polygon.is_valid:
        raise StockInputError("El polígono está vacío o es geométricamente inválido.")
    coordinates = list(polygon.exterior.coords)
    if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
        raise StockInputError("El anillo exterior debe estar cerrado y tener al menos cuatro coordenadas.")
    for lon, lat in coordinates:
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise StockInputError("Las coordenadas deben estar en orden longitud, latitud y dentro de rangos válidos.")

    area_ha, area_crs = polygon_area_ha(polygon)
    if area_ha <= 0.01:
        raise StockInputError("La superficie del potrero es demasiado pequeña para calcularse.")

    days = 30

    if "consumo_diario_total_kg_ms" not in data:
        raise StockInputError("Falta consumo_diario_total_kg_ms, expresado para todo el rodeo por día.")
    try:
        consumption = float(data["consumo_diario_total_kg_ms"])
    except (TypeError, ValueError) as exc:
        raise StockInputError("consumo_diario_total_kg_ms debe ser un número.") from exc
    if not math.isfinite(consumption) or isinstance(data['consumo_diario_total_kg_ms'], bool) or consumption < 0:
        raise StockInputError("consumo_diario_total_kg_ms debe ser finito y no negativo.")

    return {
        "target_date": target_date,
        "polygon": polygon,
        "geojson": geojson,
        "area_ha": area_ha,
        "area_crs": area_crs,
        "days": days,
        "consumption": consumption,
    }


def sample_polygon_points(polygon: Polygon, maximum: int = 5) -> list[tuple[float, float]]:
    points: list[Point] = [polygon.representative_point()]
    minx, miny, maxx, maxy = polygon.bounds
    for fx, fy in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75), (0.5, 0.5)):
        candidate = Point(minx + (maxx - minx) * fx, miny + (maxy - miny) * fy)
        if polygon.covers(candidate) and all(candidate.distance(p) > 1e-10 for p in points):
            points.append(candidate)
        if len(points) >= maximum:
            break
    return [(point.y, point.x) for point in points]


def fetch_mapbiomas_legend_key() -> str:
    response = http_json(
        MAPBIOMAS_THEMES_URL,
        timeout=30,
        extra_headers={"tenant-id": "mapbiomas"},
    )
    for theme in response.get("themes") or []:
        for subtheme in theme.get("subthemes") or []:
            if subtheme.get("key") == "coverage_lclu":
                legends = subtheme.get("legends") or []
                if legends and legends[0].get("key"):
                    return str(legends[0]["key"])
    raise StockError("No se encontró la leyenda pública coverage_lclu de MapBiomas Argentina.")


def fetch_mapbiomas_point(lat: float, lon: float, requested_year: int, legend_key: str) -> dict[str, Any]:
    parameters = [
        f"latitude={lat}",
        f"longitude={lon}",
        "subthemeKey=coverage_lclu",
        f"legendKey={legend_key}",
    ] + [f"pixelValue={value}" for value in MAPBIOMAS_PIXEL_VALUES]
    response = http_json(
        f"{MAPBIOMAS_URL}?{'&'.join(parameters)}",
        timeout=30,
        extra_headers={"tenant-id": "mapbiomas"},
    )
    history = response.get("history") or []
    available: list[tuple[int, int]] = []
    for item in history:
        try:
            available.append((int(item["year"]), int(item["pixelValue"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not available:
        raise StockError("MapBiomas no devolvió historia para el punto.")
    past_or_equal = [item for item in available if item[0] <= requested_year]
    chosen_year, pixel = max(past_or_equal or available, key=lambda item: item[0])
    return {
        "latitud": lat,
        "longitud": lon,
        "anio_cobertura": chosen_year,
        "codigo": pixel,
        "clase": MAPBIOMAS_CLASSES.get(pixel, f"Clase {pixel}"),
    }


def fetch_mapbiomas(polygon: Polygon, year: int) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        legend_key = fetch_mapbiomas_legend_key()
    except StockError as exc:
        return {"estado": "NO_DISPONIBLE", "clase_predominante": None, "muestras": [], "errores": [str(exc)]}
    for lat, lon in sample_polygon_points(polygon):
        try:
            samples.append(fetch_mapbiomas_point(lat, lon, year, legend_key))
        except StockError as exc:
            errors.append(str(exc))
    if not samples:
        return {"estado": "NO_DISPONIBLE", "clase_predominante": None, "muestras": [], "errores": errors}
    classes = Counter(item["clase"] for item in samples)
    predominant, count = classes.most_common(1)[0]
    years = Counter(item["anio_cobertura"] for item in samples)
    return {
        "estado": "DISPONIBLE",
        "leyenda": legend_key,
        "clase_predominante": predominant,
        "anio_predominante": years.most_common(1)[0][0],
        "proporcion_predominante": count / len(samples),
        "muestras": samples,
        "errores": errors,
    }


def point_inside_bbox(lon: float, lat: float, bbox: list[float]) -> bool:
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def select_zone_and_curves(
    lon: float,
    lat: float,
    requested_environment: str,
    params: dict[str, Any],
) -> tuple[str, dict[str, Any], list[str], str]:
    curves = params["curvas"]
    normalized = normalize_text(requested_environment or "no_se")
    if normalized not in {"no_se", "nose", "no_lo_se", "desconocido"}:
        aliases = {normalize_text(key): key for key in curves}
        aliases.update({normalize_text(value["nombre"]): key for key, value in curves.items()})
        aliases.update({normalize_text(value["id_matriz"]): key for key, value in curves.items() if value.get("id_matriz")})
        if normalized not in aliases:
            raise StockError(f"Ambiente desconocido: {requested_environment}.")
        curve_key = aliases[normalized]
        zone_key = curves[curve_key]["zona"]
        zone = params["zonas"][zone_key]
        if not point_inside_bbox(lon, lat, zone["bbox_operativo"]):
            raise StockError(f"El ambiente {curve_key} no es compatible con la ubicación según el límite operativo.")
        return zone_key, zone, [curve_key], "usuario"

    candidates = [
        (key, zone)
        for key, zone in params["zonas"].items()
        if point_inside_bbox(lon, lat, zone["bbox_operativo"])
    ]
    if not candidates:
        raise StockError("La ubicación no pertenece a una zona con curva regional disponible.")
    if len(candidates) > 1:
        candidates.sort(key=lambda pair: (pair[1]["bbox_operativo"][2] - pair[1]["bbox_operativo"][0]) * (pair[1]["bbox_operativo"][3] - pair[1]["bbox_operativo"][1]))
    zone_key, zone = candidates[0]
    return zone_key, zone, list(zone["ambientes"]), "mediana_ambientes_compatibles"


def create_segments(start_date: date, end_date: date, segment_days: int) -> list[tuple[date, date]]:
    segments: list[tuple[date, date]] = []
    current = start_date
    while current <= end_date:
        segment_end = min(end_date, current + timedelta(days=segment_days - 1))
        segments.append((current, segment_end))
        current = segment_end + timedelta(days=1)
    return segments


def stac_search(polygon: Polygon, target_date: date, params: dict[str, Any]) -> list[dict[str, Any]]:
    days_back = int(params["parametros"]["dias_busqueda_escena_hacia_atras"])
    start_date = target_date - timedelta(days=days_back)
    payload = {
        "collections": ["sentinel-2-l2a"],
        "bbox": list(polygon.bounds),
        "datetime": f"{start_date.isoformat()}T00:00:00Z/{target_date.isoformat()}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": float(params["parametros"]["nubosidad_escena_maxima_pct"])}},
        "limit": 20,
    }
    response = http_json(STAC_SEARCH_URL, payload=payload, timeout=45)
    features = response.get("features") or []
    features.sort(key=lambda item: item.get("properties", {}).get("datetime", ""), reverse=True)
    return features


def reproject_to_reference(
    source: np.ndarray,
    source_transform: Any,
    source_crs: Any,
    destination_shape: tuple[int, int],
    destination_transform: Any,
    destination_crs: Any,
    *,
    dtype: Any,
    nodata: float | int,
    resampling: Resampling,
) -> np.ndarray:
    destination = np.full(destination_shape, nodata, dtype=dtype)
    reproject(
        source=source,
        destination=destination,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=nodata,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=nodata,
        resampling=resampling,
    )
    return destination


def scene_ndvi(scene: dict[str, Any], polygon_geojson: dict[str, Any], minimum_valid: float) -> dict[str, Any]:
    assets = scene.get("assets", {})
    for key in ("red", "nir", "scl"):
        if key not in assets or "href" not in assets[key]:
            raise StockError(f"La escena {scene.get('id')} no contiene el asset {key}.")
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT="20", GDAL_HTTP_CONNECTTIMEOUT="10"):
        with rasterio.open(assets["red"]["href"]) as red_ds:
            geometry = transform_geom("EPSG:4326", red_ds.crs, polygon_geojson)
            red_masked, transform = raster_mask(red_ds, [geometry], crop=True, filled=False)
            red = red_masked[0].astype("float32").filled(np.nan)
            reference_crs = red_ds.crs

        with rasterio.open(assets["nir"]["href"]) as nir_ds:
            geometry_nir = transform_geom("EPSG:4326", nir_ds.crs, polygon_geojson)
            nir_masked, nir_transform = raster_mask(nir_ds, [geometry_nir], crop=True, filled=False)
            nir_source = nir_masked[0].astype("float32").filled(np.nan)
            if nir_source.shape == red.shape and nir_transform == transform and nir_ds.crs == reference_crs:
                nir = nir_source
            else:
                nir = reproject_to_reference(
                    nir_source,
                    nir_transform,
                    nir_ds.crs,
                    red.shape,
                    transform,
                    reference_crs,
                    dtype="float32",
                    nodata=np.nan,
                    resampling=Resampling.bilinear,
                )

        with rasterio.open(assets["scl"]["href"]) as scl_ds:
            geometry_scl = transform_geom("EPSG:4326", scl_ds.crs, polygon_geojson)
            scl_masked, scl_transform = raster_mask(scl_ds, [geometry_scl], crop=True, filled=False)
            scl_source = scl_masked[0].filled(0).astype("uint8")
            scl = reproject_to_reference(
                scl_source,
                scl_transform,
                scl_ds.crs,
                red.shape,
                transform,
                reference_crs,
                dtype="uint8",
                nodata=0,
                resampling=Resampling.nearest,
            )

    geometrically_valid = np.isfinite(red) & np.isfinite(nir) & ((red + nir) > 0)
    valid = geometrically_valid & ~np.isin(scl, list(SCL_INVALID_CLASSES))
    denominator = int(np.count_nonzero(geometrically_valid))
    valid_count = int(np.count_nonzero(valid))
    valid_fraction = valid_count / denominator if denominator else 0.0
    if valid_count < 4 or valid_fraction < minimum_valid:
        raise StockError(f"Solo {valid_fraction:.1%} de píxeles válidos dentro del potrero.")
    values = (nir[valid] - red[valid]) / (nir[valid] + red[valid] + 1e-6)
    values = values[np.isfinite(values)]
    if values.size < 4:
        raise StockError("No quedaron suficientes píxeles NDVI válidos.")
    properties = scene.get("properties", {})
    scene_date = str(properties.get("datetime", ""))[:10]
    return {
        "scene_id": scene.get("id"),
        "scene_date": scene_date,
        "nubosidad_escena_pct": float(properties.get("eo:cloud_cover", 0.0)),
        "pixeles_validos": int(values.size),
        "fraccion_pixeles_validos": float(valid_fraction),
        "nubosidad_aoi_pct": float((1.0 - valid_fraction) * 100.0),
        "ndvi_promedio": float(np.mean(values)),
        "ndvi_min": float(np.min(values)),
        "ndvi_max": float(np.max(values)),
        "ndvi_std": float(np.std(values)),
    }


def find_valid_scene(polygon: Polygon, geojson: dict[str, Any], target_date: date, params: dict[str, Any]) -> dict[str, Any]:
    check_observation_budget(params)
    scenes = stac_search(polygon, target_date, params)
    if not scenes:
        raise StockError(f"No se encontraron escenas Sentinel-2 para {target_date}.")
    errors: list[str] = []
    minimum_valid = float(params["parametros"]["pixeles_validos_minimo_fraccion"])
    for scene in scenes[:8]:
        check_observation_budget(params)
        try:
            result = scene_ndvi(scene, geojson, minimum_valid)
            result["fecha_objetivo_busqueda"] = target_date.isoformat()
            result["dias_desfase"] = (target_date - date.fromisoformat(result["scene_date"])).days
            result["escenas_descartadas_antes"] = errors
            return result
        except Exception as exc:
            errors.append(f"{scene.get('id')}: {exc}")
    raise StockError(f"Ninguna escena fue válida para {target_date}. Detalle: {' | '.join(errors[:3])}")


def fetch_weather(lat: float, lon: float, target_date: date) -> dict[str, float]:
    start_date = target_date - timedelta(days=65)
    daily_variables = [
        "temperature_2m_mean",
        "temperature_2m_min",
        "temperature_2m_max",
        "precipitation_sum",
        "shortwave_radiation_sum",
        "relative_humidity_2m_mean",
        "wind_speed_10m_max",
    ]
    url = (
        f"{OPEN_METEO_URL}?latitude={lat}&longitude={lon}"
        f"&start_date={start_date.isoformat()}&end_date={target_date.isoformat()}"
        f"&daily={','.join(daily_variables)}&timezone=auto"
    )
    response = http_json(url, timeout=45)
    daily = response.get("daily")
    if not daily or not daily.get("time"):
        raise StockError(f"Open-Meteo no devolvió clima para {target_date}.")
    frame = pd.DataFrame(daily)
    numeric = [column for column in frame.columns if column != "time"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["temperature_2m_mean", "precipitation_sum", "shortwave_radiation_sum"])
    if frame.empty:
        raise StockError(f"El clima de {target_date} no contiene filas completas.")
    row = frame.iloc[-1]

    def recent(days: int) -> pd.DataFrame:
        return frame.iloc[-days:]

    s7, s14, s30, s60 = (recent(days) for days in (7, 14, 30, 60))
    return {
        "temperatura_media_del_dia": float(row["temperature_2m_mean"]),
        "temperatura_minima_del_dia": float(row["temperature_2m_min"]),
        "temperatura_maxima_del_dia": float(row["temperature_2m_max"]),
        "precipitacion_del_dia": float(row["precipitation_sum"]),
        "radiacion_solar_del_dia": float(row["shortwave_radiation_sum"]),
        "humedad_relativa_del_dia": float(row["relative_humidity_2m_mean"]),
        "velocidad_del_viento_del_dia": float(row["wind_speed_10m_max"]),
        "precipitacion_acumulada_ultimos_7_dias": float(s7["precipitation_sum"].sum()),
        "radiacion_solar_acumulada_ultimos_7_dias": float(s7["shortwave_radiation_sum"].sum()),
        "temperatura_media_promedio_ultimos_7_dias": float(s7["temperature_2m_mean"].mean()),
        "humedad_relativa_promedio_ultimos_7_dias": float(s7["relative_humidity_2m_mean"].mean()),
        "velocidad_del_viento_promedio_ultimos_7_dias": float(s7["wind_speed_10m_max"].mean()),
        "temperatura_minima_ultimos_7_dias": float(s7["temperature_2m_min"].min()),
        "temperatura_maxima_ultimos_7_dias": float(s7["temperature_2m_max"].max()),
        "precipitacion_acumulada_ultimos_14_dias": float(s14["precipitation_sum"].sum()),
        "radiacion_solar_acumulada_ultimos_14_dias": float(s14["shortwave_radiation_sum"].sum()),
        "temperatura_media_promedio_ultimos_14_dias": float(s14["temperature_2m_mean"].mean()),
        "humedad_relativa_promedio_ultimos_14_dias": float(s14["relative_humidity_2m_mean"].mean()),
        "velocidad_del_viento_promedio_ultimos_14_dias": float(s14["wind_speed_10m_max"].mean()),
        "temperatura_minima_ultimos_14_dias": float(s14["temperature_2m_min"].min()),
        "temperatura_maxima_ultimos_14_dias": float(s14["temperature_2m_max"].max()),
        "precipitacion_acumulada_ultimos_30_dias": float(s30["precipitation_sum"].sum()),
        "radiacion_solar_acumulada_ultimos_30_dias": float(s30["shortwave_radiation_sum"].sum()),
        "temperatura_media_promedio_ultimos_30_dias": float(s30["temperature_2m_mean"].mean()),
        "humedad_relativa_promedio_ultimos_30_dias": float(s30["relative_humidity_2m_mean"].mean()),
        "velocidad_del_viento_promedio_ultimos_30_dias": float(s30["wind_speed_10m_max"].mean()),
        "temperatura_minima_ultimos_30_dias": float(s30["temperature_2m_min"].min()),
        "temperatura_maxima_ultimos_30_dias": float(s30["temperature_2m_max"].max()),
        "precipitacion_acumulada_ultimos_60_dias": float(s60["precipitation_sum"].sum()),
        "radiacion_solar_acumulada_ultimos_60_dias": float(s60["shortwave_radiation_sum"].sum()),
        "temperatura_media_promedio_ultimos_60_dias": float(s60["temperature_2m_mean"].mean()),
        "humedad_relativa_promedio_ultimos_60_dias": float(s60["relative_humidity_2m_mean"].mean()),
        "velocidad_del_viento_promedio_ultimos_60_dias": float(s60["wind_speed_10m_max"].mean()),
        "temperatura_minima_ultimos_60_dias": float(s60["temperature_2m_min"].min()),
        "temperatura_maxima_ultimos_60_dias": float(s60["temperature_2m_max"].max()),
    }


class DmpPredictor:
    def __init__(self, model_path: Path):
        if not model_path.exists():
            raise StockError(f"No existe la copia aislada del modelo DMP: {model_path}")
        with python_warnings.catch_warnings(record=True) as captured:
            python_warnings.simplefilter("always")
            artifacts = joblib.load(model_path)
        self.load_warnings = [str(item.message) for item in captured]
        self.model = artifacts["model"]
        self.encoder = artifacts["encoder"]
        self.feature_columns = artifacts["feature_columns"]
        self.cat_cols = artifacts.get("cat_cols", ["tipo_uso_suelo", "clase_cobertura_mapbiomas"])
        self.metrics = artifacts.get("metrics", {})

    def predict(
        self,
        lat: float,
        lon: float,
        scene: dict[str, Any],
        weather: dict[str, float],
        soil_use: str,
        coverage: str,
    ) -> float:
        scene_date = date.fromisoformat(scene["scene_date"])
        day_of_year = scene_date.timetuple().tm_yday
        sample = {
            "latitud": lat,
            "longitud": lon,
            "tipo_uso_suelo": soil_use,
            "clase_cobertura_mapbiomas": coverage,
            "sin_dia_del_anio": math.sin(2 * math.pi * day_of_year / 365.25),
            "cos_dia_del_anio": math.cos(2 * math.pi * day_of_year / 365.25),
            "nubosidad_pct": scene["nubosidad_escena_pct"],
            "ndvi_promedio": scene["ndvi_promedio"],
            "ndvi_min": scene["ndvi_min"],
            "ndvi_max": scene["ndvi_max"],
            "ndvi_std": scene["ndvi_std"],
            **weather,
        }
        frame = add_agronomic_features(pd.DataFrame([sample]))
        frame[self.cat_cols] = self.encoder.transform(frame[self.cat_cols])
        prediction = float(self.model.predict(frame[self.feature_columns])[0])
        if not math.isfinite(prediction):
            raise StockError("El modelo DMP devolvió un valor no finito.")
        return max(0.0, prediction)


def equivalent_date(year: int, reference: date) -> date:
    try:
        return date(year, reference.month, reference.day)
    except ValueError:
        return date(year, reference.month, 28)


def calculate_dmp_observation(
    predictor: DmpPredictor,
    polygon: Polygon,
    geojson: dict[str, Any],
    target_date: date,
    lat: float,
    lon: float,
    soil_use: str,
    coverage: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    scene = find_valid_scene(polygon, geojson, target_date, params)
    check_observation_budget(params)
    weather = fetch_weather(lat, lon, date.fromisoformat(scene["scene_date"]))
    prediction = predictor.predict(lat, lon, scene, weather, soil_use, coverage)
    return {
        "fecha_objetivo": target_date.isoformat(),
        "dmp_kg_ms_ha_dia": rounded(prediction, 3),
        "escena": {
            "id": scene["scene_id"],
            "fecha": scene["scene_date"],
            "desfase_dias": scene["dias_desfase"],
            "nubosidad_escena_pct": rounded(scene["nubosidad_escena_pct"], 2),
            "nubosidad_aoi_pct": rounded(scene["nubosidad_aoi_pct"], 2),
            "fraccion_pixeles_validos": rounded(scene["fraccion_pixeles_validos"], 4),
            "pixeles_validos": scene["pixeles_validos"],
            "ndvi_promedio": rounded(scene["ndvi_promedio"], 4),
            "ndvi_min": rounded(scene["ndvi_min"], 4),
            "ndvi_max": rounded(scene["ndvi_max"], 4),
            "ndvi_std": rounded(scene["ndvi_std"], 4),
        },
        "clima_fecha": scene["scene_date"],
    }


def check_observation_budget(params: dict[str, Any]) -> None:
    """Bound optional remote enrichment; local regional curves need no network."""
    deadline = params.get("_observation_deadline")
    if deadline is not None and time.monotonic() >= deadline:
        raise StockError("Presupuesto de consulta satelital agotado; se conserva la referencia regional.")


def reference_values_for_day(day: date, curve_keys: list[str], params: dict[str, Any]) -> tuple[float, float, float]:
    values = [float(params["curvas"][key]["mensual"][day.month - 1]) for key in curve_keys]
    return min(values), statistics.median(values), max(values)




def confidence_historical(year_count: int) -> str:
    if year_count >= 8:
        return "ALTA"
    if year_count >= 5:
        return "MEDIA"
    if year_count >= 3:
        return "BAJA"
    return "NO_DISPONIBLE"


def execute_calculation(
    input_data: dict[str, Any] | Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    params = load_json(PARAMS_PATH)
    data = input_data if isinstance(input_data, dict) else load_json(input_data)
    validated = validate_input(data, params)
    if "dias_actualizacion" in data and (type(data["dias_actualizacion"]) is not int or not 1 <= data["dias_actualizacion"] <= 5):
        raise StockInputError("dias_actualizacion debe ser un entero entre 1 y 5.")
    target_date: date = validated["target_date"]
    polygon: Polygon = validated["polygon"]
    area_ha = float(validated["area_ha"])
    representative = polygon.representative_point()
    lon, lat = representative.x, representative.y
    warnings: list[str] = []
    regional_scope = fallback_scope(polygon)
    # This is a per-request soft budget. An in-flight bounded request may finish
    # after it, but no further remote observation is started after the deadline.
    if regional_scope:
        params["_observation_deadline"] = time.monotonic() + 120

    print("Intersectando el polígono con ecorregiones IGN y unidades de vegetación...")
    try:
        gis_context = resolve_gis_context(polygon, params)
    except Exception as exc:
        raise StockError(f"No se pudo resolver el contexto GIS: {exc}") from exc
    selection = gis_context["seleccion_referencia"]
    zone_key = selection["zona_id"]
    zone = params["zonas"][zone_key]
    curve_keys = list(selection["perfiles_utilizados"])
    environment_method = selection["estado"]
    regional_transfer = environment_method == "RESPALDO_PROXIMIDAD"
    if regional_transfer:
        warnings.append(selection["justificacion"])
    area_ha = float(gis_context["superficie_ha"])
    print("Consultando la cobertura actual en MapBiomas...")
    try:
        mapbiomas = fetch_mapbiomas(polygon, target_date.year)
    except (StockError, OSError) as exc:
        if not regional_scope:
            raise
        mapbiomas = {"estado": "NO_DISPONIBLE", "clase_predominante": None, "errores": [str(exc)]}
    map_coverage = mapbiomas.get("clase_predominante")
    compatible = set(params["coberturas_forrajeras_compatibles"])
    livestock_assumption = None
    regional_only_reason = None
    agricultural_coverages = {"Áreas de uso agropecuario", "Agricultura", "Cultivos temporarios", "Cultivos perennes", "Mosaico de usos"}
    unsupported = map_coverage is not None and map_coverage not in compatible
    if map_coverage in agricultural_coverages or (regional_scope and unsupported):
        observed_coverage = map_coverage
        if unsupported and observed_coverage not in agricultural_coverages:
            regional_only_reason = f"Cobertura observada '{observed_coverage}': referencia de uso ganadero sin ajuste DMP."
        map_coverage = zone["cobertura_modelo_si_mapbiomas_no_disponible"]
        livestock_assumption = {
            "activo": True,
            "motivo": "uso_ganadero_asumido_por_el_sistema",
            "cobertura_observada": observed_coverage,
            "cobertura_referencia": map_coverage,
            "confianza": "BAJA",
            "medicion_real": False,
        }
        warnings.append(
            f"MapBiomas indica '{observed_coverage}'. Se asume uso ganadero y se calcula con la referencia regional "
            f"'{map_coverage}'. Es una estimación orientativa: no confirma la cobertura real ni mide el pasto disponible."
        )
    if map_coverage is not None and map_coverage not in compatible:
        raise StockCoverageError(map_coverage)
    if map_coverage is None:
        map_coverage = zone["cobertura_modelo_si_mapbiomas_no_disponible"]
        warnings.append(
            "MapBiomas no estuvo disponible. Para ejecutar el modelo se usó la cobertura natural inferida por el perfil regional; no es una detección observada."
        )

    from stock.seasonal_window import seasonal_window
    window = seasonal_window(target_date, map_coverage)
    validated["days"] = window["dias"]
    if "dias_actualizacion" in data:
        days_update = data["dias_actualizacion"]
        if type(days_update) is not int or not 1 <= days_update <= 5:
            raise StockInputError("dias_actualizacion debe ser un entero entre 1 y 5.")
        validated["days"] = days_update
        window["dias"] = days_update
        window["criterio"] = "actualizacion_incremental"
    start_date = target_date - timedelta(days=validated["days"] - 1)
    if not window["cobertura_reconocida"]:
        warnings.append("Ventana estacional: cobertura sin equivalencia explícita; se aplica el perfil pastizal natural.")
    print("Cargando la copia aislada del modelo DMP...")
    predictor = None
    if not regional_only_reason:
        try:
            predictor = DmpPredictor(MODEL_PATH)
        except (StockError, OSError) as exc:
            if not regional_scope:
                raise
            regional_only_reason = f"Modelo DMP no disponible: {exc}"
    segments = create_segments(start_date, target_date, int(params["parametros"]["dias_periodo_dmp"]))
    historical_start = int(params["parametros"]["anio_historico_inicio"])
    historical_years = list(range(historical_start, target_date.year))
    minimum_years = int(params["parametros"]["min_anios_historicos"])
    period_results: list[dict[str, Any]] = []
    total_gross = {"min": 0.0, "central": 0.0, "max": 0.0}
    total_usable = {"min": 0.0, "central": 0.0, "max": 0.0}
    total_reference = {"min": 0.0, "central": 0.0, "max": 0.0}
    utilization = float(params["parametros"]["porcentaje_utilizable_pastizal_natural"])
    clipped_any = False

    # Spend the optional observation budget on the most recent growth first.
    for period_index, (period_start, period_end) in reversed(list(enumerate(segments, 1))):
        print(f"Procesando período {period_index}/{len(segments)}: {period_start} -> {period_end}")
        current = None
        fallback_reason = regional_only_reason
        history: list[dict[str, Any]] = []
        history_errors: list[dict[str, str]] = []
        if not fallback_reason:
            try:
                check_observation_budget(params)
                current = calculate_dmp_observation(
                    predictor, polygon, validated["geojson"], period_end, lat, lon,
                    zone["tipo_uso_suelo_modelo"], map_coverage, params,
                )
            except (StockError, OSError) as exc:
                if not regional_scope:
                    raise
                fallback_reason = str(exc)
        for year in historical_years if not fallback_reason else []:
            historical_target = equivalent_date(year, period_end)
            try:
                check_observation_budget(params)
                observation = calculate_dmp_observation(
                    predictor, polygon, validated["geojson"], historical_target, lat, lon,
                    zone["tipo_uso_suelo_modelo"], map_coverage, params,
                )
                observation["anio"] = year
                history.append(observation)
                print(f"  Histórico {year}: {observation['dmp_kg_ms_ha_dia']:.2f} kg MS/ha/día")
            except Exception as exc:
                history_errors.append({"anio": str(year), "error": str(exc)})
                print(f"  Histórico {year}: no disponible")
        historical_median = statistics.median(item["dmp_kg_ms_ha_dia"] for item in history) if history else None
        if not fallback_reason and (len(history) < minimum_years or historical_median <= 0):
            fallback_reason = f"Histórico DMP insuficiente o no positivo: {len(history)} años válidos; mínimo {minimum_years}."
            if not regional_scope:
                raise StockError(fallback_reason)
        # Neutral multiplier means regional seasonal expectation, NOT an
        # invented NDVI, measured DMP, or proof of normal current conditions.
        original_factor = None if fallback_reason else current["dmp_kg_ms_ha_dia"] / historical_median
        applied_factor = 1.0 if fallback_reason else min(
            float(params["parametros"]["factor_dmp_maximo"]),
            max(float(params["parametros"]["factor_dmp_minimo"]), original_factor),
        )
        clipped = original_factor is not None and not math.isclose(original_factor, applied_factor, rel_tol=1e-9)
        clipped_any = clipped_any or clipped
        if clipped:
            warnings.append(
                f"El factor DMP {original_factor:.2f} del período terminado {period_end} fue limitado a {applied_factor:.2f}."
            )

        period_gross = {"min": 0.0, "central": 0.0, "max": 0.0}
        daily_references: list[dict[str, Any]] = []
        day_cursor = period_start
        while day_cursor <= period_end:
            reference_min, reference_central, reference_max = reference_values_for_day(day_cursor, curve_keys, params)
            for key, reference in (("min", reference_min), ("central", reference_central), ("max", reference_max)):
                corrected = reference * applied_factor
                total_reference[key] += reference
                period_gross[key] += corrected
                total_gross[key] += corrected
                total_usable[key] += corrected * utilization
            daily_references.append({
                "fecha": day_cursor.isoformat(),
                "referencia_min": reference_min,
                "referencia_central": reference_central,
                "referencia_max": reference_max,
            })
            day_cursor += timedelta(days=1)

        period_days = (period_end - period_start).days + 1
        period_results.append({
            "periodo": period_index,
            "fecha_inicio": period_start.isoformat(),
            "fecha_fin": period_end.isoformat(),
            "dias": period_days,
            "metodo_crecimiento": "REFERENCIA_REGIONAL" if fallback_reason else "REFERENCIA_AJUSTADA_DMP",
            "motivo_respaldo": fallback_reason,
            "dmp_actual": current,
            "dmp_historico": {
                "metodo": "mediana_mismo_modelo_misma_epoca",
                "mediana_kg_ms_ha_dia": rounded(historical_median, 3),
                "cantidad_anios_validos": len(history),
                "observaciones": history,
                "errores": history_errors,
            },
            "factor_dmp_original": rounded(original_factor, 4),
            "factor_dmp_aplicado": rounded(applied_factor, 4),
            "factor_limitado": clipped,
            "referencia_regional_promedio_kg_ms_ha_dia": {
                key: rounded(sum(item[f"referencia_{key}"] for item in daily_references) / period_days, 3)
                for key in ("min", "central", "max")
            },
            "crecimiento_bruto_corregido_promedio_kg_ms_ha_dia": {
                key: rounded(period_gross[key] / period_days, 3) for key in period_gross
            },
            "crecimiento_utilizable_promedio_kg_ms_ha_dia": {
                key: rounded(period_gross[key] * utilization / period_days, 3) for key in period_gross
            },
            "produccion_bruta_periodo_kg_ms_ha": {key: rounded(value, 2) for key, value in period_gross.items()},
            "produccion_utilizable_periodo_kg_ms_ha": {
                key: rounded(value * utilization, 2) for key, value in period_gross.items()
            },
            "referencias_diarias": daily_references,
        })

    period_results.sort(key=lambda period: period["periodo"])
    # El campo histórico 'stock inicial' ahora representa producción antes del consumo.
    initial = dict(total_usable)
    initial_metadata = {
        "estado": "PRODUCCION_ACUMULADA_ESTIMADA",
        "metodo": "suma_produccion_utilizable_bloques_5_dias",
        "descripcion": "Suma del crecimiento utilizable por los días reales de cada bloque; no es biomasa medida al comienzo de la ventana.",
        "confianza": "BAJA",
        "medicion_real": False,
        "biomasa_previa_asumida_kg_ms_ha": 0,
    }
    warnings.append(
        "El stock se estima con producción de la ventana menos consumo, sin biomasa previa ni otras pérdidas explícitas; no es un aforo."
    )
    consumption_total_daily = validated["consumption"]
    consumption_per_ha_daily = consumption_total_daily / area_ha
    consumption_total_window = consumption_total_daily * validated["days"]
    consumption_per_ha_window = consumption_per_ha_daily * validated["days"]
    pre_clamp = {
        key: initial[key] - consumption_per_ha_window
        for key in ("min", "central", "max")
    }
    final_stock = {key: max(0.0, value) for key, value in pre_clamp.items()}
    unmet = {key: max(0.0, -value) for key, value in pre_clamp.items()}

    history_counts = [period["dmp_historico"]["cantidad_anios_validos"] for period in period_results]
    historical_confidence = confidence_historical(min(history_counts))
    fallback_periods = [p for p in period_results if p["motivo_respaldo"]]
    environmental_confidence = "BAJA" if livestock_assumption or fallback_periods else selection["confianza_ambiental"]
    satellite_values = [p["dmp_actual"]["escena"]["fraccion_pixeles_validos"] for p in period_results if p["dmp_actual"]]
    satellite_quality = min(satellite_values) if satellite_values else 0
    satellite_confidence = "NO_DISPONIBLE" if not satellite_values else "BAJA" if fallback_periods else "ALTA" if satellite_quality >= 0.8 else "MEDIA" if satellite_quality >= 0.5 else "BAJA"
    if fallback_periods:
        warnings.append(f"{len(fallback_periods)} períodos usan la curva regional sin ajuste DMP; no hay observación suficiente para inferir la anomalía actual.")
    status = "COHERENTE"
    if predictor and predictor.load_warnings:
        warnings.append(
            "La carga del artefacto emitió una advertencia de compatibilidad de XGBoost; las predicciones se generaron, pero conviene reexportar el modelo con un formato estable."
        )
    if warnings or environmental_confidence == "BAJA" or historical_confidence == "BAJA" or clipped_any:
        status = "REVISAR"

    curve_metadata = []
    for key in curve_keys:
        curve = params["curvas"][key]
        curve_metadata.append({
            "id": key,
            "id_matriz": curve.get("id_matriz"),
            "nombre": curve["nombre"],
            "valores_mensuales_kg_ms_ha_dia": curve["mensual"],
            "total_anual_kg_ms_ha": curve["total_anual_kg_ms_ha"],
            "promedio_anual_kg_ms_ha_dia": curve["promedio_anual_kg_ms_ha_dia"],
            "fuente": curve["fuente"],
            "tipo_fuente": curve["tipo_fuente"],
            "relacion_verano_invierno": curve.get("relacion_verano_invierno"),
            "advertencia": curve.get("advertencia"),
        })

    output = {
        "estado": "OK",
        "generado_en": datetime.now().astimezone().isoformat(timespec="seconds"),
        "metodologia": "gis_dmp_balance_estacional_respaldo_regional_v3",
        "respaldo_estimacion": {
            "activo": bool(fallback_periods), "version": "nea_litoral_pampa_ba_regional_sin_observacion_v2",
            "provincias": regional_scope or [], "periodos_regionales": len(fallback_periods),
            "periodos_ajustados_dmp": len(period_results) - len(fallback_periods),
            "medicion_real": False, "validacion_local": False,
            "criterio": "curva_regional_estacional_sin_anomalia_cuando_falta_observacion",
        },
        "supuesto_uso_ganadero": livestock_assumption,
        "ventana_estacional": window,
        "potrero": {
            "nombre": data.get("nombre_potrero", "Potrero sin nombre"),
            "fecha_objetivo": target_date.isoformat(),
            "fecha_inicio": start_date.isoformat(),
            "dias_calculo": validated["days"],
            "centroide_representativo": {"latitud": rounded(lat, 7), "longitud": rounded(lon, 7)},
            "superficie_ha": rounded(area_ha, 3),
        },
        "contexto_gis": gis_context,
        "seleccion_referencia": selection,
        "ubicacion_y_ambiente": {
            "zona_id": zone_key,
            "zona_nombre": zone["nombre"],
            "seleccion_ambiente": "automatico_gis",
            "ambiente_solicitado": None,
            "ambientes_considerados": curve_keys,
            "mapbiomas": mapbiomas,
            "cobertura_enviada_al_modelo": map_coverage,
            "limite_geografico": "interseccion_ign_oyarzabal_poligono_completo",
            "advertencia_geografica": selection["justificacion"],
        },
        "referencias_regionales": curve_metadata,
        "fuente_matriz_referencias": params.get("fuente_matriz_referencias"),
        "dmp": {
            "uso": "corrector_relativo_no_valor_absoluto_de_forraje",
            "modelo_archivo": str(MODEL_PATH),
            "modelo_sha256": sha256_file(MODEL_PATH) if predictor else None,
            "metricas_oof_del_artefacto": {key: rounded(value, 4) for key, value in predictor.metrics.items()} if predictor else {},
            "advertencias_carga_artefacto": predictor.load_warnings if predictor else [],
            "nota_metricas": "Las metricas OOF pertenecen al dataset del modelo y no validan este potrero ni el stock final.",
            "periodos": period_results,
        },
        "crecimiento": {
            "unidad": "kg MS/ha/dia",
            "porcentaje_utilizable_aplicado": utilization * 100.0,
            "descripcion": "Curva regional estacional; ajuste DMP solo en períodos con observaciones e historia suficientes.",
            "crecimiento_regional_normal_promedio_kg_ms_ha_dia": {
                key: rounded(total_reference[key] / validated["days"], 3) for key in total_reference
            },
            "crecimiento_bruto_promedio_kg_ms_ha_dia": {
                key: rounded(total_gross[key] / validated["days"], 3) for key in total_gross
            },
            "crecimiento_utilizable_promedio_kg_ms_ha_dia": {
                key: rounded(total_usable[key] / validated["days"], 3) for key in total_usable
            },
            "produccion_bruta_acumulada_kg_ms_ha": {key: rounded(value, 2) for key, value in total_gross.items()},
            "produccion_utilizable_acumulada_kg_ms_ha": {key: rounded(value, 2) for key, value in total_usable.items()},
            "produccion_bruta_total_potrero_kg_ms": {
                key: rounded(value * area_ha, 2) for key, value in total_gross.items()
            },
            "produccion_utilizable_total_potrero_kg_ms": {
                key: rounded(value * area_ha, 2) for key, value in total_usable.items()
            },
            "comparacion_con_referencia": {
                "factor_efectivo_ventana": rounded(total_gross["central"] / total_reference["central"], 4) if total_reference["central"] > 0 else None,
                "variacion_porcentual": rounded((total_gross["central"] / total_reference["central"] - 1.0) * 100.0, 2) if total_reference["central"] > 0 and not fallback_periods else None,
                "interpretacion": "Valor negativo indica crecimiento estimado por debajo de la referencia regional normal; positivo indica por encima."
            },
        },
        "stock_inicial_estimado": {
            **initial_metadata,
            "valor_kg_ms_ha": {key: rounded(value, 2) for key, value in initial.items()},
        },
        "consumo": {
            "fuente": "informado_por_usuario",
            "diario_total_potrero_kg_ms": rounded(consumption_total_daily, 2),
            "diario_kg_ms_ha": rounded(consumption_per_ha_daily, 3),
            "acumulado_total_potrero_kg_ms": rounded(consumption_total_window, 2),
            "acumulado_kg_ms_ha": rounded(consumption_per_ha_window, 2),
        },
        "stock_final_utilizable": {
            "unidad": "kg MS/ha",
            "valor_kg_ms_ha": {key: rounded(value, 2) for key, value in final_stock.items()},
            "total_potrero_kg_ms": {key: rounded(value * area_ha, 2) for key, value in final_stock.items()},
            "formula": "max(0, produccion_utilizable_ventana - consumo_ventana)",
        },
        "balance_stock": {
            "tipo_stock": "materia_seca_utilizable_estimada",
            "stock_inicial_fuente": initial_metadata["metodo"],
            "stock_inicial_kg_ms_ha": {key: rounded(value, 2) for key, value in initial.items()},
            "stock_inicial_estimado": {
                **initial_metadata,
                "valor_kg_ms_ha": {key: rounded(value, 2) for key, value in initial.items()},
            },
            "consumo": {
                "fuente": data.get("consumo_fuente", "informado_por_usuario" if "consumo_diario_total_kg_ms" in data else "no_informado_asumido_cero"),
                "diario_total_potrero_kg_ms": rounded(consumption_total_daily, 2),
                "diario_kg_ms_ha": rounded(consumption_per_ha_daily, 3),
                "acumulado_total_potrero_kg_ms": rounded(consumption_total_window, 2),
                "acumulado_kg_ms_ha": rounded(consumption_per_ha_window, 2),
            },
            "formula": "produccion_utilizable_ventana - consumo_ventana; resultado limitado a cero",
            "stock_final_antes_de_limitar_kg_ms_ha": {key: rounded(value, 2) for key, value in pre_clamp.items()},
            "stock_final_utilizable_kg_ms_ha": {key: rounded(value, 2) for key, value in final_stock.items()},
            "stock_final_utilizable_total_potrero_kg_ms": {
                key: rounded(value * area_ha, 2) for key, value in final_stock.items()
            },
            "demanda_no_cubierta_kg_ms_ha": {key: rounded(value, 2) for key, value in unmet.items()},
        },
        "coherencia": {
            "estado": status,
            "crecimiento": "Comparado con las curvas mensuales regionales entregadas y corregido solo por la anomalia DMP limitada.",
            "stock": "El balance funciona, pero el stock inicial automático es todavía un proxy de prueba y no una medición de campo ni un modelo de biomasa validado.",
            "confianza_geografica": selection["confianza_geografica"],
            "confianza_ambiental": environmental_confidence,
            "confianza_satelital": satellite_confidence,
            "confianza_historica": historical_confidence,
            "aplicabilidad_modelo": "MEDIA" if not fallback_periods and not livestock_assumption and not regional_transfer and zone_key in {"corrientes", "entre_rios_norte", "buenos_aires_ne", "buenos_aires_centro"} else "BAJA",
            "advertencias": warnings,
        },
        "limitaciones": [
            "DMP representa productividad vegetal y se usa solo como anomalia relativa; no equivale directamente a forraje consumible.",
            "MapBiomas no distingue pastos cortos, malezal, pajonal y flechillar.",
            "La selección regional usa ecorregiones IGN/ANIDA y unidades de vegetación de Oyarzabal; cuando esas capas no distinguen la comunidad se conserva la mediana y el rango de perfiles compatibles.",
            "El 50 por ciento utilizable y el prior del stock inicial son parámetros operativos configurables.",
            "El stock inicial automático actual es un proxy explícitamente no validado; se necesita una base de aforos para convertirlo en un modelo defendible.",
            "La estimacion no reemplaza un aforo de campo.",
        ],
    }
    if output_path is not None:
        write_json(output_path, output)
    return output


def print_summary(output: dict[str, Any], output_path: Path) -> None:
    growth = output["crecimiento"]
    stock = output["balance_stock"]
    print("\n" + "=" * 68)
    print("TERRABOVINA - ESTIMACION REGIONAL DE STOCK UTILIZABLE")
    print("=" * 68)
    print(f"Potrero:        {output['potrero']['nombre']}")
    print(f"Zona:           {output['ubicacion_y_ambiente']['zona_nombre']}")
    ecos = output["contexto_gis"]["ecorregiones"]
    units = output["contexto_gis"]["unidades_vegetacion"]
    if ecos:
        print(f"Ecorregión:     {ecos[0]['nombre']} ({ecos[0]['porcentaje_superficie']:.1f}%)")
    if units:
        print(f"Vegetación:     {units[0]['codigo']} - {units[0]['nombre_vulgar']} ({units[0]['porcentaje_superficie']:.1f}%)")
    print(f"Ventana:        {output['potrero']['fecha_inicio']} -> {output['potrero']['fecha_objetivo']}")
    print(f"Superficie:     {output['potrero']['superficie_ha']:.3f} ha")
    print(f"Ambientes:      {', '.join(output['ubicacion_y_ambiente']['ambientes_considerados'])}")
    print("\nCRECIMIENTO PROMEDIO")
    print(f"Regional normal: {growth['crecimiento_regional_normal_promedio_kg_ms_ha_dia']['central']:.2f} kg MS/ha/día")
    print(f"Bruto:          {growth['crecimiento_bruto_promedio_kg_ms_ha_dia']['central']:.2f} kg MS/ha/día")
    print(f"Utilizable:     {growth['crecimiento_utilizable_promedio_kg_ms_ha_dia']['central']:.2f} kg MS/ha/día")
    print(f"Cambio DMP:     {growth['comparacion_con_referencia']['variacion_porcentual']:+.2f}%")
    print("\nPRODUCCION ACUMULADA EN LA VENTANA")
    print(f"Bruta:          {growth['produccion_bruta_acumulada_kg_ms_ha']['central']:.2f} kg MS/ha")
    print(f"Utilizable:     {growth['produccion_utilizable_acumulada_kg_ms_ha']['central']:.2f} kg MS/ha")
    print("\nBALANCE DE STOCK UTILIZABLE")
    print(f"Inicial:        {stock['stock_inicial_kg_ms_ha']['central']:.2f} kg MS/ha")
    print(f"Tipo inicial:   {stock['stock_inicial_estimado']['estado']} (confianza {stock['stock_inicial_estimado']['confianza']})")
    print(f"Consumo:        {stock['consumo']['acumulado_kg_ms_ha']:.2f} kg MS/ha")
    print(f"Final central:  {stock['stock_final_utilizable_kg_ms_ha']['central']:.2f} kg MS/ha")
    print(
        "Rango final:    "
        f"{stock['stock_final_utilizable_kg_ms_ha']['min']:.2f} - "
        f"{stock['stock_final_utilizable_kg_ms_ha']['max']:.2f} kg MS/ha"
    )
    print(f"Total potrero:  {stock['stock_final_utilizable_total_potrero_kg_ms']['central']:.2f} kg MS")
    print(f"Coherencia:     {output['coherencia']['estado']}")
    print(f"Salida JSON:    {output_path.resolve()}")


def calculate_stock(data: dict[str, Any]) -> dict[str, Any]:
    """Entrada estable del servicio: calcula Stock sin archivos intermedios."""
    return execute_calculation(data)
