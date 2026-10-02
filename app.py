from flask import Flask, request, jsonify
import os
import sys
import math
import json
from datetime import datetime, timedelta
import urllib.request
import pandas as pd
import numpy as np
import joblib

# Paths base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DMP_DIR = os.path.join(BASE_DIR, 'modelo_final DMP')
DMI_DIR = os.path.join(BASE_DIR, 'modelo_final DMI')

# Agregar directorios src a sys.path
sys.path.insert(0, os.path.join(DMP_DIR, 'src'))
sys.path.insert(0, DMI_DIR)

# Modulo utils para DMP
import models_utils
sys.modules['models_utils'] = models_utils
from feature_engineering import add_agronomic_features

# Import predictor de DMI
from src.predictor import HerdPredictor
from stock import StockError, StockInputError, StockCoverageError, calculate_stock
from validation import PredictionInputError, validate_dmi, validate_dmp

# Inicializar Flask app
app = Flask(__name__)
from rotation import rotation_api
app.register_blueprint(rotation_api)


@app.errorhandler(PredictionInputError)
def invalid_prediction_input(error):
    return jsonify({"error": str(error)}), 400


@app.errorhandler(StockError)
def unavailable_prediction_source(error):
    return jsonify({"estado": "NO_CALCULABLE", "error": str(error)}), 502


@app.errorhandler(400)
@app.errorhandler(415)
def invalid_json(error):
    return jsonify({"error": "Body JSON válido requerido."}), error.code

# --- INICIALIZACIÓN Y CARGA DE MODELOS ---

# Cargar modelo DMP
model_path_dmp = os.path.join(DMP_DIR, 'models', 'final_model.joblib')
artifacts_dmp = joblib.load(model_path_dmp)
model_dmp = artifacts_dmp['model']
encoder_dmp = artifacts_dmp['encoder']
feature_columns_dmp = artifacts_dmp['feature_columns']
cat_cols_dmp = artifacts_dmp.get('cat_cols', ['tipo_uso_suelo', 'clase_cobertura_mapbiomas'])

# Cargar modelo DMI
dmi_predictor = HerdPredictor()

