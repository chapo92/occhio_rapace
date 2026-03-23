"""Unit tests for OCRProcessor (core version)."""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np

from core.ocr_processor import OCRProcessor


class TestOCRProcessor(unittest.TestCase):

    def setUp(self):
        with patch('core.ocr_processor.TESSERACT_AVAILABLE', False), \
             patch('core.ocr_processor.EASYOCR_AVAILABLE', False):
            self.ocr = OCRProcessor(use_tesseract=False, use_easyocr=False)

    def test_preprocess_for_ocr(self):
        image = np.zeros((50, 100, 3), dtype=np.uint8)
        image[10:40, 20:80] = [200, 200, 200]
        result = self.ocr.preprocess_for_ocr(image)
        self.assertIsNotNone(result)
        self.assertEqual(len(result.shape), 2)
        self.assertEqual(result.shape[0], 100)  # 2x scale
        self.assertEqual(result.shape[1], 200)

    def test_parse_number_basic(self):
        self.assertAlmostEqual(OCRProcessor._parse_number("12.50"), 12.50)

    def test_parse_number_dollar(self):
        self.assertAlmostEqual(OCRProcessor._parse_number("$45"), 45.0)

    def test_parse_number_euro(self):
        self.assertAlmostEqual(OCRProcessor._parse_number("€ 100"), 100.0)

    def test_parse_number_comma(self):
        self.assertAlmostEqual(OCRProcessor._parse_number("1,234.56"), 1234.56)

    def test_parse_number_none(self):
        self.assertIsNone(OCRProcessor._parse_number(""))
        self.assertIsNone(OCRProcessor._parse_number(None))

    def test_read_all_numbers(self):
        with patch.object(self.ocr, 'read_text', return_value="Pot: 45.50 Blinds: 0.50/1.00"):
            numbers = self.ocr.read_all_numbers(np.zeros((10, 10, 3), dtype=np.uint8))
        self.assertIn(45.50, numbers)
        self.assertIn(0.50, numbers)
        self.assertIn(1.00, numbers)

    def test_read_text_no_engines(self):
        image = np.zeros((50, 100, 3), dtype=np.uint8)
        result = self.ocr.read_text(image)
        self.assertEqual(result, "")

    def test_read_text_with_confidence_no_engines(self):
        image = np.zeros((50, 100, 3), dtype=np.uint8)
        text, conf = self.ocr.read_text_with_confidence(image)
        self.assertEqual(text, "")
        self.assertEqual(conf, 0.0)


if __name__ == "__main__":
    unittest.main()
