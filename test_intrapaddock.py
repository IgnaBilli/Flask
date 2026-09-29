import json
import unittest
from shapely.geometry import shape
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

    def test_relief_and_retired_curves_never_change_growth(self):
        for position in ['sin_definir', 'loma', 'media_loma', 'bajo']:
            for retired in [None, 'malezal', 'pajonal', 'flechillar', 'pastos_cortos']:
                with self.subTest(position=position, retired=retired):
                    z=self.zone(posicion=position)
                    z.pop('ambiente_id')
                    if retired: z['ambiente_id']=retired
                    a=self.run_analysis([z])
                    self.assertEqual(a['factor_mensual'],[1]*12)
                    self.assertEqual(a['referencia_ponderada_mensual'],a['referencia_base_mensual'])
                    self.assertEqual(a['catalogo'],[])
                    self.assertNotIn('ambiente_id',a['configuracion']['zonas'][0])
                    self.assertEqual(a['configuracion']['zonas'][0]['posicion'],position)
                    self.assertAlmostEqual(a['superficie_sin_clasificar_ha'],0)

    def test_partial_relief_and_inaccessible_only_affect_access(self):
        a=self.run_analysis([self.zone(geom=box(x1=-58.995)),
            self.zone(id='blocked',kind='inaccesible',geom=box(x1=-58.995),desde='2026-09-27')])
        self.assertEqual(a['factor_mensual'],[1]*12)
        share=a['superficie_pastoreable_ha']/a['superficie_total_ha']
        self.assertAlmostEqual(share,.5,places=3)
        for m in range(12):
            self.assertAlmostEqual(a['referencia_accesible_mensual'][m],share*a['referencia_base_mensual'][m])

    def test_rejects_outside_overlap_and_crossed_polygon(self):
        for zones in ([self.zone(geom=box(x1=-58.98))],[self.zone(),self.zone(id='b')]):
            with self.assertRaises(ZoneError): self.run_analysis(zones)
        with self.assertRaises(ZoneError):
            polygon({'type':'Polygon','coordinates':[[[-59,-35],[-58,-34],[-59,-34],[-58,-35],[-59,-35]]]})

    def test_inaccessible_union_dates_and_blocked_water(self):
        zones=[self.zone(kind='inaccesible',desde='2026-09-26',hasta='2026-09-27'),
               self.zone(id='b',kind='inaccesible',desde='2026-09-26',hasta='2026-09-27'),
               self.zone(id='w',kind='aguada',geom=box(x1=-58.995))]
        active=self.run_analysis(zones)
        self.assertEqual(active['superficie_pastoreable_ha'],0)
        self.assertEqual(active['preferencia']['puntos'],[])
        self.assertEqual(active['factor_mensual'],[1]*12)
        expired=self.run_analysis(zones,'2026-09-28')
        self.assertAlmostEqual(expired['superficie_pastoreable_ha']/expired['superficie_total_ha'],.5,places=3)
        self.assertTrue(expired['preferencia']['puntos'])

    def test_water_has_no_forage_but_remains_a_proximity_resource(self):
        water=box(x1=-58.995)
        a=self.run_analysis([self.zone(),self.zone(id='w',kind='aguada',geom=water)])
        share=a['superficie_pastoreable_ha']/a['superficie_total_ha']
        self.assertAlmostEqual(share,.5,places=3)
        self.assertAlmostEqual(a['configuracion']['zonas'][0]['superficie_accesible_ha'],a['superficie_pastoreable_ha'])
        self.assertEqual(a['factor_mensual'],[1]*12)
        self.assertEqual(a['referencia_ponderada_mensual'],a['referencia_base_mensual'])
        for base, accessible in zip(a['referencia_base_mensual'],a['referencia_accesible_mensual']):
            self.assertAlmostEqual(accessible,base*share)
        self.assertTrue(a['preferencia']['puntos'])
        self.assertTrue(all(p['agua_m'] is not None and not shape(water).covers(shape(p['geom']))
                            for p in a['preferencia']['puntos']))

    def test_overlapping_water_and_restrictions_are_excluded_once(self):
        water=box(x1=-58.995)
        zones=[self.zone(id='w1',kind='aguada',geom=water),
               self.zone(id='w2',kind='aguada',geom=water),
               self.zone(id='r',kind='inaccesible',geom=box(x0=-58.9975,x1=-58.9925),desde='2026-09-27')]
        a=self.run_analysis(zones)
        self.assertAlmostEqual(a['superficie_pastoreable_ha']/a['superficie_total_ha'],.25,places=3)
        self.assertAlmostEqual(a['superficie_agua_ha']/a['superficie_total_ha'],.5,places=3)

    def test_entire_field_water_has_zero_accessible_forage(self):
        a=self.run_analysis([self.zone(kind='aguada')])
        self.assertEqual(a['superficie_pastoreable_ha'],0)
        self.assertEqual(a['referencia_accesible_mensual'],[0]*12)
        self.assertEqual(a['preferencia']['puntos'],[])
        self.assertFalse(any('Sin aguadas registradas' in w for w in a['advertencias']))

    def test_preference_is_inside_and_excludes_inaccessible(self):
        zones=[self.zone(id='w',kind='aguada',geom=box(x1=-58.999,y1=-34.999)),
               self.zone(id='b',kind='inaccesible',geom=box(x0=-58.995),desde='2026-09-27')]
        a=self.run_analysis(zones)
        self.assertTrue(a['preferencia']['puntos'])
        self.assertTrue(all(p['geom']['coordinates'][0]<-58.995 for p in a['preferencia']['puntos']))

if __name__=='__main__': unittest.main()
