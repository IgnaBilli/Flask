import unittest
from datetime import date
import app  # Inicializa las rutas del artefacto igual que el servicio Flask.
from stock.seasonal_window import seasonal_window


class SeasonalWindowTest(unittest.TestCase):
    def test_boundaries_and_profiles(self):
        cases = [('03-20',48,45),('03-21',60,60),('06-20',60,60),
                 ('06-21',90,90),('09-20',90,90),('09-21',38,35),
                 ('12-20',38,35),('12-21',48,45)]
        for day,natural,implanted in cases:
            with self.subTest(day=day):
                target = date.fromisoformat('2026-'+day)
                self.assertEqual(seasonal_window(target,'Pastizal natural')['dias'],natural)
                self.assertEqual(seasonal_window(target,'Pasturas')['dias'],implanted)

    def test_unknown_coverage_is_explicit(self):
        result = seasonal_window(date(2026,9,21),None)
        self.assertEqual(result['dias'],38)
        self.assertFalse(result['cobertura_reconocida'])
