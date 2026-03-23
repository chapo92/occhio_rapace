from __future__ import annotations
import logging
import re
from typing import Optional, Tuple, List
import cv2
import numpy as np

logger = logging.getLogger(__name__)

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False


class OCRProcessor:
    def __init__(self, use_tesseract: bool = True, use_easyocr: bool = True):
        self._tess = use_tesseract and TESSERACT_AVAILABLE
        self._easy = use_easyocr and EASYOCR_AVAILABLE
        self._easyocr_reader = None
        if self._easy:
            try:
                self._easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            except Exception as e:
                logger.warning("EasyOCR init failed: %s", e)
                self._easy = False

    def preprocess_888poker(self, image: np.ndarray) -> np.ndarray:
        """Preprocess 888 Poker white/yellow text on dark background."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        scale = 2
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(thresh) > 127:
            thresh = cv2.bitwise_not(thresh)
        denoised = cv2.medianBlur(thresh, 3)
        return denoised

    def preprocess_for_ocr(self, image: np.ndarray) -> np.ndarray:
        return self.preprocess_888poker(image)

    def read_text_with_confidence(self, image: np.ndarray) -> Tuple[str, float]:
        preprocessed = self.preprocess_for_ocr(image)
        if self._tess:
            try:
                data = pytesseract.image_to_data(preprocessed, output_type=pytesseract.Output.DICT,
                                                  config='--psm 6')
                texts = [t for t, c in zip(data['text'], data['conf']) if int(c) > 0 and t.strip()]
                confs = [int(c) for c in data['conf'] if int(c) > 0]
                if texts:
                    text = " ".join(texts)
                    conf = sum(confs) / len(confs) / 100.0
                    return text.strip(), conf
            except Exception as e:
                logger.debug("Tesseract failed: %s", e)
        if self._easy and self._easyocr_reader:
            try:
                results = self._easyocr_reader.readtext(preprocessed)
                if results:
                    text = " ".join([r[1] for r in results])
                    conf = sum([r[2] for r in results]) / len(results)
                    return text.strip(), conf
            except Exception as e:
                logger.debug("EasyOCR failed: %s", e)
        return "", 0.0

    def read_text(self, image: np.ndarray) -> str:
        text, _ = self.read_text_with_confidence(image)
        return text

    def read_number(self, image: np.ndarray) -> Optional[float]:
        text = self.read_text(image)
        return self._parse_number(text)

    def read_all_numbers(self, image: np.ndarray) -> List[float]:
        text = self.read_text(image)
        results = []
        for m in re.findall(r'[\d,]+\.?\d*', text):
            cleaned = m.replace(',', '')
            try:
                results.append(float(cleaned))
            except ValueError:
                pass
        return results

    def read_region(self, frame: np.ndarray, roi: Tuple[int,int,int,int]) -> str:
        x, y, w, h = roi
        region = frame[y:y+h, x:x+w]
        return self.read_text(region)

    @staticmethod
    def _parse_number(text: str) -> Optional[float]:
        if not text:
            return None
        cleaned = re.sub(r'[^\d.,]', '', text)
        cleaned = cleaned.replace(',', '')
        try:
            return float(cleaned)
        except ValueError:
            return None
