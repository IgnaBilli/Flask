"""Evidence-gated comparison for natural grasslands in NEA and Buenos Aires.

Geographic coverage does not imply a calibrated growth model. The reviewed
studies provide local/seasonal evidence, not a transferable province-wide
rainfall/relief multiplier. Until an applicable model is validated, estimates
remain None (never zero or a copied baseline labelled as a new prediction).
This module does not mutate the production ledger or regional/DMP calculator.
"""
import json
from functools import lru_cache
from pathlib import Path
from shapely.geometry import shape
from shapely.ops import unary_union

BOUNDARIES = Path(__file__).parent / "stock/data/gis/provincias_nea_ba.geojson"
EVIDENCE = {
    "18": {"provincia": "Corrientes", "titulo": "Leszczuk · FAUBA (2020)",
        "url": "https://ri.agro.uba.ar/files/download/tesis/especializacion/2022leszczukandresalejandro.pdf",
        "alcance": "Cinco potreros de pastizal natural de INTA Mercedes; modelo mensual de lluvia y temperatura (2000–2018).",
        "pendiente": "Falta comprobar la aplicabilidad al potrero y validar el modelo con la fuente meteorológica utilizada.",
        "tipo": "trabajo_final_especializacion"},
    "06": {"provincia": "Buenos Aires", "titulo": "Fernández y colaboradores · UNLP (2022)",
        "url": "https://sedici.unlp.edu.ar/bitstream/handle/10915/150871/Documento_completo.pdf-PDFA.pdf?sequence=1",
        "alcance": "Pastizal natural de Magdalena (2001–2020); lluvias de noviembre–diciembre y producción de enero–febrero.",
        "pendiente": "Modelo local y estacional; falta validación zonal. No permite estimar cualquier mes de toda la provincia.",
        "tipo": "resumen_congreso"},
    "22": {"provincia": "Chaco", "titulo": "INTA · Pastizales del Chaco Húmedo (2024)",
        "url": "https://www.argentina.gob.ar/node/423766",
        "alcance": "Monitoreo de pastizales naturales en bajo inundable, ralera y media loma–bajo.",
        "pendiente": "Faltan series y coeficientes verificados para relacionar clima y crecimiento en cada ambiente.",
        "tipo": "documentacion_institucional"},
    "34": {"provincia": "Formosa", "titulo": "INTA · Aportes a la sustentabilidad de la ganadería del NEA (2025)",
        "url": "https://repositorio.inta.gob.ar/handle/20.500.12123/23621",
        "alcance": "Evaluación de pastizal natural en General Belgrano, páginas 60–61; no se usan los ensayos de pasturas implantadas.",
        "pendiente": "Falta un modelo climático validado por ambiente; el monitoreo local no representa toda Formosa.",
        "tipo": "informe_tecnico"},
    "54": {"provincia": "Misiones", "titulo": "Rossner, Marastoni y Cibils (2016)",
        "url": "https://www.produccion-animal.com.ar/produccion_y_manejo_pasturas/pasturas%20naturales/231-Resumenes-VII-Congreso.pdf#page=112",
        "alcance": "Pastizal natural del sur de Misiones; dinámica estacional. El resumen no presenta los resultados separados de loma y bajo.",
        "pendiente": "Faltan los datos desagregados y una respuesta climática validada para el potrero.",
        "tipo": "resumen_congreso"},
}


@lru_cache(maxsize=1)
def boundaries():
    data = json.loads(BOUNDARIES.read_text(encoding="utf-8"))
    return [(f["properties"]["id"], shape(f["geometry"])) for f in data["features"]]


def coverage(field):
    """Require the entire field to fall inside the target provinces, not a bbox."""
    matches = [(code, geom) for code, geom in boundaries() if geom.intersects(field)]
    inside = bool(matches and unary_union([g for _, g in matches]).covers(field))
    codes = [code for code, geom in matches if geom.intersection(field).area > 0]
    return {"incluido": inside, "provincias": [EVIDENCE[c]["provincia"] for c in codes],
            "codigos": codes, "metodo": "interseccion_georef_provincias",
            "fuente": "https://www.argentina.gob.ar/georef/descarga-de-la-base-completa"}


def build_comparison(field, climate, target, baseline):
    area = coverage(field)
    period = next((p for p in climate.get("periodos", []) if p.get("dias") == 30), None)
    return {
        "version": "comparacion_climatica_nea_ba_v1", "fecha": target,
        "cobertura": area, "experimental": True, "aplicado_al_balance": False,
        "estado": "sin_modelo_validado" if area["incluido"] else "fuera_de_cobertura",
        "estimacion_kg_ms_ha_dia": None, "diferencia_porcentual": None,
        "referencia_regional_kg_ms_ha_dia": baseline[int(target[5:7])-1],
        "periodo_climatico": period if climate.get("disponible") else None,
        "fuentes": [dict(EVIDENCE[c]) for c in area["codigos"]],
        "mensaje": "Se conserva el crecimiento actual: falta un modelo climático validado para este potrero."
            if area["incluido"] else "La comparación comprende NEA y provincia de Buenos Aires.",
        "nota": "La estimación vigente ya puede incorporar clima y vegetación. No se aplica un segundo factor ni un porcentaje por relieve.",
    }
