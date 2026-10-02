import unittest
from unittest.mock import MagicMock, patch

from app import app
from stock.calculator import calculate_stock, StockError


POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [-56.29177828, -28.43191057],
        [-56.28468932, -28.43191057],
        [-56.28468932, -28.42626782],
        [-56.29177828, -28.42626782],
        [-56.29177828, -28.43191057],
    ]],
}


class StockEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch('stock.calculator.DmpPredictor')
    @patch('stock.calculator.fetch_mapbiomas')
    @patch('stock.calculator.resolve_gis_context')
    def test_unsupported_coverage_is_422_without_running_or_fabricating_stock(self, gis, coverage, predictor):
        gis.return_value = {
            'superficie_ha': 25, 'seleccion_referencia': {
                'zona_id': 'corrientes', 'perfiles_utilizados': ['pastos_cortos'], 'estado': 'PARCIAL'
            }
        }
        for name in ['Cultivos temporarios', 'Áreas urbanas', 'Cuerpos de agua']:
            coverage.return_value = {'clase_predominante': name}
            response = self.client.post('/predict/stock', json={
                'fecha': '2026-08-05', 'consumo_diario_total_kg_ms': 0, 'geojson': POLYGON
            })
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json['codigo'], 'COBERTURA_NO_COMPATIBLE')
            self.assertEqual(response.json['cobertura'], name)
            self.assertEqual(response.json['estado'], 'NO_CALCULABLE')
            self.assertNotIn('stock_final_utilizable', response.json)
        predictor.assert_not_called()

    @patch('app.calculate_stock', side_effect=StockError('MapBiomas no disponible'))
    def test_source_failure_remains_502(self, calculate):
        response = self.client.post('/predict/stock', json={
            'fecha': '2026-08-05', 'consumo_diario_total_kg_ms': 0, 'geojson': POLYGON
        })
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('codigo', response.json)

    def test_requires_the_three_contract_fields(self):
        response = self.client.post("/predict/stock", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("fecha", response.get_json()["error"])

    def test_rejects_future_dates_without_contacting_sources(self):
        response = self.client.post("/predict/stock", json={
            "fecha": "2099-01-01",
            "consumo_diario_total_kg_ms": 350,
            "geojson": POLYGON,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["estado"], "ERROR")

    @patch("app.calculate_stock")
    def test_returns_the_traceable_calculation_unchanged(self, calculate):
        calculate.return_value = {
            "estado": "OK",
            "metodologia": "gis_matriz_regional_por_anomalia_dmp_y_balance_30_dias",
            "crecimiento": {"crecimiento_utilizable_promedio_kg_ms_ha_dia": {"central": 2.18}},
            "stock_final_utilizable": {"valor_kg_ms_ha": {"central": 673.67}},
        }
        payload = {"fecha": "2026-08-05", "consumo_diario_total_kg_ms": 350, "geojson": POLYGON}
        response = self.client.post("/predict/stock", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["stock_final_utilizable"]["valor_kg_ms_ha"]["central"], 673.67)
        calculate.assert_called_once_with(payload)


class StockFormulaTest(unittest.TestCase):
    @patch("stock.calculator.calculate_dmp_observation")
    @patch("stock.calculator.DmpPredictor")
    @patch("stock.calculator.fetch_mapbiomas")
    @patch("stock.calculator.resolve_gis_context")
    def test_balance_uses_dmp_as_relative_factor_and_dmi_as_consumption(
        self, resolve_gis, fetch_mapbiomas, predictor_class, dmp_observation
    ):
        resolve_gis.return_value = {
            "superficie_ha": 50.0,
            "ecorregiones": [{"nombre": "Campos y Malezales", "porcentaje_superficie": 100}],
            "unidades_vegetacion": [{"codigo": "U27", "nombre_vulgar": "Campos y Urundayzales", "porcentaje_superficie": 100}],
            "seleccion_referencia": {
                "estado": "PARCIAL", "zona_id": "corrientes",
                "perfiles_utilizados": ["pastos_cortos", "flechillar", "pajonal", "malezal"],
                "justificacion": "prueba", "confianza_geografica": "ALTA", "confianza_ambiental": "BAJA",
            },
        }
        fetch_mapbiomas.return_value = {"estado": "DISPONIBLE", "clase_predominante": "Pasturas"}
        predictor_class.return_value = MagicMock(load_warnings=[], metrics={})

        def observation(*args, **kwargs):
            target = args[3]
            return {
                "fecha_objetivo": target.isoformat(), "dmp_kg_ms_ha_dia": 10.0,
                "escena": {"fecha": target.isoformat(), "fraccion_pixeles_validos": 1.0, "ndvi_promedio": 0.6},
                "clima_fecha": target.isoformat(),
            }
        dmp_observation.side_effect = observation

        result = calculate_stock({
            "nombre_potrero": "Prueba",
            "fecha": "2026-08-05",
            "consumo_diario_total_kg_ms": 350,
            "geojson": POLYGON,
        })
        self.assertEqual(len(result["dmp"]["periodos"]), 18)
        self.assertEqual(result["potrero"]["dias_calculo"], 90)
        self.assertAlmostEqual(result["consumo"]["acumulado_kg_ms_ha"], 350 / 50 * 90)
        self.assertTrue(all(period["factor_dmp_aplicado"] == 1 for period in result["dmp"]["periodos"]))
        gross = result["crecimiento"]["crecimiento_bruto_promedio_kg_ms_ha_dia"]["central"]
        usable = result["crecimiento"]["crecimiento_utilizable_promedio_kg_ms_ha_dia"]["central"]
        self.assertAlmostEqual(usable, gross * 0.5, places=3)
        initial = result["stock_inicial_estimado"]["valor_kg_ms_ha"]["central"]
        production = result["crecimiento"]["produccion_utilizable_acumulada_kg_ms_ha"]["central"]
        consumption = result["consumo"]["acumulado_kg_ms_ha"]
        final = result["stock_final_utilizable"]["valor_kg_ms_ha"]["central"]
        self.assertAlmostEqual(initial, production, delta=0.02)
        self.assertAlmostEqual(final, max(0, production - consumption), delta=0.02)


if __name__ == "__main__":
    unittest.main()
