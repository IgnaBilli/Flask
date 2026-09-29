"""Weather context, not a soil-water or forage-growth model.

P - reference ET0 cannot diagnose soil moisture or flooding. No growth factors
are produced. Relief interpretations are hypotheses to check in the field.
"""
from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime, timedelta
import math
import json
import threading
import time
from zoneinfo import ZoneInfo

from urllib.parse import urlencode
from urllib.request import urlopen

SOURCES = [
    {"id": "open_meteo", "titulo": "Open-Meteo: precipitación y evapotranspiración de referencia",
     "url": "https://open-meteo.com/en/docs", "alcance": "Datos meteorológicos modelados para la ubicación; no son mediciones del suelo de cada zona."},
    {"id": "fao56", "titulo": "FAO-56, capítulo 8: agua disponible y estrés hídrico",
     "url": "https://www.fao.org/4/x0490e/x0490e0e.htm", "alcance": "Fundamento del balance de agua. Ks ajusta transpiración; no se aplica como coeficiente de crecimiento."},
    {"id": "di_bella_2016", "titulo": "UBA-CONICET · Di Bella et al. (2016): relieve y régimen hídrico",
     "url": "https://swr.agriculturejournals.cz/pdfs/swr/2016/02/03.pdf", "alcance": "Mediciones en la Pampa Deprimida. Orienta la interpretación; sus parámetros no se trasladan automáticamente al NEA."},
    {"id": "chaco_2016", "titulo": "INTA · Chiossone et al. (2016): producción por ambientes en Chaco",
     "url": "https://www.produccion-animal.com.ar/produccion_y_manejo_pasturas/pasturas%20naturales/231-Resumenes-VII-Congreso.pdf#page=59", "alcance": "Comparación local en La Viruela, página 59. Producción anual y aprovechamiento no equivalen a un factor diario por relieve."},
    {"id": "corrientes_2021", "titulo": "INTA (2021): Caracterización y manejo de los pastizales correntinos",
     "url": "https://repositorio.inta.gob.ar/handle/20.500.12123/8899", "alcance": "Curvas y ensayos regionales de producción; no define porcentajes universales por relieve."},
    {"id": "nea_2025", "titulo": "INTA (2025): Aportes a la sustentabilidad de la ganadería del NEA",
     "url": "https://repositorio.inta.gob.ar/handle/20.500.12123/23621", "alcance": "Monitoreos de Corrientes, Chaco, Formosa y Misiones. No completa todas las combinaciones de suelo, relieve y vegetación."},
]
OBSERVATIONS = {"seco": "Seco", "humedo": "Húmedo, sin agua en superficie", "anegado": "Con agua en superficie"}
_cache = OrderedDict()
_lock = threading.Lock()


def argentina_today():
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()


def unavailable():
    return {"disponible": False, "mensaje": "No hay una serie meteorológica completa disponible. El crecimiento base se conserva."}


def summarize_daily(payload, end):
    """Require all 30 completed days; never replace missing values with zero."""
    daily = payload.get("daily", {})
    units = payload.get("daily_units", {})
    if any(units.get(k) != "mm" for k in ("precipitation_sum", "et0_fao_evapotranspiration")):
        raise ValueError("Unidades meteorológicas inesperadas")
    dates = daily.get("time", [])
    rain = daily.get("precipitation_sum", [])
    et0 = daily.get("et0_fao_evapotranspiration", [])
    temperature = daily.get("temperature_2m_mean", [])
    temperature_available = (units.get("temperature_2m_mean") == "°C" and len(temperature) == 30
        and all(type(v) in (int, float) and math.isfinite(v) for v in temperature))
    expected = [(end - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    if dates != expected or len(rain) != 30 or len(et0) != 30:
        raise ValueError("Serie incompleta o fechas inesperadas")
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in rain + et0):
        raise ValueError("Dato meteorológico inválido")
    periods = []
    for days in (7, 30):
        p, e = sum(rain[-days:]), sum(et0[-days:])
        balance = round(p - e, 1)
        periods.append({"dias": days, "desde": expected[-days], "hasta": expected[-1],
                        "precipitacion_mm": round(p, 1), "et0_mm": round(e, 1), "balance_mm": balance,
                        "temperatura_media_c": round(sum(temperature[-days:]) / days, 1) if temperature_available else None,
                        "senal": "negativo" if balance < 0 else "positivo" if balance > 0 else "equilibrado"})
    return {"disponible": True, "periodos": periods, "fuente": "open_meteo", "fecha_datos": expected[-1],
            "metodo": "Precipitación menos evapotranspiración de referencia (P − ET₀).",
            "alcance": "Contexto climático del potrero, compartido entre zonas. No mide humedad del suelo ni confirma sequía o inundación."}


def fetch_context(lat, lon, target):
    end = min(date.fromisoformat(target) - timedelta(days=1), argentina_today() - timedelta(days=1))
    # A representative location is sufficient for a weather grid, not per-zone weather.
    key = (round(lat, 2), round(lon, 2), end.isoformat())
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic():
            return deepcopy(hit[1])
    url = ("https://api.open-meteo.com/v1/forecast" if (argentina_today() - end).days <= 60
           else "https://archive-api.open-meteo.com/v1/archive")
    try:
        query = urlencode({"latitude": key[0], "longitude": key[1],
            "start_date": (end - timedelta(days=29)).isoformat(), "end_date": end.isoformat(),
            "daily": "precipitation_sum,et0_fao_evapotranspiration,temperature_2m_mean", "timezone": "America/Argentina/Buenos_Aires"})
        with urlopen(url + "?" + query, timeout=8) as response:
            result = summarize_daily(json.load(response), end)
        result["consultado_en"] = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).isoformat()
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result = unavailable()
    with _lock:
        _cache[key] = (time.monotonic() + (21600 if result["disponible"] else 120), result)
        _cache.move_to_end(key)
        while len(_cache) > 128:
            _cache.popitem(last=False)
    return deepcopy(result)


