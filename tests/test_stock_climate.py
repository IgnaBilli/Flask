import json
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from app import app  # Initializes the model import paths used in production.
from stock.calculator import fetch_weather, calculate_dmp_observation


class StockClimateTest(unittest.TestCase):
    @patch('stock.calculator.http_json')
    def test_date_is_last_complete_weather_day_not_requested_date(self, http):
        http.return_value = {'daily': {
            'time': ['2026-10-01', '2026-10-02'],
            'temperature_2m_mean': [-2.5, None], 'temperature_2m_min': [-4, None],
            'temperature_2m_max': [3, None], 'precipitation_sum': [0, None],
            'shortwave_radiation_sum': [12, None], 'relative_humidity_2m_mean': [None, None],
            'wind_speed_10m_max': [8, None],
        }}
        weather = fetch_weather(-35, -60, date(2026, 10, 2))
        self.assertEqual(weather['fecha_dato'], '2026-10-01')
        self.assertEqual(weather['temperatura_media_del_dia'], -2.5)
        self.assertEqual(weather['precipitacion_del_dia'], 0)

    @patch('stock.calculator.fetch_weather')
    @patch('stock.calculator.find_valid_scene')
    def test_observation_retains_real_climate_without_changing_model_inputs(self, scene, weather):
        scene.return_value = dict(scene_id='s2', scene_date='2026-10-02', dias_desfase=1,
            nubosidad_escena_pct=0, nubosidad_aoi_pct=0, fraccion_pixeles_validos=1,
            pixeles_validos=50, ndvi_promedio=.6, ndvi_min=.4, ndvi_max=.8, ndvi_std=.1)
        weather.return_value = dict(fecha_dato='2026-10-01', temperatura_media_del_dia=-2.5,
            precipitacion_del_dia=0, humedad_relativa_del_dia=float('nan'))
        predictor = MagicMock()
        predictor.predict.return_value = 20
        result = calculate_dmp_observation(predictor, None, {}, date(2026, 10, 3), -35, -60, 'pastura', 'pastura', {})
        self.assertEqual(result['clima'], dict(fuente='OPEN_METEO_ARCHIVE', fecha='2026-10-01',
            temperatura=-2.5, precipitacion=0, humedad=None))
        self.assertEqual(result['clima_fecha'], '2026-10-01')
        self.assertNotIn('fecha_dato', predictor.predict.call_args.args[3])
        self.assertEqual(result['dmp_kg_ms_ha_dia'], 20)
        json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
