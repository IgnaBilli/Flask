# Paquete Modelo Final e Inferencia (v1)

Este directorio contiene todo lo necesario para ejecutar la inferencia del modelo (v1) prediciendo el consumo diario de materia seca (DMI) de ganado vacuno.

## Contenido de la Carpeta

- `ejecutar.py`: Script principal de prueba/ejecución. Lee `input.json` y genera `output.json`.
- `input.json`: Archivo con datos de entrada para la predicción de los animales.
- `output.json`: Archivo donde se guardan los resultados predichos y advertencias.
- `models/`: Contiene el modelo v1 en formato joblib (`dmi_model.joblib`).
- `src/`: Código fuente modularizado (`predictor.py`, `features.py`, `config.py`).
- `requirements.txt`: Dependencias requeridas para ejecutar la inferencia.

## Instrucciones de Uso

1. Instalar las dependencias (si no las tienes instaladas):
   ```bash
   pip install -r requirements.txt
   ```

2. Ejecutar la inferencia:
   ```bash
   python ejecutar.py
   ```
