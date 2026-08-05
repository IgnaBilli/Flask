import requests
import json

url = "http://127.0.0.1:5000/predict/dmp"
payload = {
    "nombre_potrero": "Potrero Corrientes",
    "geojson": {
      "type": "Polygon",
      "coordinates": [[
        [-56.285814598, -28.426267824],
        [-56.291778278, -28.426555376],
        [-56.290627827, -28.431910566],
        [-56.289679751, -28.431735996],
        [-56.28468932, -28.427751216],
        [-56.285814598, -28.426267824]
      ]]
    }
}

try:
    response = requests.post(url, json=payload, timeout=30)
    print("=== RESPUESTA DEL ENDPOINT /predict/dmp ===")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
except Exception as e:
    print(f"Error al consultar el endpoint: {e}")
