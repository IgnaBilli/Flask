import numpy as np
import pandas as pd

def add_agronomic_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    def get_col(col_name, default_val=0.0):
        if col_name in df.columns:
            return df[col_name]
        return default_val

    df['ndvi_rango'] = df['ndvi_max'] - df['ndvi_min']
    df['ndvi_cv'] = df['ndvi_std'] / (df['ndvi_promedio'] + 1e-6)
    df['ndvi_relacion_max'] = df['ndvi_promedio'] / (df['ndvi_max'] + 1e-6)

    t_base = 8.0
    df['grados_dia_efectivos'] = np.maximum(0, df['temperatura_media_del_dia'] - t_base)
    df['amplitud_termica_dia'] = df['temperatura_maxima_del_dia'] - df['temperatura_minima_del_dia']

    t_max_7d = get_col('temperatura_maxima_ultimos_7_dias', df['temperatura_maxima_del_dia'])
    t_min_7d = get_col('temperatura_minima_ultimos_7_dias', df['temperatura_minima_del_dia'])
    df['amplitud_termica_7d'] = t_max_7d - t_min_7d

    df['par_est_dia'] = df['radiacion_solar_del_dia'] * 0.48
    df['par_est_7d'] = get_col('radiacion_solar_acumulada_ultimos_7_dias', df['radiacion_solar_del_dia'] * 7) * 0.48
    df['par_est_30d'] = get_col('radiacion_solar_acumulada_ultimos_30_dias', df['radiacion_solar_del_dia'] * 30) * 0.48

    rad_7d = get_col('radiacion_solar_acumulada_ultimos_7_dias', df['radiacion_solar_del_dia'] * 7)
    precip_7d = get_col('precipitacion_acumulada_ultimos_7_dias', df['precipitacion_del_dia'] * 7)
    df['ratio_precip_rad_7d'] = precip_7d / (rad_7d + 1.0)

    rad_30d = get_col('radiacion_solar_acumulada_ultimos_30_dias', df['radiacion_solar_del_dia'] * 30)
    precip_30d = get_col('precipitacion_acumulada_ultimos_30_dias', df['precipitacion_del_dia'] * 30)
    df['ratio_precip_rad_30d'] = precip_30d / (rad_30d + 1.0)

    rad_60d = get_col('radiacion_solar_acumulada_ultimos_60_dias', df['radiacion_solar_del_dia'] * 60)
    precip_60d = get_col('precipitacion_acumulada_ultimos_60_dias', df['precipitacion_del_dia'] * 60)
    df['ratio_precip_rad_60d'] = precip_60d / (rad_60d + 1.0)

    df['lue_proxy_dia'] = df['ndvi_promedio'] * df['par_est_dia']
    df['lue_proxy_7d'] = df['ndvi_promedio'] * df['par_est_7d']

    return df

FEATURE_COLUMNS = [
    'tipo_uso_suelo', 'clase_cobertura_mapbiomas', 'latitud', 'longitud', 'sin_dia_del_anio', 'cos_dia_del_anio',
    'nubosidad_pct', 'ndvi_promedio', 'ndvi_min', 'ndvi_max', 'ndvi_std',
    'ndvi_rango', 'ndvi_cv', 'ndvi_relacion_max',
    'temperatura_media_del_dia', 'temperatura_minima_del_dia', 'temperatura_maxima_del_dia',
    'precipitacion_del_dia', 'radiacion_solar_del_dia', 'humedad_relativa_del_dia', 'velocidad_del_viento_del_dia',
    'grados_dia_efectivos', 'amplitud_termica_dia', 'par_est_dia', 'lue_proxy_dia',
    'precipitacion_acumulada_ultimos_7_dias', 'radiacion_solar_acumulada_ultimos_7_dias',
    'temperatura_media_promedio_ultimos_7_dias', 'humedad_relativa_promedio_ultimos_7_dias',
    'amplitud_termica_7d', 'par_est_7d', 'ratio_precip_rad_7d', 'lue_proxy_7d',
    'precipitacion_acumulada_ultimos_30_dias', 'radiacion_solar_acumulada_ultimos_30_dias',
    'temperatura_media_promedio_ultimos_30_dias', 'humedad_relativa_promedio_ultimos_30_dias',
    'par_est_30d', 'ratio_precip_rad_30d',
    'precipitacion_acumulada_ultimos_60_dias', 'ratio_precip_rad_60d'
]
