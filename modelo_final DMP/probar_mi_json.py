import json
import joblib
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.feature_engineering import add_agronomic_features
from src.models_utils import WeightedEnsemble
import models_utils
sys.modules['models_utils'] = models_utils

def probar_modelo_final():
    """
    Script de inferencia para evaluar predicciones usando el modelo final con clase_cobertura_mapbiomas.
    Uso:
        python modelo_final/probar_mi_json.py ruta/a/tu_archivo.json
    """
    model_path = os.path.join(os.path.dirname(__file__), 'models', 'final_model.joblib')
    
    if not os.path.exists(model_path):
        print(f"Error: No se encontró el modelo en '{model_path}'.")
        print("Ejecuta primero: python modelo_final/src/train_model.py")
        return

    artifacts = joblib.load(model_path)
    model = artifacts['model']
    encoder = artifacts['encoder']
    feature_columns = artifacts['feature_columns']
    cat_cols = artifacts.get('cat_cols', ['tipo_uso_suelo', 'clase_cobertura_mapbiomas'])

    if len(sys.argv) > 1:
        json_path = sys.argv[1]
    else:
        json_path = os.path.join(os.path.dirname(__file__), 'mi_json.json')

    if not os.path.exists(json_path):
        print(f"Error: El archivo JSON '{json_path}' no existe.")
        return

    print(f"--- Leyendo datos desde: {json_path} ---")
    with open(json_path, 'r', encoding='utf-8') as f:
        datos_usuario = json.load(f)

    # 1. Preprocesar y transformar datos agronómicos
    df_single = pd.DataFrame([datos_usuario])
    df_feat = add_agronomic_features(df_single)

    # 2. Codificar variables categóricas
    df_feat[cat_cols] = encoder.transform(df_feat[cat_cols])

    # 3. Formatear matriz de entrada X
    X = df_feat[feature_columns]

    # 4. Generar Predicción
    pred_dia = float(model.predict(X)[0])
    pred_dia = max(0.0, round(pred_dia, 2))

    dias_periodo = datos_usuario.get('dmp_dias_periodo', 10)
    pred_periodo = round(pred_dia * dias_periodo, 2)

    resultado = {
        "dmp_kg_ms_ha_dia": pred_dia,
        "dmp_kg_ms_ha_periodo": pred_periodo
    }

    print("\n--- PREDICCIÓN OBTENIDA (MODELO FINAL) ---")
    print(json.dumps(resultado, indent=2))

if __name__ == '__main__':
    probar_modelo_final()
