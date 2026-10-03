import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from app import app
from stock import progress
from stock.calculator import calculate_stock, StockInputError

class ProgressTest(unittest.TestCase):
    def test_records_are_monotonic_and_readable_from_another_reporter(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(progress, 'DIRECTORY', Path(folder)):
            identifier = str(uuid4())
            report = progress.reporter(identifier)
            report(30); report(10)
            self.assertEqual(progress.read_progress(identifier), {'porcentaje': 30})
            self.assertIsNone(progress.read_progress('../secret'))

    def test_optional_progress_preserves_result_and_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(progress, 'DIRECTORY', Path(folder)):
            identifier = str(uuid4())
            def run(data, on_progress):
                on_progress(40)
                return {'stock': 123}
            with patch('stock.calculator.execute_calculation', side_effect=run):
                self.assertEqual(calculate_stock({'progress_id':identifier}), {'stock':123})
                self.assertEqual(progress.read_progress(identifier)['porcentaje'], 100)
            failed = str(uuid4())
            with patch('stock.calculator.execute_calculation', side_effect=StockInputError('invalid')):
                with self.assertRaises(StockInputError): calculate_stock({'progress_id':failed})
                self.assertLess(progress.read_progress(failed)['porcentaje'],100)
