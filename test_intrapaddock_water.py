import unittest
from datetime import date, timedelta
from unittest.mock import patch
import json
from io import BytesIO

from intrapaddock_water import summarize_daily, fetch_context, zone_reading, unavailable, _cache
from test_intrapaddock import IntrapaddockTests
from intrapaddock import ZoneError


class WaterTests(unittest.TestCase):
    def payload(self, rain=1, et0=3):
        end = date(2026, 9, 26)
        return {"daily_units": {"precipitation_sum": "mm", "et0_fao_evapotranspiration": "mm"},
                "daily": {"time": [(end-timedelta(days=i)).isoformat() for i in range(29,-1,-1)],
                          "precipitation_sum": [rain]*30, "et0_fao_evapotranspiration": [et0]*30}}

    def test_complete_windows_and_signs(self):
        for rain, expected in [(1,-60),(3,0),(5,60)]:
            result=summarize_daily(self.payload(rain),date(2026,9,26))
            self.assertEqual(result["periodos"][1]["balance_mm"],expected)
            self.assertEqual(result["periodos"][0]["dias"],7)
            self.assertEqual(result["periodos"][0]["desde"],"2026-09-20")

    def test_missing_invalid_units_and_dates_are_not_zero_filled(self):
        for broken in (None, float('nan'), -1, True):
            data=self.payload();data['daily']['precipitation_sum'][0]=broken
            with self.assertRaises(ValueError):summarize_daily(data,date(2026,9,26))
        data=self.payload();data['daily']['time'][0]='2026-08-29'
        with self.assertRaises(ValueError):summarize_daily(data,date(2026,9,26))
        data=self.payload();data['daily_units']['precipitation_sum']='inch'
        with self.assertRaises(ValueError):summarize_daily(data,date(2026,9,26))

    @patch('intrapaddock_water.urlopen')
    @patch('intrapaddock_water.argentina_today',return_value=date(2026,9,27))
    def test_current_day_excluded_cached_and_outage_safe(self, _today, get):
        _cache.clear();get.return_value=BytesIO(json.dumps(self.payload()).encode())
        a=fetch_context(-35,-59,'2026-09-27')
        self.assertTrue(a['disponible'])
        self.assertIn('end_date=2026-09-26',get.call_args.args[0])
        a['periodos'][0]['balance_mm']=999
        self.assertNotEqual(fetch_context(-35,-59,'2026-09-27')['periodos'][0]['balance_mm'],999)
        self.assertEqual(get.call_count,1)
        _cache.clear();get.side_effect=TimeoutError()
        self.assertFalse(fetch_context(-35,-59,'2026-09-27')['disponible'])

    def test_no_soil_diagnosis_or_growth_change_from_climate(self):
        for rain in (0,20):
            climate=summarize_daily(self.payload(rain),date(2026,9,26))
            for position in ('loma','media_loma','bajo','sin_definir'):
                r=zone_reading({'posicion':position},climate,'2026-09-27')
                self.assertEqual(r['estado_suelo'],'Sin confirmar')
                self.assertEqual(r['factor_aplicado'],1)
        obs={'posicion':'bajo','observacion_hidrica':{'estado':'anegado','fecha':'2026-09-26'}}
        self.assertEqual(zone_reading(obs,unavailable(),'2026-09-27')['estado_suelo'],'Sin confirmar')
        self.assertEqual(zone_reading(obs,unavailable(),'2026-09-26')['estado_suelo'],'Con agua en superficie')


class ObservationTests(IntrapaddockTests):
    def test_observation_round_trip_and_validation(self):
        obs={'estado':'anegado','fecha':'2026-09-27'}
        a=self.run_analysis([self.zone(posicion='bajo',observacion_hidrica=obs)])
        self.assertEqual(a['configuracion']['zonas'][0]['observacion_hidrica'],obs)
        self.assertEqual(a['factor_mensual'],[1]*12)
        self.assertEqual(a['superficie_pastoreable_ha'],a['superficie_total_ha'])
        for invalid in [{'estado':'inventado','fecha':'2026-09-27'},{'estado':'seco','fecha':'2026-09-28'},{'estado':'seco'}]:
            with self.assertRaises(ZoneError):self.run_analysis([self.zone(observacion_hidrica=invalid)])


if __name__=='__main__':unittest.main()
