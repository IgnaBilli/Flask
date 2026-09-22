import unittest
from unittest.mock import patch
import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box
from intrapaddock import (calculate_intrapaddock, pixel_weights, ndvi_from_bands,
                         summarize_sector, make_grid, IntrapaddockSourceError)
from validation import PredictionInputError

POLYGON = {'type': 'Polygon', 'coordinates': [[[-56.29, -28.43], [-56.284, -28.43],
           [-56.284, -28.425], [-56.29, -28.425], [-56.29, -28.43]]]}


class IntrapaddockTests(unittest.TestCase):
    def test_fractional_edges_and_holes_preserve_area(self):
        polygon = Polygon([(2, 2), (98, 2), (98, 98), (2, 98)],
                          holes=[[(43, 43), (57, 43), (57, 57), (43, 57)]])
        weights = pixel_weights(polygon, (10, 10), from_origin(0, 100, 10, 10))
        self.assertAlmostEqual(float(weights.sum()), polygon.area, places=6)
        self.assertAlmostEqual(weights[0, 0], 64)
        self.assertTrue(np.all(weights >= 0))
        self.assertTrue(np.all(weights <= 100))

    def test_excludes_water_shadows_clouds_nodata_and_invalid_reflectance(self):
        red = np.full((1, 12), 0.2)
        nir = np.full((1, 12), 0.6)
        result = ndvi_from_bands(red, nir, np.arange(12).reshape(1, 12))
        self.assertEqual(np.flatnonzero(np.isfinite(result)).tolist(), [4, 5])
        np.testing.assert_allclose(result[0, 4:6], [0.5, 0.5])
        self.assertTrue(np.isnan(ndvi_from_bands(np.array([[-0.1]]), np.array([[0.5]]), np.array([[4]]))[0, 0]))

    def test_coverage_denominator_does_not_drop_missing_pixels(self):
        weights = np.full((4, 4), 100.0)
        values = np.full((4, 4), 0.6)
        values[:2] = np.nan
        mean, area, count = summarize_sector(values, weights)
        self.assertAlmostEqual(mean, 0.6)
        self.assertEqual(area, 0.08)
        self.assertEqual(count, 8)
        values[:] = np.nan
        self.assertEqual(summarize_sector(values, weights), (None, 0.0, 0))

    @patch('intrapaddock.fetch_scenes')
    def test_rejects_invalid_or_future_requests_before_contacting_sources(self, scenes):
        for payload in [None, {}, {'geojson': POLYGON, 'fecha': '2099-01-01'}]:
            with self.assertRaises(PredictionInputError):
                calculate_intrapaddock(payload)
        scenes.assert_not_called()

    @patch('intrapaddock.read_scene')
    @patch('intrapaddock.fetch_scenes')
    def test_real_contract_dates_fixed_geometry_and_common_pixel_comparisons(self, scenes, read):
        scenes.return_value = [
            {'id': 'recent', 'properties': {'datetime': '2026-09-20T14:00:00Z'}},
            {'id': 'previous', 'properties': {'datetime': '2026-09-15T14:00:00Z'}},
        ]
        grid_shape = make_grid(POLYGON)[3]
        first = np.full(grid_shape, 0.6)
        second = np.full(grid_shape, 0.4)
        first[:grid_shape[0] // 3, :] = np.nan
        read.side_effect = [first, second]
        result = calculate_intrapaddock({'geojson': POLYGON, 'fecha': '2026-09-21'})
        self.assertFalse(result['illustrative'])
        self.assertEqual(result['dates'], ['2026-09-15', '2026-09-20'])
        self.assertEqual(len(result['sectors']), 4)
        self.assertLessEqual(len(result['scenes']['2026-09-20']['cells']['features']), 3000)
        for sector in result['sectors']:
            self.assertAlmostEqual(sector['comparisons']['2026-09-20']['delta'], 0.2)
            self.assertLessEqual(sector['validAreaHa']['2026-09-20'], sector['areaHa'] + 1e-8)
        self.assertAlmostEqual(sum(s['areaHa'] for s in result['sectors']), make_grid(POLYGON)[0].area / 10000)

    @patch('intrapaddock.fetch_scenes', return_value=[])
    def test_no_scenes_is_a_source_error_never_synthetic_data(self, _scenes):
        with self.assertRaises(IntrapaddockSourceError):
            calculate_intrapaddock({'geojson': POLYGON})


if __name__ == '__main__':
    unittest.main()
