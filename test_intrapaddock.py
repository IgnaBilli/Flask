import json
import unittest
from intrapaddock import analyze, polygon, ZoneError, PARAMS

def box(x0=-59, x1=-58.99, y0=-35, y1=-34.99):
    return {'type': 'Polygon', 'coordinates': [[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}

class IntrapaddockTests(unittest.TestCase):
    def setUp(self):
        self.params = json.loads(PARAMS.read_text(encoding='utf-8'))
        self.keys = self.params['zonas']['pampa_deprimida']['ambientes']

    def run_analysis(self, zones, day='2026-09-27'):
        return analyze({'geojson':box(), 'fecha':day, 'configuracion':{'zonas':zones}},
            lambda field, params: {'seleccion_referencia':{'zona_id':'pampa_deprimida','perfiles_utilizados':self.keys}})

    def zone(self, id='a', kind='ambiente', geom=None, **extra):
        return dict(id=id,nombre=id,tipo=kind,geom=geom or box(),ambiente_id=self.keys[0],**extra)

    def test_unclassified_keeps_existing_reference(self):
        a=self.run_analysis([])
        self.assertEqual(a['factor_mensual'],[1]*12)
        self.assertAlmostEqual(a['superficie_total_ha'],a['superficie_pastoreable_ha'])

    def test_full_environment_replaces_reference_not_twice(self):
        a=self.run_analysis([self.zone()])
        for actual, expected in zip(a['referencia_ponderada_mensual'],self.params['curvas'][self.keys[0]]['mensual']):
            self.assertAlmostEqual(actual,expected)
        self.assertAlmostEqual(a['superficie_sin_clasificar_ha'],0)

    def test_partial_environment_weights_unclassified(self):
        a=self.run_analysis([self.zone(geom=box(x1=-58.995))])
        share=a['configuracion']['zonas'][0]['porcentaje']/100
        for m in range(12):
            expected=share*self.params['curvas'][self.keys[0]]['mensual'][m]+(1-share)*a['referencia_base_mensual'][m]
            self.assertAlmostEqual(a['referencia_ponderada_mensual'][m],expected,places=6)

    def test_rejects_outside_overlap_and_crossed_polygon(self):
        for zones in ([self.zone(geom=box(x1=-58.98))],[self.zone(),self.zone(id='b')]):
            with self.assertRaises(ZoneError): self.run_analysis(zones)
        with self.assertRaises(ZoneError):
            polygon({'type':'Polygon','coordinates':[[[-59,-35],[-58,-34],[-59,-34],[-58,-35],[-59,-35]]]})

    def test_inaccessible_union_dates_and_blocked_water(self):
        zones=[self.zone(kind='inaccesible',desde='2026-09-26',hasta='2026-09-27'),
               self.zone(id='b',kind='inaccesible',desde='2026-09-26',hasta='2026-09-27'),
               self.zone(id='w',kind='aguada')]
        active=self.run_analysis(zones)
        self.assertEqual(active['superficie_pastoreable_ha'],0)
        self.assertEqual(active['preferencia']['puntos'],[])
        self.assertEqual(active['factor_mensual'],[1]*12)
        expired=self.run_analysis(zones,'2026-09-28')
        self.assertAlmostEqual(expired['superficie_pastoreable_ha'],expired['superficie_total_ha'])
        self.assertTrue(expired['preferencia']['puntos'])

    def test_preference_is_inside_and_excludes_inaccessible(self):
        zones=[self.zone(id='w',kind='aguada',geom=box(x1=-58.999,y1=-34.999)),
               self.zone(id='b',kind='inaccesible',geom=box(x0=-58.995),desde='2026-09-27')]
        a=self.run_analysis(zones)
        self.assertTrue(a['preferencia']['puntos'])
        self.assertTrue(all(p['geom']['coordinates'][0]<-58.995 for p in a['preferencia']['puntos']))

if __name__=='__main__': unittest.main()
