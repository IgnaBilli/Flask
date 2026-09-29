import json
import unittest
from datetime import date
from shapely.geometry import shape
from intrapaddock import analyze, ZoneError
from intrapaddock_climate import coverage, build_comparison
from intrapaddock_water import summarize_daily, unavailable
from test_intrapaddock import box
from test_intrapaddock_water import WaterTests


def missing_reference(field, params):
    raise ValueError("No regional curve")


class ClimateCoverageTests(unittest.TestCase):
    def test_target_provinces_including_previously_uncovered_regions(self):
        # Inland locations include both ends of provinces, beyond old bboxes.
        sites=[(-55.5,-27.4,'Misiones'),(-54.45,-26,'Misiones'),(-58,-29,'Corrientes'),
               (-60,-27,'Chaco'),(-62.5,-25.5,'Chaco'),(-58.5,-26,'Formosa'),
               (-61.8,-23.6,'Formosa'),(-59,-35,'Buenos Aires'),(-62.5,-40,'Buenos Aires')]
        for lon,lat,province in sites:
            with self.subTest(province=province,lon=lon):
                geom=box(lon,lon+.001,lat,lat+.001)
                a=analyze({'geojson':geom,'fecha':'2026-09-29'},missing_reference)
                comparison=a['comparacion_climatica']
                self.assertTrue(comparison['cobertura']['incluido'])
                self.assertIn(province,comparison['cobertura']['provincias'])
                self.assertEqual(a['factor_mensual'],[1]*12)
                self.assertEqual(a['referencia_base_mensual'],[None]*12)
                self.assertIsNone(comparison['estimacion_kg_ms_ha_dia'])
                self.assertIsNone(comparison['diferencia_porcentual'])
                self.assertFalse(comparison['aplicado_al_balance'])
                json.dumps(a,allow_nan=False)

    def test_caba_neighbours_and_international_borders_not_claimed(self):
        for lon,lat in [(-58.44,-34.61),(-60.7,-31.6),(-55.9,-27.3),(-70,-40)]:
            geom=box(lon,lon+.001,lat,lat+.001)
            self.assertFalse(coverage(shape(geom))['incluido'])
            with self.assertRaises(ZoneError):
                analyze({'geojson':geom,'fecha':'2026-09-29'},missing_reference)

    def test_same_climate_never_mints_relief_coefficients(self):
        geom=box(-55.5,-55.499,-27.4,-27.399)
        for position in ('loma','media_loma','bajo'):
            zone={'id':'a','nombre':'Zona','tipo':'ambiente','posicion':position,'geom':geom}
            a=analyze({'geojson':geom,'fecha':'2026-09-29','configuracion':{'zonas':[zone]}},missing_reference)
            self.assertEqual(a['configuracion']['zonas'][0]['aporte_mensual_kg_ms_ha_dia'],[None]*12)
            self.assertEqual(a['referencia_accesible_mensual'],[None]*12)
            self.assertEqual(a['comparacion_climatica']['estado'],'sin_modelo_validado')

    def test_missing_weather_is_not_a_zero_or_growth_prediction(self):
        c=build_comparison(shape(box()),unavailable(),'2026-09-29',[20]*12)
        self.assertIsNone(c['periodo_climatico'])
        self.assertEqual(c['referencia_regional_kg_ms_ha_dia'],20)
        self.assertIsNone(c['estimacion_kg_ms_ha_dia'])

    def test_temperature_optional_but_complete_not_zero_filled(self):
        payload=WaterTests().payload()
        payload['daily_units']['temperature_2m_mean']='°C'
        payload['daily']['temperature_2m_mean']=[15]*23+[22]*7
        a=summarize_daily(payload,date(2026,9,26))
        self.assertEqual(a['periodos'][0]['temperatura_media_c'],22)
        self.assertEqual(a['periodos'][1]['temperatura_media_c'],16.6)
        payload['daily']['temperature_2m_mean'][0]=None
        b=summarize_daily(payload,date(2026,9,26))
        self.assertIsNone(b['periodos'][1]['temperatura_media_c'])
        self.assertTrue(b['disponible'])


if __name__=='__main__': unittest.main()
