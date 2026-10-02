import copy
import json
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modelo_final DMP/src"))
from shapely.geometry import box, mapping
from stock.gis_utils import resolve_gis_context
from stock.nearby_reference import fallback_scope, nearest_reference
from stock.calculator import calculate_stock

PARAMS = json.loads((ROOT / "stock/data/parametros_regionales.json").read_text(encoding="utf-8"))


def field(lon, lat):
    return box(lon-.002, lat-.002, lon+.002, lat+.002)


class NearbySelectionTest(unittest.TestCase):
    def test_all_target_provinces_allow_fallback(self):
        for province, lon, lat in [("Buenos Aires", -62.8, -40.5), ("Corrientes", -57.8, -28.7),
                                   ("Chaco", -60.5, -26.5), ("Formosa", -61.8, -24),
                                   ("Misiones", -54.6, -26.4)]:
            with self.subTest(province=province):
                self.assertIn(province, fallback_scope(field(lon, lat)))

    def test_whole_polygon_required_and_no_extension_to_patagonia_or_brazil(self):
        for polygon in [field(-65.5, -43.3), field(-53.5, -26.4), box(-65, -42, -58, -35)]:
            self.assertIsNone(fallback_scope(polygon))

    def test_closest_wins_without_environment_match(self):
        result = nearest_reference(field(-54.6, -26.4), "selva paranaense", "U1", PARAMS, ["Misiones"])
        self.assertEqual(result["zona_id"], "corrientes")
        self.assertEqual(result["respaldo"]["candidatos_ordenados"][0]["prioridad_ambiental"], 3)

    def test_compatible_reference_wins_over_closer_unrelated_region(self):
        result = nearest_reference(field(-62, -38), "pampa", "U99", PARAMS, ["Buenos Aires"])
        self.assertEqual(result["zona_id"], "buenos_aires_centro")
        self.assertTrue(result["respaldo"]["candidatos_ordenados"][0]["misma_ecorregion"])

    def test_specific_unit_keeps_only_compatible_profiles(self):
        result = nearest_reference(field(-55.8, -27.5), "campos y malezales", "U4", PARAMS, ["Misiones"])
        self.assertEqual(result["perfiles_utilizados"], ["santa_fe_panicum_prionitis"])

    def test_trace_is_deterministic_and_not_labelled_validated(self):
        args = (field(-54.6, -26.4), "selva paranaense", "U1", PARAMS, ["Misiones"])
        result = nearest_reference(*args)
        shuffled = copy.deepcopy(PARAMS)
        shuffled["zonas"] = dict(reversed(list(shuffled["zonas"].items())))
        self.assertEqual(result, nearest_reference(args[0], args[1], args[2], shuffled, args[4]))
        self.assertFalse(result["respaldo"]["validacion_local"])
        self.assertFalse(result["respaldo"]["comparacion_climatica_directa"])
        self.assertEqual(result["confianza_ambiental"], "BAJA")

    def test_incomplete_curves_are_never_used(self):
        params = copy.deepcopy(PARAMS)
        for key in params["zonas"]["corrientes"]["ambientes"]:
            params["curvas"][key]["mensual"][0] = None
        result = nearest_reference(field(-54.6, -26.4), "", "", params, ["Misiones"])
        self.assertNotEqual(result["zona_id"], "corrientes")
        for curve in params["curvas"].values():
            curve["mensual"] = []
        with self.assertRaisesRegex(ValueError, "curvas regionales completas"):
            nearest_reference(field(-54.6, -26.4), "", "", params, ["Misiones"])

    def test_existing_direct_matches_are_preserved(self):
        for lon, lat, status, zone in [(-56.37, -28.45, "PARCIAL", "corrientes"),
                                      (-60.55, -33.95, "EXACTA", "buenos_aires_ne"),
                                      (-58.8, -30.95, "EXACTA", "entre_rios_norte"),
                                      (-64.7, -37, "PARCIAL", "caldenal_centro")]:
            with self.subTest(zone=zone):
                result = resolve_gis_context(field(lon, lat), PARAMS)["seleccion_referencia"]
                self.assertEqual((result["estado"], result["zona_id"]), (status, zone))
                self.assertNotIn("respaldo", result)

    def test_unmapped_real_locations_get_a_complete_regional_reference(self):
        for lon, lat in [(-54.6, -26.4), (-61.8, -24), (-62.8, -40.5), (-62.3, -38.7)]:
            with self.subTest(lon=lon, lat=lat):
                result = resolve_gis_context(field(lon, lat), PARAMS)["seleccion_referencia"]
                self.assertEqual(result["estado"], "RESPALDO_PROXIMIDAD")
                self.assertTrue(result["perfiles_utilizados"])

    def test_out_of_scope_unmapped_location_still_fails(self):
        with self.assertRaisesRegex(ValueError, "referencia regional"):
            resolve_gis_context(field(-65.5, -43.3), PARAMS)

    @patch("stock.gis_utils._load_ign_features", return_value=[])
    @patch("stock.gis_utils._load_oyarzabal_features", return_value=[])
    def test_cartographic_gap_inside_target_scope_still_resolves(self, *_):
        result = resolve_gis_context(field(-54.6, -26.4), PARAMS)
        self.assertEqual(result["seleccion_referencia"]["estado"], "RESPALDO_PROXIMIDAD")
        self.assertEqual(result["ecorregiones"], [])


class NearbyCalculationTest(unittest.TestCase):
    @patch("stock.calculator.calculate_dmp_observation")
    @patch("stock.calculator.DmpPredictor")
    @patch("stock.calculator.fetch_mapbiomas")
    def test_real_gis_selection_flows_into_stock_and_trace(self, coverage, predictor, observation):
        coverage.return_value = {"estado": "DISPONIBLE", "clase_predominante": "Pasturas"}
        predictor.return_value = MagicMock(load_warnings=[], metrics={})
        observation.side_effect = lambda *a, **kw: {
            "fecha_objetivo": a[3].isoformat(), "dmp_kg_ms_ha_dia": 10,
            "escena": {"fecha": a[3].isoformat(), "fraccion_pixeles_validos": 1, "ndvi_promedio": .6},
            "clima_fecha": a[3].isoformat(),
        }
        for lon, lat in [(-54.6, -26.4), (-61.8, -24), (-62.8, -40.5)]:
            with self.subTest(lon=lon, lat=lat):
                result = calculate_stock({"fecha": "2026-10-01", "dias_actualizacion": 5,
                    "consumo_diario_total_kg_ms": 0, "geojson": mapping(field(lon, lat))})
                value = result["stock_final_utilizable"]["valor_kg_ms_ha"]["central"]
                self.assertTrue(math.isfinite(value) and value > 0)
                self.assertEqual(result["seleccion_referencia"]["estado"], "RESPALDO_PROXIMIDAD")
                self.assertEqual(result["coherencia"]["aplicabilidad_modelo"], "BAJA")
                self.assertEqual(result["coherencia"]["estado"], "REVISAR")
                self.assertTrue(result["coherencia"]["advertencias"])


if __name__ == "__main__":
    unittest.main()
