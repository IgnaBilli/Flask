"""Manual environmental zoning. No remote calls or synthetic satellite pixels.

Monthly references are the existing, versioned regional matrix. Preference is
relative proximity, not an animal observation or a calibrated grazing model.
"""
import json
import math
import statistics
from datetime import date
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, shape, mapping
from shapely.ops import transform, unary_union

VERSION = "relieve_sin_curvas_v2"
PARAMS = Path(__file__).parent / "stock/data/parametros_regionales.json"

class ZoneError(ValueError):
    pass


def polygon(raw):
    if not isinstance(raw, dict) or raw.get("type") != "Polygon":
        raise ZoneError("Cada zona debe ser un polígono GeoJSON.")
    rings = raw.get("coordinates")
    if not isinstance(rings, list) or not rings or sum(len(r) for r in rings if isinstance(r, list)) > 500:
        raise ZoneError("El polígono admite hasta 500 vértices.")
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
            raise ZoneError("Los anillos deben estar cerrados y tener al menos tres vértices.")
        for coord in ring:
            if (not isinstance(coord, list) or len(coord) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in coord)
                or not -180 <= coord[0] <= 180 or not -90 <= coord[1] <= 90):
                raise ZoneError("Coordenadas inválidas; usar longitud, latitud en WGS84.")
    geom = shape(raw)
    if geom.is_empty or not geom.is_valid or geom.area <= 0:
        raise ZoneError("El polígono está vacío o se cruza a sí mismo.")
    return geom


def iso_day(value):
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError()
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ZoneError("Las fechas deben tener formato YYYY-MM-DD.")