# --- FUNCIONES AUXILIARES DMP ---
def fetch_mapbiomas_class(lat: float, lon: float, year: int) -> str:
    try:
        url = 'https://prd.plataforma.mapbiomas.org/api/v1/argentina/maps/pixel-history'
        pixel_values = [27, 15, 9, 21, 19, 36, 3, 4, 6, 34, 33, 77, 63, 12, 11, 66, 73, 24, 25]
        params_str = f"latitude={lat}&longitude={lon}&subthemeKey=coverage_lclu&legendKey=default"
        for pv in pixel_values:
            params_str += f"&pixelValue={pv}"
            
        full_url = f"{url}?{params_str}"
        req = urllib.request.Request(full_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            hist = data.get('history', [])
            
            mapping = {
                1: 'Bosques', 3: 'Bosques cerrados', 4: 'Bosques abiertos', 6: 'Bosques inundables',
                10: 'Vegetación natural herbácea y arbustiva', 66: 'Arbustales cerrados', 77: 'Arbustales abiertos',
                63: 'Mosaicos de arbustos y herbáceas', 12: 'Herbáceas', 11: 'Herbaceas Inundables', 73: 'Turberas',
                14: 'Áreas de uso agropecuario', 18: 'Agricultura', 19: 'Cultivos temporarios', 36: 'Cultivos perennes',
                15: 'Pasturas', 9: 'Silvicultura', 21: 'Mosaico de usos', 22: 'Área sin vegetación', 24: 'Áreas urbanas',
                25: 'Otras áreas no vegetadas', 26: 'Cuerpos de agua', 34: 'Hielo en superficie y nieve permanente',
                33: 'Ríos, lagunas, lagos y océano', 27: 'No observado'
            }
            
            year_map = {item['year']: item['pixelValue'] for item in hist}
            pixel_val = year_map.get(year)
            if pixel_val is None and year_map:
                pixel_val = year_map[max(year_map.keys())]
                
            if pixel_val not in mapping or pixel_val == 27:
                raise StockError('MapBiomas no devolvió una cobertura utilizable.')
            return mapping[pixel_val]
    except Exception as exc:
        raise StockError('No se pudo consultar la cobertura de MapBiomas.') from exc

def fetch_open_meteo_weather(lat: float, lon: float, target_date_str: str) -> dict:
    target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    start_dt = target_dt - timedelta(days=65)
    
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = target_dt.strftime("%Y-%m-%d")
    
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat}&longitude={lon}&start_date={start_str}&end_date={end_str}&"
        f"daily=temperature_2m_mean,temperature_2m_min,temperature_2m_max,"
        f"precipitation_sum,shortwave_radiation_sum,relative_humidity_2m_mean,wind_speed_10m_max&"
        f"timezone=auto"
    )
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as exc:
        raise StockError('No se pudo consultar el clima en Open-Meteo.') from exc
        
    try:
        df_w = pd.DataFrame(data['daily'])
        required = ['temperature_2m_mean', 'temperature_2m_min', 'temperature_2m_max',
                    'precipitation_sum', 'shortwave_radiation_sum', 'relative_humidity_2m_mean', 'wind_speed_10m_max']
        if len(df_w) < 60 or df_w['time'].iloc[-1] != target_date_str:
            raise ValueError('Período climático incompleto.')
        if not np.isfinite(df_w[required].to_numpy(dtype=float)).all():
            raise ValueError('Datos climáticos faltantes.')
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise StockError('Open-Meteo no devolvió todos los datos climáticos requeridos.') from exc
    
    row_today = df_w.iloc[-1]
    
    def get_slice(days):
        return df_w.iloc[-(days):]
    
    s7 = get_slice(7)
    s14 = get_slice(14)
    s30 = get_slice(30)
    s60 = get_slice(60)
    
    return {
        "temperatura_media_del_dia": float(row_today['temperature_2m_mean']),
        "temperatura_minima_del_dia": float(row_today['temperature_2m_min']),
        "temperatura_maxima_del_dia": float(row_today['temperature_2m_max']),
        "precipitacion_del_dia": float(row_today['precipitation_sum']),
        "radiacion_solar_del_dia": float(row_today['shortwave_radiation_sum']),
        "humedad_relativa_del_dia": float(row_today['relative_humidity_2m_mean']),
        "velocidad_del_viento_del_dia": float(row_today['wind_speed_10m_max']),
        
        "precipitacion_acumulada_ultimos_7_dias": float(s7['precipitation_sum'].sum()),
        "radiacion_solar_acumulada_ultimos_7_dias": float(s7['shortwave_radiation_sum'].sum()),
        "temperatura_media_promedio_ultimos_7_dias": float(s7['temperature_2m_mean'].mean()),
        "humedad_relativa_promedio_ultimos_7_dias": float(s7['relative_humidity_2m_mean'].mean()),
        "velocidad_del_viento_promedio_ultimos_7_dias": float(s7['wind_speed_10m_max'].mean()),
        "temperatura_minima_ultimos_7_dias": float(s7['temperature_2m_min'].min()),
        "temperatura_maxima_ultimos_7_dias": float(s7['temperature_2m_max'].max()),
        
        "precipitacion_acumulada_ultimos_14_dias": float(s14['precipitation_sum'].sum()),
        "radiacion_solar_acumulada_ultimos_14_dias": float(s14['shortwave_radiation_sum'].sum()),
        "temperatura_media_promedio_ultimos_14_dias": float(s14['temperature_2m_mean'].mean()),
        "humedad_relativa_promedio_ultimos_14_dias": float(s14['relative_humidity_2m_mean'].mean()),
        "velocidad_del_viento_promedio_ultimos_14_dias": float(s14['wind_speed_10m_max'].mean()),
        "temperatura_minima_ultimos_14_dias": float(s14['temperature_2m_min'].min()),
        "temperatura_maxima_ultimos_14_dias": float(s14['temperature_2m_max'].max()),

        "precipitacion_acumulada_ultimos_30_dias": float(s30['precipitation_sum'].sum()),
        "radiacion_solar_acumulada_ultimos_30_dias": float(s30['shortwave_radiation_sum'].sum()),
        "temperatura_media_promedio_ultimos_30_dias": float(s30['temperature_2m_mean'].mean()),
        "humedad_relativa_promedio_ultimos_30_dias": float(s30['relative_humidity_2m_mean'].mean()),
        "velocidad_del_viento_promedio_ultimos_30_dias": float(s30['wind_speed_10m_max'].mean()),
        "temperatura_minima_ultimos_30_dias": float(s30['temperature_2m_min'].min()),
        "temperatura_maxima_ultimos_30_dias": float(s30['temperature_2m_max'].max()),

        "precipitacion_acumulada_ultimos_60_dias": float(s60['precipitation_sum'].sum()),
        "radiacion_solar_acumulada_ultimos_60_dias": float(s60['shortwave_radiation_sum'].sum()),
        "temperatura_media_promedio_ultimos_60_dias": float(s60['temperature_2m_mean'].mean()),
        "humedad_relativa_promedio_ultimos_60_dias": float(s60['relative_humidity_2m_mean'].mean()),
        "velocidad_del_viento_promedio_ultimos_60_dias": float(s60['wind_speed_10m_max'].mean()),
        "temperatura_minima_ultimos_60_dias": float(s60['temperature_2m_min'].min()),
        "temperatura_maxima_ultimos_60_dias": float(s60['temperature_2m_max'].max()),
    }

