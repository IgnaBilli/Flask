import json
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import KFold
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.preprocessing import OrdinalEncoder
import lightgbm as lgb
import xgboost as xgb
from catboost import CatBoostRegressor
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from feature_engineering import add_agronomic_features, FEATURE_COLUMNS
from models_utils import WeightedEnsemble

def train_final_model():
    print("=== Entrenando Modelo Final (Dataset COMPLETO con MapBiomas) ===")
    
    csv_path = os.path.join(os.path.dirname(__file__), '../../Dataset_COMPLETO.csv')
    if not os.path.exists(csv_path):
        csv_path = 'Dataset_COMPLETO.csv'
        
    df_raw = pd.read_csv(csv_path)
    df_raw['radiacion_solar_del_dia'] = df_raw['radiacion_solar_del_dia'].fillna(df_raw['radiacion_solar_del_dia'].median())

    df = add_agronomic_features(df_raw)
    X = df[FEATURE_COLUMNS].copy()
    y = df['dmp_kg_ms_ha_dia'].values

    cat_cols = ['tipo_uso_suelo', 'clase_cobertura_mapbiomas']
    encoder = OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)
    X[cat_cols] = encoder.fit_transform(X[cat_cols])

    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    oof_preds = np.zeros(len(df))

    for fold, (train_idx, val_idx) in enumerate(kf.split(X, y), 1):
        X_train, y_train = X.iloc[train_idx], y[train_idx]
        X_val, y_val = X.iloc[val_idx], y[val_idx]

        m_lgb = lgb.LGBMRegressor(n_estimators=450, learning_rate=0.03, num_leaves=35, max_depth=8, subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1, n_jobs=1)
        m_xgb = xgb.XGBRegressor(n_estimators=450, learning_rate=0.03, max_depth=7, subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=1)
        m_cat = CatBoostRegressor(iterations=450, learning_rate=0.03, depth=7, random_seed=42, verbose=0)

        m_lgb.fit(X_train, y_train)
        m_xgb.fit(X_train, y_train)
        m_cat.fit(X_train, y_train)

        preds = 0.40 * m_lgb.predict(X_val) + 0.35 * m_xgb.predict(X_val) + 0.25 * m_cat.predict(X_val)
        oof_preds[val_idx] = preds

    r2 = r2_score(y, oof_preds)
    rmse = np.sqrt(mean_squared_error(y, oof_preds))
    mae = mean_absolute_error(y, oof_preds)

    print(f"\n=== RESULTADOS MODELO FINAL (con clase_cobertura_mapbiomas) ===")
    print(f"OOF R²   : {r2:.4f}")
    print(f"OOF RMSE : {rmse:.4f} kg MS/ha/día")
    print(f"OOF MAE  : {mae:.4f} kg MS/ha/día")

    final_lgb = lgb.LGBMRegressor(n_estimators=450, learning_rate=0.03, num_leaves=35, max_depth=8, subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1, n_jobs=1)
    final_xgb = xgb.XGBRegressor(n_estimators=450, learning_rate=0.03, max_depth=7, subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=1)
    final_cat = CatBoostRegressor(iterations=450, learning_rate=0.03, depth=7, random_seed=42, verbose=0)

    final_lgb.fit(X, y)
    final_xgb.fit(X, y)
    final_cat.fit(X, y)

    ensemble = WeightedEnsemble(final_lgb, final_xgb, final_cat)

    models_dir = os.path.join(os.path.dirname(__file__), '../models')
    os.makedirs(models_dir, exist_ok=True)

    artifacts = {
        'model': ensemble,
        'encoder': encoder,
        'feature_columns': FEATURE_COLUMNS,
        'cat_cols': cat_cols,
        'metrics': {'r2': float(r2), 'rmse': float(rmse), 'mae': float(mae)}
    }

    save_path = os.path.join(models_dir, 'final_model.joblib')
    joblib.dump(artifacts, save_path)
    print(f"Modelo final guardado en: '{save_path}'")

if __name__ == '__main__':
    train_final_model()
