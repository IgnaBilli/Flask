from __future__ import annotations

import json
import math
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import Polygon, shape
from shapely.ops import transform, unary_union

from .nearby_reference import fallback_scope, nearest_reference


BASE_DIR = Path(__file__).resolve().parent
GIS_DIR = BASE_DIR / "data" / "gis"
IGN_PATH = GIS_DIR / "ign_anida_ecorregiones_gepama.geojson"
OYARZABAL_PATH = (
    GIS_DIR
    / "oyarzabal_2018"
    / "Mapa Unidades Vegetación - Proyecto QGis"
    / "Unidades de Vegetación de la Argentina.kml"
)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def _valid(geometry: Any) -> Any:
    if geometry.is_valid:
        return geometry
    repaired = geometry.buffer(0)
    return repaired if not repaired.is_empty else geometry


def _utm_epsg(polygon: Polygon) -> int:
    lon = polygon.representative_point().x
    zone = max(1, min(60, int(math.floor((lon + 180.0) / 6.0)) + 1))
    return (32600 if polygon.representative_point().y >= 0 else 32700) + zone


def polygon_area_ha(polygon: Polygon) -> tuple[float, str]:
    epsg = _utm_epsg(polygon)
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    projected = transform(transformer.transform, polygon)
    return abs(projected.area) / 10000.0, f"EPSG:{epsg}"


