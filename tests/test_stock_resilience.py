"""Regional estimate remains explicit when remote observations are unavailable."""
import contextlib
import io
import json
import math
import unittest
from unittest.mock import MagicMock, patch

from shapely.geometry import box, mapping
from app import app
from stock.calculator import calculate_stock, StockError

LOCATIONS = [(-54.6, -26.4), (-61.8, -24), (-59.301, -27.851),
             (-56.37, -28.45), (-62.745, -40.3), (-60.55, -33.95), (-60.3, -37.2),
             (-61.20436, -31.68509), (-59.0, -32.5), (-64.3, -36.6), (-67.5, -37.5)]


def payload(lon=-62.745, lat=-40.3, **kwargs):
    return {'fecha': '2026-10-02', 'dias_actualizacion': 5,
            'consumo_diario_total_kg_ms': 0,
            'geojson': mapping(box(lon-.001, lat-.001, lon+.001, lat+.001)), **kwargs}


def observation(*args):
    day = args[3]
    return {'fecha_objetivo': day.isoformat(), 'dmp_kg_ms_ha_dia': 20 if day.year == 2026 else 10,
            'escena': {'fecha': day.isoformat(), 'fraccion_pixeles_validos': 1, 'ndvi_promedio': .6},
            'clima_fecha': day.isoformat()}


class RegionalResilienceTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.coverage = self.stack.enter_context(patch('stock.calculator.fetch_mapbiomas',
            return_value={'estado': 'DISPONIBLE', 'clase_predominante': 'Pasturas'}))
        self.predictor = self.stack.enter_context(patch('stock.calculator.DmpPredictor',
            return_value=MagicMock(load_warnings=[], metrics={})))
        self.observation = self.stack.enter_context(patch('stock.calculator.calculate_dmp_observation',
            side_effect=StockError('Solo 0.0% de píxeles válidos dentro del potrero.')))

    def assert_regional(self, result):
        self.assertEqual(result['estado'], 'OK')
        self.assertTrue(result['respaldo_estimacion']['activo'])
        self.assertFalse(result['respaldo_estimacion']['medicion_real'])
        self.assertEqual(result['coherencia']['aplicabilidad_modelo'], 'BAJA')
        self.assertTrue(all(p['factor_dmp_original'] is None and p['factor_dmp_aplicado'] == 1
                            for p in result['dmp']['periodos']))
        json.dumps(result, allow_nan=False)

    def test_all_provinces_all_months_balance_without_images(self):
        for lon, lat in LOCATIONS:
            for month in range(1, 13):
                with self.subTest(lon=lon, month=month):
                    result = calculate_stock(payload(lon, lat, fecha=f'2025-{month:02d}-15'))
                    self.assert_regional(result)
                    production = result['crecimiento']['produccion_utilizable_acumulada_kg_ms_ha']['central']
                    self.assertGreaterEqual(production, 0)
                    self.assertEqual(result['stock_final_utilizable']['valor_kg_ms_ha']['central'], production)
                    self.assertIsNone(result['dmp']['periodos'][0]['dmp_actual'])

    def test_every_coverage_keeps_observed_class_and_uses_livestock_reference(self):
        for name in ['Bosques cerrados', 'Áreas urbanas', 'Cuerpos de agua', 'Silvicultura',
                     'Cultivos temporarios', 'No observado']:
            with self.subTest(coverage=name):
                self.coverage.return_value = {'estado': 'DISPONIBLE', 'clase_predominante': name}
                self.observation.reset_mock()
                result = calculate_stock(payload())
                self.assert_regional(result)
                self.assertEqual(result['ubicacion_y_ambiente']['mapbiomas']['clase_predominante'], name)
                self.assertTrue(result['supuesto_uso_ganadero']['activo'])
                if name != 'Cultivos temporarios':
                    self.observation.assert_not_called()

    def test_mapbiomas_and_weather_outages_do_not_fabricate_observations(self):
        self.coverage.side_effect = StockError('MapBiomas HTTP 503')
        self.observation.side_effect = StockError('Open-Meteo no disponible')
        result = calculate_stock(payload())
        self.assert_regional(result)
        self.assertEqual(result['ubicacion_y_ambiente']['mapbiomas']['estado'], 'NO_DISPONIBLE')
        self.assertIn('Open-Meteo', result['dmp']['periodos'][0]['motivo_respaldo'])

    def test_model_missing_still_uses_regional_reference(self):
        self.predictor.side_effect = StockError('Modelo ausente')
        result = calculate_stock(payload())
        self.assert_regional(result)
        self.assertIsNone(result['dmp']['modelo_sha256'])
        self.observation.assert_not_called()

    def test_historical_gap_preserves_current_observation_but_no_anomaly(self):
        def missing_history(*args):
            if args[3].year != 2026:
                raise StockError('Sin historia')
            return observation(*args)
        self.observation.side_effect = missing_history
        result = calculate_stock(payload())
        self.assert_regional(result)
        period = result['dmp']['periodos'][0]
        self.assertIsNotNone(period['dmp_actual'])
        self.assertEqual(period['dmp_historico']['cantidad_anios_validos'], 0)
        self.assertIsNone(period['dmp_historico']['mediana_kg_ms_ha_dia'])

    def test_valid_observations_keep_existing_adjustment(self):
        self.observation.side_effect = observation
        result = calculate_stock(payload())
        self.assertFalse(result['respaldo_estimacion']['activo'])
        period = result['dmp']['periodos'][0]
        self.assertEqual(period['factor_dmp_original'], 2)
        self.assertGreater(period['factor_dmp_aplicado'], 1)

    def test_mixed_periods_do_not_discard_usable_observations(self):
        def mixed(*args):
            if args[3].year == 2026 and args[3].month == 9:
                raise StockError('Bloque nublado')
            return observation(*args)
        self.observation.side_effect = mixed
        data = payload()
        del data['dias_actualizacion']
        result = calculate_stock(data)
        self.assertGreater(result['respaldo_estimacion']['periodos_regionales'], 0)
        self.assertGreater(result['respaldo_estimacion']['periodos_ajustados_dmp'], 0)

    def test_high_consumption_returns_zero_and_unmet_demand_not_negative_stock(self):
        result = calculate_stock(payload(consumo_diario_total_kg_ms=1_000_000))
        self.assert_regional(result)
        self.assertEqual(result['stock_final_utilizable']['valor_kg_ms_ha']['central'], 0)
        self.assertGreater(result['balance_stock']['demanda_no_cubierta_kg_ms_ha']['central'], 0)

    def test_soft_budget_stops_new_remote_observations(self):
        with patch('stock.calculator.time.monotonic', side_effect=[0, 121]):
            result = calculate_stock(payload())
        self.assert_regional(result)
        self.observation.assert_not_called()

    def test_stock_endpoint_returns_200_for_pixel_failure(self):
        response = app.test_client().post('/predict/stock', json=payload())
        self.assertEqual(response.status_code, 200)
        self.assert_regional(response.json)

    def test_bad_input_and_outside_scope_are_not_hidden(self):
        for data in [payload(fecha='2099-01-01'), payload(dias_actualizacion=0),
                     payload(consumo_diario_total_kg_ms=-1)]:
            response = app.test_client().post('/predict/stock', json=data)
            self.assertEqual(response.status_code, 400)
        self.coverage.assert_not_called()
        self.observation.assert_not_called()
        with self.assertRaises(StockError):
            calculate_stock(payload(-65.5, -43.3))


if __name__ == '__main__':
    unittest.main()
