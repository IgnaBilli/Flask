import json
import sys
from pathlib import Path

DIR_ACTUAL = Path(__file__).resolve().parent
INPUT_PATH = DIR_ACTUAL / "input.json"
OUTPUT_PATH = DIR_ACTUAL / "output.json"

sys.path.insert(0, str(DIR_ACTUAL))

from src.predictor import HerdPredictor


def main() -> None:
    try:
        contenido = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"No se encontró el archivo de entrada: {INPUT_PATH}")
    except json.JSONDecodeError as error:
        raise SystemExit(f"El archivo input.json no es un JSON válido: {error}")

    animales = contenido.get("animales")
    if not isinstance(animales, list) or not animales:
        raise SystemExit("input.json debe contener una lista no vacía llamada 'animales'.")

    try:
        predictor = HerdPredictor()
        predicciones, advertencias = predictor.predict(animales)
    except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"No se pudo ejecutar la predicción: {error}")

    salida = {
        "predicciones": predicciones,
        "advertencias": advertencias,
    }
    OUTPUT_PATH.write_text(
        json.dumps(salida, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Predicción completada con éxito. Resultado guardado en: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
