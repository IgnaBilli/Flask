import json
import os
import sys
import math
from datetime import datetime, timedelta
import urllib.request
import pandas as pd
import numpy as np
import joblib
import rasterio
from rasterio.warp import transform_bounds

# Cargar módulos del modelo
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))

from feature_engineering import add_agronomic_features
import models_utils
sys.modules['models_utils'] = models_utils


def fetch_mapbiomas_class(lat: float, lon: float, year: int) -> str:
    """Consulta la API de MapBiomas Argentina para obtener la cobertura del suelo."""
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
            
            # Leyenda mapeada
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
                
            return mapping.get(pixel_val, "Cultivos temporarios")
    except Exception:
        return "Cultivos temporarios"


def fetch_open_meteo_weather(lat: float, lon: float, target_date_str: str) -> dict:
    """Consulta la API pública de Open-Meteo para reconstruir clima diario y acumulados."""
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
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode('utf-8'))
        
    daily = data['daily']
    df_w = pd.DataFrame(daily)
    
    # El día objetivo es la última fila
    row_today = df_w.iloc[-1]
    
    # Calcular acumulados
    def get_slice(days):
        return df_w.iloc[-(days):]
    
    s7 = get_slice(7)
    s14 = get_slice(14)
    s30 = get_slice(30)
    s60 = get_slice(60)
    
    weather_dict = {
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
    return weather_dict


# Configuración de credenciales Sentinel Hub
from sentinelhub import SHConfig, SentinelHubCatalog, SentinelHubRequest, DataCollection, Geometry, CRS, MimeType, bbox_to_dimensions

sh_config = SHConfig()
sh_config.sh_client_id = '8f976726-22ff-4f99-9832-1fee4080786c'
sh_config.sh_client_secret = 'E0HNvgzGzn1HdkDgKmZwc4NBVrsSl4fG'


def fetch_sentinel_hub_ndvi(geojson_geom: dict, target_date_str: str) -> dict:
    """
    Busca en el catálogo de Sentinel Hub la imagen más RECIENTE con nubosidad < 20%
    y procesa en tiempo real las bandas B04 y B08 recortadas exactamente al polígono.
    """
    target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    start_dt = target_dt - timedelta(days=90)
    
    aoi_geometry = Geometry(geometry=geojson_geom, crs=CRS.WGS84)
    catalog = SentinelHubCatalog(config=sh_config)
    
    time_interval = (start_dt.strftime("%Y-%m-%d"), target_dt.strftime("%Y-%m-%d"))
    
    try:
        search_res = list(catalog.search(DataCollection.SENTINEL2_L2A, bbox=aoi_geometry.bbox, time=time_interval))
    except Exception as e:
        search_res = []

    # Filtrar por nubes < 20%
    clean_scenes = [r for r in search_res if r['properties'].get('eo:cloud_cover', 100) < 20]
    
    if not clean_scenes:
        # Fallback si no hubiera < 20% en 90 días
        clean_scenes = sorted(search_res, key=lambda x: x['properties'].get('eo:cloud_cover', 100))
        
    if not clean_scenes:
        return {
            "nubosidad_pct": 0.0, "ndvi_promedio": 0.45, "ndvi_min": 0.10, "ndvi_max": 0.85, "ndvi_std": 0.12,
            "scene_id": "N/A", "scene_date": target_date_str
        }
        
    # Ordenar por fecha más reciente
    best_scene = sorted(clean_scenes, key=lambda x: x['properties']['datetime'], reverse=True)[0]
    cloud_cover = best_scene['properties'].get('eo:cloud_cover', 0.0)
    scene_id = best_scene.get('id', '')
    scene_date = best_scene['properties']['datetime'][:10]

    evalscript = """
    function setup() {
        return {
            input: ["B04", "B08", "dataMask"],
            output: { bands: 2, sampleType: "FLOAT32" }
        };
    }
    function evaluatePixel(sample) {
        if (sample.dataMask === 0) {
            return [NaN, NaN];
        }
        return [sample.B04, sample.B08];
    }
    """

    request = SentinelHubRequest(
        evalscript=evalscript,
        input_data=[SentinelHubRequest.input_data(
            data_collection=DataCollection.SENTINEL2_L2A,
            time_interval=(scene_date, scene_date)
        )],
        responses=[SentinelHubRequest.output_response('default', MimeType.TIFF)],
        geometry=aoi_geometry,
        size=bbox_to_dimensions(aoi_geometry.bbox, resolution=10),
        config=sh_config
    )

    try:
        data = request.get_data()
        if len(data) > 0:
            arr = data[0]
            b04 = arr[:, :, 0]
            b08 = arr[:, :, 1]
            
            mask_valid = ~np.isnan(b04) & ~np.isnan(b08) & ((b08 + b04) > 0)
            if np.any(mask_valid):
                ndvi_matrix = (b08[mask_valid] - b04[mask_valid]) / (b08[mask_valid] + b04[mask_valid] + 1e-6)
                
                return {
                    "nubosidad_pct": float(cloud_cover),
                    "ndvi_promedio": float(np.mean(ndvi_matrix)),
                    "ndvi_min": float(np.min(ndvi_matrix)),
                    "ndvi_max": float(np.max(ndvi_matrix)),
                    "ndvi_std": float(np.std(ndvi_matrix)),
                    "scene_id": scene_id,
                    "scene_date": scene_date
                }
    except Exception as e:
        pass

    return {
        "nubosidad_pct": float(cloud_cover), "ndvi_promedio": 0.45, "ndvi_min": 0.10, "ndvi_max": 0.85, "ndvi_std": 0.12,
        "scene_id": scene_id, "scene_date": scene_date
    }


def predict_potrero(input_file: str):
    with open(input_file, 'r', encoding='utf-8') as f:
        data_in = json.load(f)
        
    fecha_str = data_in.get('fecha', datetime.now().strftime("%Y-%m-%d"))
    geojson = data_in.get('geojson', {})
    
    if geojson.get('type') == 'Polygon':
        coords = geojson['coordinates'][0]
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        lat_center = sum(lats) / len(lats)
        lon_center = sum(lons) / len(lons)
        bbox = [min(lons), min(lats), max(lons), max(lats)]
    else:
        lat_center = data_in.get('latitud', -33.98)
        lon_center = data_in.get('longitud', -60.48)
        bbox = [lon_center - 0.02, lat_center - 0.02, lon_center + 0.02, lat_center + 0.02]
        
    dt = datetime.strptime(fecha_str, "%Y-%m-%d")
    day_of_year = dt.timetuple().tm_yday
    sin_dia = math.sin(2 * math.pi * day_of_year / 365.25)
    cos_dia = math.cos(2 * math.pi * day_of_year / 365.25)
    
    # 1. MapBiomas
    clase_mapbiomas = fetch_mapbiomas_class(lat_center, lon_center, dt.year)
    
    # 2. Clima
    weather_data = fetch_open_meteo_weather(lat_center, lon_center, fecha_str)
    
    # 3. NDVI vía Sentinel Hub API
    geojson_geom = geojson if geojson.get('type') else {'type': 'Polygon', 'coordinates': [[[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]], [bbox[0], bbox[1]]]]}
    ndvi_data = fetch_sentinel_hub_ndvi(geojson_geom, fecha_str)
    
    # Imprimir información detallada en consola antes del JSON final
    print("================================================================================")
    print("=== DATOS DE IMAGEN SATELITAL UTILIZADA Y VARIABLES PASADAS AL MODELO IA ===")
    print("================================================================================")
    print(f"ID Escena Satelital Sentinel-2 : {ndvi_data.get('scene_id')}")
    print(f"Fecha Exacta de Captura Imagen : {ndvi_data.get('scene_date')}")
    print(f"Nubosidad de la Imagen        : {ndvi_data.get('nubosidad_pct'):.2f}%")
    print(f"Cobertura Suelo MapBiomas     : {clase_mapbiomas}")
    print("--------------------------------------------------------------------------------")
    
    # Construir objeto completo de entrada
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
    
    # Cargar modelo final
    model_path = os.path.join(BASE_DIR, 'models', 'final_model.joblib')
    artifacts = joblib.load(model_path)
    model = artifacts['model']
    encoder = artifacts['encoder']
    feature_columns = artifacts['feature_columns']
    cat_cols = artifacts.get('cat_cols', ['tipo_uso_suelo', 'clase_cobertura_mapbiomas'])
    
    df_single = pd.DataFrame([full_sample])
    df_feat = add_agronomic_features(df_single)
    
    print("\n--- ATRIBUTOS Y VALORES ENVIADOS AL MODELO (FEATURE VECTOR) ---")
    for col in feature_columns:
        if col in df_feat.columns:
            val = df_feat[col].values[0]
            print(f"  • {col:45s} : {val}")
    print("--------------------------------------------------------------------------------\n")

    df_feat[cat_cols] = encoder.transform(df_feat[cat_cols])
    
    X = df_feat[feature_columns]
    pred_dia = float(model.predict(X)[0])
    pred_dia = max(0.0, round(pred_dia, 2))
    
    dias_periodo = data_in.get('dmp_dias_periodo', 10)
    pred_periodo = round(pred_dia * dias_periodo, 2)
    
    res = {
        "dmp_kg_ms_ha_dia": pred_dia,
        "dmp_kg_ms_ha_periodo": pred_periodo
    }
    
    print(json.dumps(res, indent=2))

if __name__ == '__main__':
    if len(sys.argv) > 1:
        inp = sys.argv[1]
    else:
        inp = os.path.join(os.path.dirname(__file__), 'potrero_ejemplo.json')
    predict_potrero(inp)