def _percentage_intersections(polygon: Polygon, features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    epsg = _utm_epsg(polygon)
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    projected_polygon = transform(transformer.transform, polygon)
    denominator = projected_polygon.area
    results: list[dict[str, Any]] = []
    for feature in features:
        geometry = _valid(feature["geometry"])
        if geometry.is_empty or not geometry.intersects(polygon):
            continue
        intersection = _valid(geometry.intersection(polygon))
        projected_intersection = transform(transformer.transform, intersection)
        percentage = 100.0 * projected_intersection.area / denominator if denominator else 0.0
        if percentage > 0.0001:
            item = dict(feature["properties"])
            item["porcentaje_superficie"] = round(percentage, 4)
            results.append(item)
    results.sort(key=lambda item: item["porcentaje_superficie"], reverse=True)
    return results


def _load_ign_features(polygon: Polygon) -> list[dict[str, Any]]:
    if not IGN_PATH.exists():
        raise FileNotFoundError(f"No existe la capa IGN: {IGN_PATH}")
    with IGN_PATH.open("r", encoding="utf-8") as handle:
        collection = json.load(handle)
    minx, miny, maxx, maxy = polygon.bounds
    features: list[dict[str, Any]] = []
    for raw in collection.get("features", []):
        geometry = shape(raw["geometry"])
        gx1, gy1, gx2, gy2 = geometry.bounds
        if gx2 < minx or gx1 > maxx or gy2 < miny or gy1 > maxy:
            continue
        properties = raw.get("properties", {})
        features.append({
            "geometry": geometry,
            "properties": {
                "nombre": properties.get("ECORREGION"),
                "objectid": properties.get("OBJECTID"),
            },
        })
    return features


def _coordinates(text: str | None) -> list[tuple[float, float]]:
    if not text:
        return []
    return [tuple(map(float, token.split(",")[:2])) for token in text.strip().split()]


def _load_oyarzabal_features(polygon: Polygon) -> list[dict[str, Any]]:
    if not OYARZABAL_PATH.exists():
        raise FileNotFoundError(f"No existe la capa Oyarzabal: {OYARZABAL_PATH}")
    namespace = {"k": "http://www.opengis.net/kml/2.2"}
    root = ET.parse(OYARZABAL_PATH).getroot()
    minx, miny, maxx, maxy = polygon.bounds
    features: list[dict[str, Any]] = []
    for placemark in root.findall(".//k:Placemark", namespace):
        properties = {
            item.attrib.get("name"): (item.text or "").strip()
            for item in placemark.findall(".//k:SimpleData", namespace)
        }
        polygons: list[Polygon] = []
        for element in placemark.findall(".//k:Polygon", namespace):
            outer = element.find(
                ".//k:outerBoundaryIs/k:LinearRing/k:coordinates", namespace
            )
            if outer is None:
                continue
            shell = _coordinates(outer.text)
            holes = [
                _coordinates(item.text)
                for item in element.findall(
                    ".//k:innerBoundaryIs/k:LinearRing/k:coordinates", namespace
                )
            ]
            if len(shell) >= 4:
                polygons.append(Polygon(shell, [hole for hole in holes if len(hole) >= 4]))
        if not polygons:
            continue
        geometry = _valid(unary_union(polygons))
        gx1, gy1, gx2, gy2 = geometry.bounds
        if gx2 < minx or gx1 > maxx or gy2 < miny or gy1 > maxy:
            continue
        code = str(properties.get("CODIGO", "")).strip()
        features.append({
            "geometry": geometry,
            "properties": {
                "codigo": f"U{code}" if code and not code.upper().startswith("U") else code,
                "region": properties.get("REGION"),
                "dominio": properties.get("DOMINIO"),
                "unidad_fitogeografica": properties.get("UNID_FITOG"),
                "nombre_fisonomico": properties.get("NOMFISONOM"),
                "nombre_vulgar": properties.get("NOMVULGAR"),
            },
        })
    return features


def _inside_bbox(point: Any, bbox: list[float]) -> bool:
    return bbox[0] <= point.x <= bbox[2] and bbox[1] <= point.y <= bbox[3]


def _bbox_fallback(polygon: Polygon, params: dict[str, Any]) -> tuple[str, list[str]]:
    point = polygon.representative_point()
    candidates = [
        (key, zone)
        for key, zone in params["zonas"].items()
        if _inside_bbox(point, zone["bbox_operativo"])
    ]
    if not candidates:
        raise ValueError("La ubicación no tiene una referencia regional TerraBovina compatible.")
    candidates.sort(
        key=lambda pair: (pair[1]["bbox_operativo"][2] - pair[1]["bbox_operativo"][0])
        * (pair[1]["bbox_operativo"][3] - pair[1]["bbox_operativo"][1])
    )
    key, zone = candidates[0]
    return key, list(zone["ambientes"])


def _map_reference(
    polygon: Polygon,
    ecoregion: str,
    unit: str,
    params: dict[str, Any],
) -> tuple[str, list[str], str, str] | None:
    eco = _normalize(ecoregion)
    unit = unit.upper()
    point = polygon.representative_point()

    if eco == "campos y malezales" and unit == "U28":
        return "corrientes", ["malezal"], "EXACTA", "Campos y Malezales + U28 identifica la referencia CO-03 Malezal."
    if eco == "campos y malezales" and unit == "U27":
        return "corrientes", list(params["zonas"]["corrientes"]["ambientes"]), "PARCIAL", "U27 Campos y Urundayzales no distingue las comunidades de la matriz; se usa mediana y rango de Corrientes."
    if eco == "espinal" and unit == "U19":
        if _inside_bbox(point, params["zonas"]["entre_rios_norte"]["bbox_operativo"]):
            return "entre_rios_norte", ["pastizal_natural_entre_rios_norte"], "EXACTA", "Espinal + U19 en el norte de Entre Ríos selecciona ER-01."
        return "corrientes", ["pastos_cortos", "flechillar", "pajonal"], "PARCIAL", "Espinal + U19 no distingue la comunidad; se conservan CO-01, CO-02 y CO-04."
    if eco == "pampa" and unit == "U30":
        return "buenos_aires_ne", ["pastizal_natural_buenos_aires_ne"], "EXACTA", "Pampa + U30 selecciona BA-03."
    if eco == "pampa" and unit == "U33":
        curves = ["pampa_deprimida_loma_media_loma", "pampa_deprimida_bajo_dulce", "pampa_deprimida_bajo_alcalino"]
        return "pampa_deprimida", curves, "PARCIAL", "Pampa + U33 no distingue relieve; se usa mediana y rango de loma, bajo dulce y bajo alcalino."
    if eco == "espinal" and unit == "U22":
        choices = ["caldenal_norte", "caldenal_centro", "caldenal_sur"]
        choices.sort(key=lambda key: abs(point.y - (params["zonas"][key]["bbox_operativo"][1] + params["zonas"][key]["bbox_operativo"][3]) / 2.0))
        key = choices[0]
        return key, list(params["zonas"][key]["ambientes"]), "PARCIAL", "Espinal + U22 identifica Caldenal; la franja latitudinal aproxima el sector y se conserva el rango de comunidades."
    if eco == "chaco humedo" and unit in {"U14", "U15"}:
        return "chaco_humedo_oriental", ["chaco_humedo_paja_amarilla", "chaco_humedo_paja_boba"], "PARCIAL", "La unidad no separa paja amarilla de paja boba; se usa su mediana y rango."
    if eco == "chaco humedo" and unit == "U16":
        return "santa_fe_norte", ["santa_fe_spartina_argentinensis"], "EXACTA", "Chaco Húmedo + U16 selecciona SF-01 Spartina argentinensis."
    if eco == "delta e islas del parana" and unit == "U4":
        return "santa_fe_norte", ["santa_fe_panicum_prionitis"], "EXACTA", "Delta e Islas del Paraná + U4 selecciona SF-02 Panicum prionitis."

    return None


def resolve_gis_context(polygon: Polygon, params: dict[str, Any]) -> dict[str, Any]:
    area_ha, metric_crs = polygon_area_ha(polygon)
    ecoregions = _percentage_intersections(polygon, _load_ign_features(polygon))
    vegetation_units = _percentage_intersections(polygon, _load_oyarzabal_features(polygon))
    dominant_eco = ecoregions[0]["nombre"] if ecoregions else ""
    dominant_unit = vegetation_units[0]["codigo"] if vegetation_units else ""
    direct = _map_reference(
        polygon, dominant_eco, dominant_unit, params
    )
    transferred = None
    if direct is None:
        provinces = fallback_scope(polygon)
        if provinces:
            transferred = nearest_reference(polygon, _normalize(dominant_eco), dominant_unit, params, provinces)
            direct = (transferred["zona_id"], transferred["perfiles_utilizados"],
                      transferred["estado"], transferred["justificacion"])
        else:
            if not ecoregions or not vegetation_units:
                raise ValueError("El polígono no intersecta las capas ambientales y está fuera del respaldo NEA/Buenos Aires.")
            zone_key, curves = _bbox_fallback(polygon, params)
            direct = (zone_key, curves, "RESPALDO_BBOX",
                      f"No existe mapeo exacto para {dominant_eco} + {dominant_unit}; se usó el límite operativo regional solo como respaldo.")
    zone_key, curve_keys, selection_status, justification = direct
    geographic_confidence = "ALTA"
    if not ecoregions or not vegetation_units or ecoregions[0]["porcentaje_superficie"] < 90 or vegetation_units[0]["porcentaje_superficie"] < 90:
        geographic_confidence = "MEDIA"
    if selection_status in {"RESPALDO_BBOX", "RESPALDO_PROXIMIDAD"}:
        geographic_confidence = "BAJA"

    return {
        "superficie_ha": area_ha,
        "crs_entrada": "EPSG:4326",
        "crs_calculo_superficie": metric_crs,
        "metodo_interseccion": "poligono_completo_reproyectado_a_crs_metrico",
        "ecorregiones": ecoregions,
        "unidades_vegetacion": vegetation_units,
        "fuentes": {
            "ecorregiones": {
                "organismo": "Instituto Geográfico Nacional (IGN), ANIDA",
                "archivo_local": str(IGN_PATH),
                "capa": "Ecología - Ecorregiones",
                "crs": "EPSG:4326",
            },
            "unidades_vegetacion": {
                "autores": "Oyarzabal et al. (2018)",
                "archivo_local": str(OYARZABAL_PATH),
                "publicacion": "Unidades de vegetación de la Argentina, Ecología Austral 28:040-063",
                "crs": "EPSG:4326",
            },
        },
        "seleccion_referencia": {
            "estado": selection_status,
            "zona_id": zone_key,
            "perfiles_utilizados": curve_keys,
            "justificacion": justification,
            "confianza_geografica": geographic_confidence,
            "confianza_ambiental": "ALTA" if len(curve_keys) == 1 and selection_status == "EXACTA" else "BAJA",
            **({"respaldo": transferred["respaldo"]} if transferred else {}),
        },
    }
