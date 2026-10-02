"""Traceable regional transfer when no direct vegetation rule is available.

This is a selection heuristic, not a newly calibrated agronomic model. Only
the NEA/BA provincial polygons enable new coverage. Existing direct rules and
regional curves remain authoritative and unchanged.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from pyproj import Geod
from shapely.geometry import shape
from shapely.ops import unary_union


BOUNDARIES = Path(__file__).parent / "data/gis/provincias_nea_ba.geojson"
VERSION = "referencia_proxima_nea_ba_v1"
GEOD = Geod(ellps="WGS84")
# These associations mirror the existing IGN/Oyarzabal rules; they are not
# claims of field validation across the entire vegetation unit or province.
PROFILES = {
    "corrientes": ({"campos y malezales", "espinal"}, {"U27", "U28", "U19"}),
    "entre_rios_norte": ({"espinal"}, {"U19"}),
    "buenos_aires_ne": ({"pampa"}, {"U30"}),
    "buenos_aires_centro": ({"pampa"}, set()),
    "pampa_deprimida": ({"pampa"}, {"U33"}),
    "caldenal_norte": ({"espinal"}, {"U22"}),
    "caldenal_centro": ({"espinal"}, {"U22"}),
    "caldenal_sur": ({"espinal"}, {"U22"}),
    "chaco_humedo_oriental": ({"chaco humedo"}, {"U14", "U15"}),
    "santa_fe_norte": ({"chaco humedo", "delta e islas del parana"}, {"U16", "U4"}),
}
UNIT_CURVES = {
    ("corrientes", "U28"): {"malezal"},
    ("corrientes", "U19"): {"pastos_cortos", "flechillar", "pajonal"},
    ("santa_fe_norte", "U4"): {"santa_fe_panicum_prionitis"},
    ("santa_fe_norte", "U16"): {"santa_fe_spartina_argentinensis"},
}


@lru_cache(maxsize=1)
def _boundaries():
    data = json.loads(BOUNDARIES.read_text(encoding="utf-8"))
    return tuple((f["properties"]["nombre"], shape(f["geometry"])) for f in data["features"])


def fallback_scope(polygon):
    matches = [(name, geom) for name, geom in _boundaries() if geom.intersects(polygon)]
    if not matches or not unary_union([geom for _, geom in matches]).covers(polygon):
        return None
    return sorted(name for name, geom in matches if geom.intersection(polygon).area > 0)


def _complete_curves(zone, params):
    """Never interpolate N/D curves or accept incomplete/negative references."""
    result = []
    for key in zone["ambientes"]:
        curve = params["curvas"].get(key, {})
        monthly = curve.get("mensual", [])
        if (len(monthly) == 12 and all(
            isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v >= 0 for v in monthly
        ) and sum(monthly) > 0):
            result.append(key)
    return result


def nearest_reference(polygon, eco, unit, params, provinces):
    point = polygon.representative_point()
    candidates = []
    for key, zone in params["zonas"].items():
        curves = _complete_curves(zone, params)
        if not curves:
            continue
        ecos, units = PROFILES.get(key, (set(), set()))
        same_unit, same_eco = unit in units, eco in ecos
        specific = UNIT_CURVES.get((key, unit))
        if specific:
            curves = [curve for curve in curves if curve in specific]
            if not curves:
                continue
        tier = 0 if same_unit and same_eco else 1 if same_unit else 2 if same_eco else 3
        x1, y1, x2, y2 = zone["bbox_operativo"]
        nearest_lon, nearest_lat = min(max(point.x, x1), x2), min(max(point.y, y1), y2)
        distance = abs(GEOD.inv(point.x, point.y, nearest_lon, nearest_lat)[2]) / 1000
        center_distance = abs(GEOD.inv(point.x, point.y, (x1+x2)/2, (y1+y2)/2)[2]) / 1000
        candidates.append({
            "zona_id": key, "perfiles_utilizados": curves, "prioridad_ambiental": tier,
            "misma_unidad_vegetacion": same_unit, "misma_ecorregion": same_eco,
            "distancia_limite_operativo_km": distance, "distancia_centro_operativo_km": center_distance,
        })
    if not candidates:
        raise ValueError("No hay curvas regionales completas disponibles para el respaldo.")
    candidates.sort(key=lambda c: (c["prioridad_ambiental"], c["distancia_limite_operativo_km"],
                                   c["distancia_centro_operativo_km"], c["zona_id"]))
    chosen = candidates[0]
    for candidate in candidates:
        for field in ("distancia_limite_operativo_km", "distancia_centro_operativo_km"):
            candidate[field] = round(candidate[field], 2)
    justification = (
        "Sin regla regional directa: se priorizó coincidencia de unidad de vegetación y ecorregión, "
        "luego distancia geodésica al límite operativo y a su centro. "
        + ("No hay coincidencia ambiental; se utiliza la referencia disponible más próxima. "
           if chosen["prioridad_ambiental"] == 3 else "")
        + "La transferencia es aproximada y no constituye validación local."
    )
    return {
        "estado": "RESPALDO_PROXIMIDAD", "zona_id": chosen["zona_id"],
        "perfiles_utilizados": chosen["perfiles_utilizados"], "justificacion": justification,
        "confianza_geografica": "BAJA", "confianza_ambiental": "BAJA",
        "respaldo": {
            "version": VERSION, "provincias": provinces, "referencia_transferida": True,
            "validacion_local": False, "criterio": "unidad_ecorregion_distancia",
            "distancias": "A límites operativos aproximados, no a estaciones de medición; WGS84.",
            "comparacion_climatica_directa": False,
            "candidatos_ordenados": candidates,
            "fuente_limites": "https://www.argentina.gob.ar/georef/descarga-de-la-base-completa",
        },
    }