def zone_reading(zone, climate, target):
    position = zone.get("posicion", "sin_definir")
    signal = climate["periodos"][-1]["senal"] if climate.get("disponible") else "sin_datos"
    base = {
        "loma": "Si el suelo drena bien, puede perder humedad antes que las partes bajas; durante excesos de lluvia puede evacuar agua con mayor facilidad.",
        "media_loma": "Puede conservar humedad por más tiempo que la loma. Si su drenaje es lento, también puede anegarse.",
        "bajo": "Puede recibir y conservar agua de sectores más altos. El efecto sobre el pasto depende del drenaje, la duración del anegamiento y la vegetación.",
    }.get(position, "Definí el relieve para interpretar su posible relación con el agua.")
    context = {
        "negativo": "En 30 días la demanda atmosférica superó las precipitaciones. Revisá la reserva del suelo antes de concluir que el pasto sufre falta de agua.",
        "positivo": "En 30 días las precipitaciones superaron la demanda de referencia. Esto no confirma que el suelo esté húmedo ni anegado.",
        "equilibrado": "Lluvia y demanda de referencia resultan similares en el período; esto no confirma condiciones óptimas del suelo.",
        "sin_datos": "Sin contexto climático actualizado; revisá el estado del suelo a campo.",
    }[signal]
    obs = zone.get("observacion_hidrica")
    current = bool(obs and obs["fecha"] == target)
    effects = {
        "seco": "La falta de agua puede limitar el crecimiento; la intensidad necesita una medición o un modelo calibrado.",
        "humedo": "La humedad observada no basta para afirmar crecimiento óptimo: también influyen temperatura, suelo y vegetación.",
        "anegado": "El agua en superficie puede limitar el crecimiento de plantas no tolerantes y el acceso del ganado. Si impide pastorear, dibujá un sector inaccesible; esta observación no lo descuenta automáticamente.",
    }
    return {"explicacion_relieve": base, "contexto": context,
            "estado_suelo": OBSERVATIONS[obs["estado"]] if current else "Sin confirmar",
            "observacion": obs, "observacion_del_dia": current,
            "efecto_posible": effects[obs["estado"]] if current else "Sin medición actual de humedad, reserva útil ni drenaje. No se puede cuantificar el efecto sobre el crecimiento.",
            "ajuste_crecimiento": "sin_ajuste_validado", "factor_aplicado": 1,
            "fuentes": ["di_bella_2016", "fao56"],
            "alcance": "Interpretación orientativa. El estudio de relieve es bonaerense; requiere validación local en el NEA."}


def build_context(zones, climate, target):
    return {"version": "agua_relieve_informativo_v1", "clima": climate, "fuentes": SOURCES,
            "zonas": [{"id": z["id"], **zone_reading(z, climate, target)} for z in zones if z["tipo"] == "ambiente"],
            "ajuste_automatico": False,
            "nota": "Se conserva el crecimiento base y el stock cargado. No hay coeficientes de crecimiento validados para cada relieve en toda la región.",
            "datos_pendientes": ["Reserva útil y profundidad de raíces", "Infiltración, drenaje y napa", "Respuesta de la vegetación y validación local"]}