def fetch_aws_stac_ndvi(coords: list, bbox: list, target_date_str: str) -> dict:
    """
    Busca escenas de Sentinel-2 L2A en Element 84 AWS STAC (API 100% Pública y Libre sin Claves),
    ordenadas por la fecha más RECIENTE y con nubosidad < 20%.
    """
    try:
        import rasterio
        from rasterio.mask import mask as rasterio_mask
        from rasterio.warp import transform_geom
        
        target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
        start_dt = target_dt - timedelta(days=120)
        
        stac_url = 'https://earth-search.aws.element84.com/v1/search'
        payload = json.dumps({
            'collections': ['sentinel-2-l2a'],
            'bbox': bbox,
            'datetime': f"{start_dt.strftime('%Y-%m-%d')}T00:00:00Z/{target_date_str}T23:59:59Z",
            'query': {'eo:cloud_cover': {'lt': 20}}
        }).encode('utf-8')
        
        req = urllib.request.Request(stac_url, data=payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as res:
            stac_res = json.loads(res.read().decode('utf-8'))
            
        features = stac_res.get('features', [])
        if not features:
            raise StockError('No hay escenas Sentinel-2 utilizables para la fecha solicitada.')
            
        best_item = sorted(features, key=lambda x: x['properties'].get('datetime', ''), reverse=True)[0]
        cloud_cover = best_item['properties'].get('eo:cloud_cover', 0.0)
        scene_id = best_item.get('id', '')
        scene_date = best_item['properties'].get('datetime', '')[:10]
        
        red_url = best_item['assets']['red']['href']
        nir_url = best_item['assets']['nir']['href']
        
        with rasterio.open(red_url) as ds_red, rasterio.open(nir_url) as ds_nir:
            polygon_geojson = {'type': 'Polygon', 'coordinates': [coords]} if len(coords) > 0 else {'type': 'Polygon', 'coordinates': [[[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]], [bbox[0], bbox[1]]]]}
            poly_utm = transform_geom('EPSG:4326', ds_red.crs, polygon_geojson)
            
            out_red, _ = rasterio_mask(ds_red, [poly_utm], crop=True)
            out_nir, _ = rasterio_mask(ds_nir, [poly_utm], crop=True)
            
            red = out_red[0].astype(float)
            nir = out_nir[0].astype(float)
            
            mask_valid = (nir + red) > 0
            if not np.any(mask_valid):
                raise StockError('La escena Sentinel-2 no contiene píxeles NDVI válidos.')
                
            ndvi = np.where(mask_valid, (nir - red) / (nir + red + 1e-6), np.nan)
            ndvi_vals = ndvi[~np.isnan(ndvi)]
            
            return {
                "nubosidad_pct": float(cloud_cover),
                "ndvi_promedio": float(np.mean(ndvi_vals)),
                "ndvi_min": float(np.min(ndvi_vals)),
                "ndvi_max": float(np.max(ndvi_vals)),
                "ndvi_std": float(np.std(ndvi_vals)),
                "scene_id": scene_id,
                "scene_date": scene_date
            }
    except StockError:
        raise
    except Exception as exc:
        raise StockError('No se pudo consultar una escena Sentinel-2 válida.') from exc


