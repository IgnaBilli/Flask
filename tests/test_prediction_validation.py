import math
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from app import app, fetch_mapbiomas_class, fetch_aws_stac_ndvi
from stock import StockError
from test_stock_endpoint import POLYGON


class PredictionValidationTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_dmi_rejects_invalid_inputs_before_inference(self):
        valid = {"animal_id": "test", "peso_vivo_kg": 400, "categoria_terrabovina": "Novillo"}
        cases = [[], "bad", {"animales": []}, {"animales": [None]},
                 {"animales": [valid, valid]}]
        for key, value in [("peso_vivo_kg", 0), ("peso_vivo_kg", -1), ("peso_vivo_kg", "NaN"),
                           ("peso_vivo_kg", "Infinity"), ("peso_vivo_kg", True),
                           ("categoria_terrabovina", "INVALID"), ("categoria_terrabovina", {}),
                           ("animal_id", ""), ("condicion_corporal", 99)]:
            cases.append({"animales": [{**valid, key: value}]})
        with patch('app.dmi_predictor.predict') as predict:
            for payload in cases:
                with self.subTest(payload=payload):
                    response = self.client.post('/predict/dmi', json=payload)
                    self.assertEqual(response.status_code, 400)
                    self.assertTrue(response.is_json)
            predict.assert_not_called()

    def test_dmi_real_model_returns_finite_predictions_for_all_categories(self):
        animals = [{"animal_id": str(i), "peso_vivo_kg": weight, "categoria_terrabovina": category}
                   for i, (category, weight) in enumerate([
                       ('Ternero/Ternera', 150), ('Vaquilla', 300), ('Novillo', 400), ('Vaca', 450), ('Toro', 600)])]
        response = self.client.post('/predict/dmi', json={"animales": animals})
        self.assertEqual(response.status_code, 200, response.get_json())
        predictions = response.get_json()['predicciones']
        self.assertEqual(len(predictions), 5)
        for result in predictions:
            self.assertTrue(math.isfinite(result['dmi_kg_dia']))
            self.assertGreater(result['dmi_kg_dia'], 0)

    def test_dmp_real_model_accepts_the_repository_sample(self):
        sample = Path(__file__).resolve().parents[1] / 'modelo_final DMP' / 'mi_json.json'
        payload = json.loads(sample.read_text(encoding='utf-8'))
        payload['dmp_dias_periodo'] = '3'
        response = self.client.post('/predict/dmp', json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        prediction = response.get_json()['prediccion']
        self.assertTrue(math.isfinite(prediction['dmp_kg_ms_ha_dia']))
        self.assertGreaterEqual(prediction['dmp_kg_ms_ha_dia'], 0)
        self.assertAlmostEqual(prediction['dmp_kg_ms_ha_periodo'], prediction['dmp_kg_ms_ha_dia'] * 3)

    def test_dmp_rejects_invalid_input_before_sources(self):
        cases = [[], "bad", {"nombre_potrero": "sin geometria"},
                 {"ndvi_promedio": 0.5, "latitud": -28.4, "longitud": -56.3},
                 {"geojson": {"type": "Polygon", "coordinates": []}},
                 {"geojson": POLYGON, "fecha": "2026-02-30"},
                 {"geojson": POLYGON, "dmp_dias_periodo": -1}]
        with patch('app.fetch_mapbiomas_class') as source:
            for payload in cases:
                with self.subTest(payload=payload):
                    response = self.client.post('/predict/dmp', json=payload)
                    self.assertEqual(response.status_code, 400)
                    self.assertTrue(response.is_json)
            source.assert_not_called()

    def test_unavailable_sources_never_return_fabricated_observations(self):
        with patch('app.urllib.request.urlopen', side_effect=TimeoutError('offline')):
            with self.assertRaises(StockError):
                fetch_mapbiomas_class(-28.4, -56.3, 2026)
            with self.assertRaises(StockError):
                fetch_aws_stac_ndvi(POLYGON['coordinates'][0], [-56.3, -28.5, -56.2, -28.4], '2026-08-05')

    def test_dmp_source_error_is_json_502(self):
        with patch('app.fetch_mapbiomas_class', side_effect=StockError('MapBiomas no disponible')):
            response = self.client.post('/predict/dmp', json={"geojson": POLYGON, "fecha": "2026-08-05"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()['estado'], 'NO_CALCULABLE')

    def test_stock_rejects_non_finite_consumption_before_sources(self):
        with patch('stock.calculator.resolve_gis_context') as source:
            for value in ['NaN', 'Infinity', '-Infinity', True]:
                with self.subTest(value=value):
                    response = self.client.post('/predict/stock', json={
                        'fecha': '2026-08-05', 'geojson': POLYGON, 'consumo_diario_total_kg_ms': value})
                    self.assertEqual(response.status_code, 400)
            source.assert_not_called()

    def test_malformed_json_and_health(self):
        for endpoint in ['/predict/dmi', '/predict/dmp']:
            response = self.client.post(endpoint, data='{', content_type='application/json')
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.is_json)
        self.assertEqual(self.client.get('/health').get_json()['status'], 'ok')

    def test_stock_rejects_open_and_three_dimensional_rings(self):
        ring = POLYGON['coordinates'][0]
        for coords in [ring[:-1], [point + [0] for point in ring]]:
            response = self.client.post('/predict/stock', json={
                'fecha': '2026-08-05', 'consumo_diario_total_kg_ms': 0,
                'geojson': {'type': 'Polygon', 'coordinates': [coords]}})
            self.assertEqual(response.status_code, 400)
