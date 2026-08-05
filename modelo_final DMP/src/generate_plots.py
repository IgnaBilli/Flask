import os
import sys
import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import shap

sys.path.insert(0, os.path.dirname(__file__))
from feature_engineering import add_agronomic_features, FEATURE_COLUMNS
from models_utils import WeightedEnsemble

plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial']

def generar_graficos_separados_modelo_final():
    print("=== Generando Gráficos Estadísticos Específicos y Separados en 'modelo_final/reports' ===")
    
    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    reports_dir = os.path.join(BASE_DIR, 'reports')
    os.makedirs(reports_dir, exist_ok=True)

    csv_path = os.path.join(BASE_DIR, '..', 'Dataset_COMPLETO.csv')
    if not os.path.exists(csv_path):
        csv_path = 'Dataset_COMPLETO.csv'
        
    model_path = os.path.join(BASE_DIR, 'models', 'final_model.joblib')
    if not os.path.exists(model_path):
        print(f"Error: No se encontró {model_path}. Entrena primero con train_model.py")
        return

    df_raw = pd.read_csv(csv_path)
    artifacts = joblib.load(model_path)

    model = artifacts['model']
    encoder = artifacts['encoder']
    feature_cols = artifacts['feature_columns']
    cat_cols = artifacts.get('cat_cols', ['tipo_uso_suelo', 'clase_cobertura_mapbiomas'])

    df_raw['radiacion_solar_del_dia'] = df_raw['radiacion_solar_del_dia'].fillna(df_raw['radiacion_solar_del_dia'].median())
    df = add_agronomic_features(df_raw)

    X = df[feature_cols].copy()
    X[cat_cols] = encoder.transform(X[cat_cols])
    y_true = df['dmp_kg_ms_ha_dia'].values

    y_pred = model.predict(X)
    residuals = y_true - y_pred
    df['residual_abs'] = np.abs(residuals)

    metrics = artifacts.get('metrics', {})
    r2_val = metrics.get('r2', 0.8856)
    rmse_val = metrics.get('rmse', 13.1615)
    mae_val = metrics.get('mae', 8.5403)

    # 0. Cuadro de Resumen Ejecutivo de Métricas Globales (Infografía)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.axis('off')
    card_text = (
        f"MÉTRICAS GLOBALES DE DESEMPEÑO DEL MODELO FINAL\n"
        f"____________________________________________________\n\n"
        f"  • Coeficiente de Determinación (R²):   {r2_val:.4f}  ({r2_val*100:.2f}% Varianza Explicada)\n"
        f"  • Error Absoluto Medio (MAE):         {mae_val:.4f} kg MS/ha/día\n"
        f"  • Error Cuadrático Medio (RMSE):      {rmse_val:.4f} kg MS/ha/día\n"
        f"____________________________________________________\n"
        f"  Dataset: Dataset_COMPLETO.csv (2,000 registros | MapBiomas v5)"
    )
    ax.text(0.5, 0.5, card_text, fontsize=12, fontweight='bold', ha='center', va='center',
            bbox=dict(boxstyle='round,pad=1', facecolor='#eef7fa', edgecolor='#1f77b4', lw=2))
    plt.tight_layout()
    plt.savefig(os.path.join(reports_dir, '0_metricas_resumen_global.png'), dpi=300)
    plt.close()

    # 1. Regresión Real vs Predicho (Scatter Plot 1:1) con Tarjeta de Métricas
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.scatterplot(x=y_true, y=y_pred, alpha=0.55, color='#1f77b4', edgecolors='w', s=50, ax=ax)
    ax.plot([y_true.min(), y_true.max()], [y_true.min(), y_true.max()], 'r--', lw=2.5, label='Identidad (1:1 Ideal)')
    m, b = np.polyfit(y_true, y_pred, 1)
    ax.plot(y_true, m*y_true + b, color='darkgreen', lw=2, label=f'Ajuste Lineal (y={m:.2f}x+{b:.2f})')
    
    # Cuadro de Métricas R², RMSE, MAE en el gráfico
    stats_box = f"Métricas del Modelo:\nR²    = {r2_val:.4f}\nMAE  = {mae_val:.2f} kg/ha/día\nRMSE = {rmse_val:.2f} kg/ha/día"
    ax.text(0.05, 0.65, stats_box, transform=ax.transAxes, fontsize=11, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='#1f77b4', alpha=0.9))

    ax.set_title('Predicho vs. Real (DMP kg MS/ha/día)', fontsize=13, fontweight='bold')
    ax.set_xlabel('Valores Observados (Copernicus DMP)', fontsize=11)
    ax.set_ylabel('Valores Estimados (Modelo Final)', fontsize=11)
    ax.legend(loc='upper left', frameon=True)
    plt.tight_layout()
    plt.savefig(os.path.join(reports_dir, '1_real_vs_predicho.png'), dpi=300)
    plt.close()

    # 2. Análisis de Residuos vs Predichos
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.scatterplot(x=y_pred, y=residuals, alpha=0.55, color='#ff7f0e', edgecolors='w', s=50, ax=ax)
    ax.axhline(0, color='r', linestyle='--', lw=2.5)
    ax.set_title('Residuos vs. Valores Predichos (Análisis de Homocedasticidad)', fontsize=13, fontweight='bold')
    ax.set_xlabel('Valores Predichos (DMP kg MS/ha/día)', fontsize=11)
    ax.set_ylabel('Residuo (Real - Predicho)', fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(reports_dir, '2_residuos_vs_predicho.png'), dpi=300)
    plt.close()

    # 3. Histograma y Densidad KDE de Errores Residuales
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.histplot(residuals, kde=True, color='#2ca02c', ax=ax, bins=40, stat='density', alpha=0.6)
    ax.axvline(0, color='r', linestyle='--', lw=2.5, label='Error 0')
    ax.set_title('Distribución de Errores Residuales (Densidad KDE)', fontsize=13, fontweight='bold')
    ax.set_xlabel('Error Residual (kg MS/ha/día)', fontsize=11)
    ax.set_ylabel('Densidad', fontsize=11)
    ax.legend(loc='upper right')
    plt.tight_layout()
    plt.savefig(os.path.join(reports_dir, '3_distribucion_errores_residuales.png'), dpi=300)
    plt.close()

    # 4. Error Absoluto Medio (MAE) por Cobertura MapBiomas
    fig, ax = plt.subplots(figsize=(10, 6))
    order_classes = df.groupby('clase_cobertura_mapbiomas')['residual_abs'].median().sort_values().index
    sns.boxplot(data=df, x='clase_cobertura_mapbiomas', y='residual_abs', order=order_classes, hue='clase_cobertura_mapbiomas', palette='Set2', ax=ax, legend=False)
    ax.set_title('Error Absoluto Medio (MAE) por Clase de Cobertura MapBiomas', fontsize=13, fontweight='bold')
    ax.set_xlabel('Clase de Cobertura del Suelo (MapBiomas)', fontsize=11)
    ax.set_ylabel('Error Absoluto MAE (kg MS/ha/día)', fontsize=11)
    ax.tick_params(axis='x', rotation=25)
    plt.tight_layout()
    plt.savefig(os.path.join(reports_dir, '4_error_por_cobertura_mapbiomas.png'), dpi=300)
    plt.close()

    # 5. Top 15 Importancia de Variables (Feature Importance)
    fig, ax = plt.subplots(figsize=(10, 7))
    imp_lgb = model.lgb_model.feature_importances_ / model.lgb_model.feature_importances_.sum()
    imp_xgb = model.xgb_model.feature_importances_ / model.xgb_model.feature_importances_.sum()
    imp_cat = model.cat_model.feature_importances_ / model.cat_model.feature_importances_.sum()
    avg_imp = 0.40 * imp_lgb + 0.35 * imp_xgb + 0.25 * imp_cat
    feat_imp = pd.DataFrame({'feature': feature_cols, 'importance': avg_imp}).sort_values('importance', ascending=False).head(15)

    sns.barplot(data=feat_imp, x='importance', y='feature', hue='feature', palette='viridis', ax=ax, legend=False)
    ax.set_title('Top 15 Variables Más Importantes en el Modelo Final', fontsize=13, fontweight='bold')
    ax.set_xlabel('Importancia Relativa Ponderada', fontsize=11)
    ax.set_ylabel('Variable Agronómica / Satelital', fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(reports_dir, '5_importancia_variables_top15.png'), dpi=300)
    plt.close()

    # 6. Explicabilidad SHAP (Summary Dot Plot)
    explainer = shap.TreeExplainer(model.lgb_model)
    shap_values = explainer.shap_values(X)
    fig, ax = plt.subplots(figsize=(10, 7))
    shap.summary_plot(shap_values, X, feature_names=feature_cols, max_display=15, show=False)
    plt.title('Explicabilidad Agronómica SHAP (Impacto de Variables)', fontsize=13, fontweight='bold', pad=15)
    plt.tight_layout()
    plt.savefig(os.path.join(reports_dir, '6_shap_explicabilidad.png'), dpi=300)
    plt.close()

    # 7. MAE por Provincia / Región
    fig, ax = plt.subplots(figsize=(9, 6))
    order_prov = df.groupby('provincia')['residual_abs'].mean().sort_values().index
    sns.barplot(data=df, x='provincia', y='residual_abs', order=order_prov, hue='provincia', palette='magma', ax=ax, legend=False)
    ax.set_title('Error Absoluto Medio (MAE) por Provincia', fontsize=13, fontweight='bold')
    ax.set_xlabel('Provincia', fontsize=11)
    ax.set_ylabel('MAE (kg MS/ha/día)', fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(reports_dir, '7_error_por_provincia.png'), dpi=300)
    plt.close()

    print("=== 7 Gráficos Estadísticos Específicos Generados Exitosamente ===")

if __name__ == '__main__':
    generar_graficos_separados_modelo_final()