def analyze(data, context_resolver=None, weather_resolver=None):
    if not isinstance(data, dict):
        raise ZoneError("Se requiere un objeto JSON.")
    field = polygon(data.get("geojson"))
    target = iso_day(data.get("fecha", date.today().isoformat()))
    config = data.get("configuracion", {})
    if not isinstance(config, dict) or not isinstance(config.get("zonas", []), list):
        raise ZoneError("La configuración debe contener una lista de zonas.")
    zones = config.get("zonas", [])
    if len(zones) > 40:
        raise ZoneError("Se admiten hasta 40 zonas por potrero.")
    params = json.loads(PARAMS.read_text(encoding="utf-8"))
    if context_resolver is None:
        from stock.gis_utils import resolve_gis_context
        context_resolver = resolve_gis_context
    try:
        context = context_resolver(field, params)
    except (ValueError, KeyError) as exc:
        from intrapaddock_climate import coverage
        covered = coverage(field)
        if not covered["incluido"]:
            raise ZoneError("No hay referencia regional disponible para esta ubicación.") from exc
        # Keep spatial analysis available throughout NEA/BA. Missing growth is
        # explicitly unknown: never borrow a neighbouring province's curve.
        context = {"seleccion_referencia": {"zona_id": "sin_referencia_regional",
            "perfiles_utilizados": [], "estado": "SIN_REFERENCIA",
            "justificacion": "Sin curva regional disponible; se conserva el crecimiento cargado.",
            "provincia": ", ".join(covered["provincias"])}}
    selection = context["seleccion_referencia"]
    region = selection["zona_id"]
    baseline_keys = selection["perfiles_utilizados"]
    baseline = [statistics.median(params["curvas"][k]["mensual"][m] for k in baseline_keys)
                if baseline_keys else None for m in range(12)]
    catalog = []  # Regional pasture types are no longer intrapaddock choices.
    point = field.representative_point()
    epsg = (32700 if point.y < 0 else 32600) + max(1, min(60, int((point.x + 180) // 6) + 1))
    forward = Transformer.from_crs(4326, epsg, always_xy=True).transform
    backward = Transformer.from_crs(epsg, 4326, always_xy=True).transform
    projected = transform(forward, field)
    area = projected.area
    if area < 1:
        raise ZoneError("El potrero debe tener al menos un metro cuadrado.")
    normalized, geometries, habitats, ids = [], {}, [], set()
    for z in zones:
        if not isinstance(z, dict):
            raise ZoneError("Cada zona debe ser un objeto.")
        zid, name, kind = z.get("id"), z.get("nombre"), z.get("tipo")
        if not isinstance(zid, str) or not 1 <= len(zid) <= 80 or zid in ids:
            raise ZoneError("Las zonas necesitan identificadores únicos.")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ZoneError("Cada zona necesita un nombre de hasta 100 caracteres.")
        if kind not in {"ambiente", "aguada", "sombra", "inaccesible"}:
            raise ZoneError("Tipo de zona desconocido.")
        geom = polygon(z.get("geom"))
        if not field.covers(geom):
            raise ZoneError(f"La zona {name} debe quedar completamente dentro del potrero.")
        # Projected straight edges can differ slightly after subdivision.
        # Clip to the projected field so the area budget never exceeds 100%.
        metric = transform(forward, geom).intersection(projected)
        if metric.area < 1:
            raise ZoneError(f"La zona {name} debe tener al menos un metro cuadrado.")
        item = {"id": zid, "nombre": name.strip(), "tipo": kind, "geom": mapping(geom),
                "superficie_ha": metric.area / 10000, "porcentaje": metric.area / area * 100,
                "fuente": "declarado_por_usuario"}
        if kind == "ambiente":
            position = z.get("posicion", "sin_definir")
            if position not in {"sin_definir", "loma", "media_loma", "bajo", "otro"}:
                raise ZoneError("Posición del relieve desconocida.")
            item["posicion"] = position
            observation = z.get("observacion_hidrica")
            if observation is not None:
                from intrapaddock_water import OBSERVATIONS
                if (not isinstance(observation, dict) or not isinstance(observation.get("estado"), str)
                        or observation["estado"] not in OBSERVATIONS):
                    raise ZoneError("Estado hídrico observado inválido.")
                observed = iso_day(observation.get("fecha"))
                if observed > target:
                    raise ZoneError("La observación del suelo no puede tener una fecha futura.")
                item["observacion_hidrica"] = {"estado": observation["estado"], "fecha": observed}
            if any(metric.intersection(other).area > 0.01 for other in habitats):
                raise ZoneError("Los ambientes no pueden superponerse; pueden compartir bordes.")
            habitats.append(metric)
            # Ignore retired IDs from stored versions or older clients. Relief
            # describes the zone; it does not select another growth curve.
            item["curva_mensual"] = baseline[:]
            item["referencia"] = "Referencia base del potrero, sin ajuste por relieve."
        if kind == "inaccesible":
            start = iso_day(z.get("desde"))
            end = iso_day(z["hasta"]) if z.get("hasta") else None
            if end and end < start:
                raise ZoneError("La fecha de fin debe ser igual o posterior al inicio.")
            item.update(desde=start, hasta=end)
        normalized.append(item)
        geometries[zid] = metric
        ids.add(zid)

    restrictions = unary_union([geometries[z["id"]] for z in normalized if z["tipo"] == "inaccesible"
                                and z["desde"] <= target and (not z["hasta"] or target <= z["hasta"])])
    # Aguadas represent water only, with no forage. Union all exclusions so
    # overlaps between water bodies and dated restrictions count only once.
    water_area = unary_union([geometries[z["id"]] for z in normalized if z["tipo"] == "aguada"])
    blocked = unary_union([restrictions, water_area])
    accessible = projected.difference(blocked)
    habitat_area = sum(g.area for g in habitats)
    unclassified = projected.difference(unary_union(habitats))
    for z in normalized:
        if z["tipo"] == "ambiente":
            g = geometries[z["id"]]
            z["superficie_accesible_ha"] = g.difference(blocked).area / 10000
            z["aporte_mensual_kg_ms_ha_dia"] = [v * g.area / area if v is not None else None for v in z["curva_mensual"]]

    # All zones use the same baseline; avoid area-rounding growth multipliers.
    weighted = baseline[:]
    accessible_ref = [v * accessible.area / area if v is not None else None for v in baseline]
    # Water remains a proximity resource even though its surface is not grazed.
    # Only an active access restriction removes a water resource from the map.
    water = [geometries[z["id"]].difference(restrictions) for z in normalized if z["tipo"] == "aguada"]
    shade = [geometries[z["id"]].difference(blocked) for z in normalized if z["tipo"] == "sombra"]
    water = [g for g in water if not g.is_empty]
    shade = [g for g in shade if not g.is_empty]
    # Grid is a display sample, NOT Sentinel pixels. Rank proximity within this field.
    samples = []
    if water or shade:
        x0, y0, x1, y1 = projected.bounds
        step = max(10, max(x1 - x0, y1 - y0) / 18)
        for i in range(math.ceil((x1 - x0) / step)):
            for j in range(math.ceil((y1 - y0) / step)):
                p = Point(x0 + (i + .5) * step, y0 + (j + .5) * step)
                if not accessible.covers(p):
                    continue
                dw = min(p.distance(g) for g in water) if water else None
                ds = min(p.distance(g) for g in shade) if shade else None
                samples.append({"geom": mapping(transform(backward, p)), "agua_m": dw, "sombra_m": ds})
        for key in ("agua_m", "sombra_m"):
            vals = sorted(s[key] for s in samples if s[key] is not None)
            for s in samples:
                if vals:
                    # Equal distances receive the same score; flat layer is neutral.
                    s[key + "_cercania"] = ((max(vals) - s[key]) / (max(vals) - min(vals))
                                             if max(vals) > min(vals) else .5)
        for s in samples:
            values = [s[k] for k in ("agua_m_cercania", "sombra_m_cercania") if k in s]
            score = sum(values) / len(values)
            s["nivel"] = "alta" if score >= 2 / 3 else "baja" if score < 1 / 3 else "media"
            s["indice_relativo"] = round(score, 3)
    warnings = ["Ambientes y recursos declarados por el usuario; no detectados por satélite.",
                "El relieve no modifica el crecimiento base del potrero. No se aplican curvas por tipo de pastizal."]
    if selection.get("confianza_geografica") in {"BAJA", "MEDIA"}:
        warnings.append("La selección regional requiere revisión: " + selection.get("justificacion", "Ubicación regional aproximada."))
    if unclassified.area / area > .001:
        warnings.append("La superficie sin clasificar conserva la referencia regional actual.")
    if not water:
        warnings.append("Sin aguadas registradas: no se puede evaluar cercanía al agua. No implica que no exista agua.")
    if water_area.area > .01:
        warnings.append("Las aguadas representan agua sin pasto y se excluyen de la superficie pastoreable.")
    if restrictions.area > .01:
        warnings.append("Hay sectores inaccesibles: la carga se concentra sobre una superficie menor.")
    from intrapaddock_water import build_context, unavailable
    from intrapaddock_climate import build_comparison
    climate = weather_resolver(point.y, point.x, target) if weather_resolver else unavailable()
    return {"version": VERSION, "fecha": target, "region": region, "seleccion_referencia": selection,
            "agua_relieve": build_context(normalized, climate, target),
            "comparacion_climatica": build_comparison(field, climate, target, baseline),
            "region_nombre": params["zonas"][region]["nombre"] if region in params["zonas"]
                else selection.get("provincia", "Sin referencia regional"), "catalogo": catalog,
            "configuracion": {"zonas": normalized}, "superficie_total_ha": area / 10000,
            "superficie_pastoreable_ha": accessible.area / 10000,
            "superficie_agua_ha": water_area.area / 10000,
            "accesibilidad_metodo": "sin_aguadas_y_restricciones_v2",
            "superficie_sin_clasificar_ha": max(0, area - habitat_area) / 10000,
            "referencia_base_mensual": baseline, "referencia_ponderada_mensual": weighted,
            "referencia_accesible_mensual": accessible_ref,
            "factor_mensual": [1] * 12,
            "preferencia": {"metodo": "cercania_relativa_agua_sombra_v1", "puntos": samples,
                           "advertencia": "Preferencia potencial por cercanía; no mide consumo, presencia animal ni sobrepastoreo. Pesos iguales y tercios son convenciones visuales no calibradas."},
            "advertencias": warnings, "matriz_version": params["version"]}