# --- ENDPOINTS FLASK ---

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "models_loaded": {"dmp": model_dmp is not None, "dmi": dmi_predictor is not None}})

@app.route('/predict/dmp', methods=['POST'])
def predict_dmp():
    """
    Endpoint para DMP.
    Soporta:
    1) Caso directo/offline (si viene 'ndvi_promedio' u otros features en el JSON)
    2) Caso satelital dinámico (si solo viene 'geojson' y 'nombre_potrero')
    """
    data_in = validate_dmp(request.get_json())

    # 1. Si vienen features directas en el body (como en mi_json.json)
    if "ndvi_promedio" in data_in and "latitud" in data_in:
        full_sample = data_in.copy()
        dias_periodo = data_in.get('dmp_dias_periodo', 10)
    else:
        # 2. Caso con GeoJSON / Coordenadas dinámicas (fetching clima y satélite)
        fecha_str = data_in.get('fecha', datetime.now().strftime("%Y-%m-%d"))
        geojson = data_in.get('geojson', {})
        
        if geojson.get('type') == 'Polygon':
            coords = geojson['coordinates'][0]
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            lat_center = float(sum(lats) / len(lats))
            lon_center = float(sum(lons) / len(lons))
            bbox = [min(lons), min(lats), max(lons), max(lats)]
        elif "latitud" in data_in and "longitud" in data_in:
            lat_center = float(data_in["latitud"])
            lon_center = float(data_in["longitud"])
            bbox = [lon_center - 0.02, lat_center - 0.02, lon_center + 0.02, lat_center + 0.02]
        else:
            lat_center = float(data_in.get('latitud', -28.4284))
            lon_center = float(data_in.get('longitud', -56.2880))
            bbox = [lon_center - 0.02, lat_center - 0.02, lon_center + 0.02, lat_center + 0.02]
            
        dt = datetime.strptime(fecha_str, "%Y-%m-%d")
        day_of_year = dt.timetuple().tm_yday
        sin_dia = math.sin(2 * math.pi * day_of_year / 365.25)
        cos_dia = math.cos(2 * math.pi * day_of_year / 365.25)
        
        clase_mapbiomas = fetch_mapbiomas_class(lat_center, lon_center, dt.year)
        weather_data = fetch_open_meteo_weather(lat_center, lon_center, fecha_str)
        coords_list = coords if 'coords' in locals() else []
        ndvi_data = fetch_aws_stac_ndvi(coords_list, bbox, fecha_str)
        
        full_sample = {
            "latitud": lat_center,
            "longitud": lon_center,
            "tipo_uso_suelo": data_in.get("tipo_uso_suelo", "Agrícola Núcleo"),
            "clase_cobertura_mapbiomas": clase_mapbiomas,
            "sin_dia_del_anio": sin_dia,
            "cos_dia_del_anio": cos_dia,
            **ndvi_data,
            **weather_data
        }
        dias_periodo = data_in.get('dmp_dias_periodo', 10)

    # Inferencia modelo DMP
    try:
        df_single = pd.DataFrame([full_sample])
        df_feat = add_agronomic_features(df_single)
        numeric_columns = [column for column in feature_columns_dmp if column not in cat_cols_dmp]
        if not np.isfinite(df_feat[numeric_columns].to_numpy(dtype=float)).all():
            raise ValueError('Variables no finitas.')
        if not all(column in df_feat for column in cat_cols_dmp):
            raise ValueError('Categorías faltantes.')
    except (KeyError, ValueError, TypeError) as exc:
        if 'ndvi_promedio' in data_in:
            raise PredictionInputError('Faltan variables DMP requeridas o contienen valores inválidos.') from exc
        raise StockError('Las fuentes no proporcionaron todas las variables DMP requeridas.') from exc
    
    # Extraer feature vector como diccionario ordenado antes de codificar categóricas
    feature_vector_dict = {}
    for col in feature_columns_dmp:
        if col in df_feat.columns:
            val = df_feat[col].values[0]
            if isinstance(val, (np.floating, float)):
                val = float(val)
            elif isinstance(val, (np.integer, int)):
                val = int(val)
            feature_vector_dict[col] = val

    df_feat[cat_cols_dmp] = encoder_dmp.transform(df_feat[cat_cols_dmp])
    
    X = df_feat[feature_columns_dmp]
    pred_dia = float(model_dmp.predict(X)[0])
    if not math.isfinite(pred_dia):
        raise StockError('El modelo DMP no produjo una predicción finita.')
    pred_dia = max(0.0, round(pred_dia, 2))
    pred_periodo = round(pred_dia * dias_periodo, 2)
    
    return jsonify({
        "datos_imagen_satelital": {
            "id_escena_sentinel2": full_sample.get("scene_id", "N/A"),
            "fecha_exacta_captura": full_sample.get("scene_date", fecha_str if 'fecha_str' in locals() else "N/A"),
            "nubosidad_pct": full_sample.get("nubosidad_pct", 0.0),
            "cobertura_suelo_mapbiomas": full_sample.get("clase_cobertura_mapbiomas", "N/A")
        },
        "feature_vector_enviado_al_modelo": feature_vector_dict,
        "prediccion": {
            "dmp_kg_ms_ha_dia": pred_dia,
            "dmp_kg_ms_ha_periodo": pred_periodo
        }
    })


@app.route('/predict/dmi', methods=['POST'])
def predict_dmi():
    """
    Endpoint para DMI.
    Recibe: { "animales": [ ... ] }
    Devuelve: { "predicciones": [ ... ], "advertencias": [ ... ] }
    """
    animales = validate_dmi(request.get_json(), dmi_predictor.metadata['weight_ranges_kg'])

    try:
        predicciones, advertencias = dmi_predictor.predict(animales)
        return jsonify({
            "predicciones": predicciones,
            "advertencias": advertencias
        })
    except Exception:
        app.logger.exception('Fallo inesperado en /predict/dmi')
        return jsonify({"error": "No se pudo ejecutar el modelo DMI."}), 500


@app.route('/predict/stock', methods=['POST'])
def predict_stock():
    """Calcula stock utilizable con GIS, referencias regionales y anomalía DMP."""
    data_in = request.get_json(silent=True)
    if not isinstance(data_in, dict):
        return jsonify({"estado": "ERROR", "error": "Body JSON requerido"}), 400

    required = ("fecha", "geojson", "consumo_diario_total_kg_ms")
    missing = [field for field in required if field not in data_in]
    if missing:
        return jsonify({
            "estado": "ERROR",
            "error": f"Faltan campos requeridos: {', '.join(missing)}",
        }), 400

    try:
        return jsonify(calculate_stock(data_in)), 200
    except StockInputError as exc:
        return jsonify({"estado": "ERROR", "error": str(exc)}), 400
    except StockCoverageError as exc:
        return jsonify({
            "estado": "NO_CALCULABLE", "codigo": "COBERTURA_NO_COMPATIBLE",
            "cobertura": exc.coverage, "error": str(exc),
        }), 422
    except StockError as exc:
        message = str(exc)
        source_markers = (
            "No se pudo consultar", "HTTP ", "Open-Meteo", "MapBiomas",
            "Sentinel-2", "escena", "píxeles NDVI",
        )
        status = 502 if any(marker in message for marker in source_markers) else 422
        return jsonify({"estado": "NO_CALCULABLE", "error": message}), status
    except Exception as exc:
        app.logger.exception("Fallo inesperado en /predict/stock")
        return jsonify({"estado": "ERROR", "error": str(exc)}), 500


@app.route('/intrapotrero/analizar', methods=['POST'])
def analyze_intrapaddock():
    from intrapaddock import analyze, ZoneError
    from intrapaddock_water import fetch_context
    try:
        return jsonify(analyze(request.get_json(silent=True), weather_resolver=fetch_context))
    except ZoneError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception:
        app.logger.exception('Fallo en análisis intrapotrero')
        return jsonify({"error": "No se pudo analizar la geometría del potrero."}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
