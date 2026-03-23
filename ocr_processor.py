"""
Occhi di Falco - OCR Processor Module
Extracts text from image regions using EasyOCR and/or Tesseract.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class OCRProcessor:
    """
    Dual OCR engine: EasyOCR for general text, Tesseract for digits.

    Parameters
    ----------
    languages : list[str]
        Language codes for EasyOCR (e.g. ``["en"]``).
    use_gpu : bool
        Enable GPU acceleration for EasyOCR.
    tesseract_config : str
        Tesseract CLI config string.
    """

    def __init__(
        self,
        languages: List[str] = None,
        use_gpu: bool = False,
        tesseract_config: str = "--oem 3 --psm 6",
    ):
        self.languages = languages or ["en"]
        self.use_gpu = use_gpu
        self.tesseract_config = tesseract_config
        self._easyocr_reader = None
        self._tesseract_available = False
        self._init_engines()

    # ------------------------------------------------------------------
    # Engine initialisation
    # ------------------------------------------------------------------

    def _init_engines(self) -> None:
        """Lazy-initialise OCR engines and log availability."""
        # EasyOCR
        try:
            import easyocr  # noqa: F401

            self._easyocr_reader = easyocr.Reader(self.languages, gpu=self.use_gpu)
            logger.info("EasyOCR initialised (languages=%s, gpu=%s)", self.languages, self.use_gpu)
        except ImportError:
            logger.warning("EasyOCR not installed. Run: pip install easyocr")
        except Exception as exc:
            logger.warning("EasyOCR init failed: %s", exc)

        # Tesseract (pytesseract wrapper)
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            self._tesseract_available = True
            logger.info("Tesseract OCR available")
        except Exception:
            logger.warning(
                "Tesseract OCR not available. "
                "Install Tesseract and pytesseract: pip install pytesseract"
            )

    # ------------------------------------------------------------------
    # Pre-processing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
        """
        Apply image pre-processing to improve OCR accuracy on poker UIs.

        Steps:
        1. Convert to grayscale.
        2. Upscale ×2 (helps with small poker fonts).
        3. Adaptive threshold to produce a clean binary image.

        Parameters
        ----------
        image : np.ndarray
            BGR input image.

        Returns
        -------
        np.ndarray
            Pre-processed binary image.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Upscale for better OCR on small text
        upscaled = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        # Adaptive threshold (handles uneven lighting on poker tables)
        binary = cv2.adaptiveThreshold(
            upscaled, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11, 2,
        )
        return binary

    # ------------------------------------------------------------------
    # Core OCR methods
    # ------------------------------------------------------------------

    def read_text_easyocr(self, image: np.ndarray) -> str:
        """
        Extract all text from *image* using EasyOCR.

        Parameters
        ----------
        image : np.ndarray
            BGR or grayscale image.

        Returns
        -------
        str
            Concatenated detected text, empty string on failure.
        """
        if self._easyocr_reader is None:
            return ""
        try:
            results = self._easyocr_reader.readtext(image, detail=0, paragraph=True)
            return " ".join(results)
        except Exception as exc:
            logger.error("EasyOCR error: %s", exc)
            return ""

    def read_text_tesseract(self, image: np.ndarray) -> str:
        """
        Extract text from *image* using Tesseract.

        Parameters
        ----------
        image : np.ndarray
            BGR or grayscale image.

        Returns
        -------
        str
            Detected text, empty string on failure.
        """
        if not self._tesseract_available:
            return ""
        try:
            import pytesseract

            processed = self.preprocess_for_ocr(image)
            text = pytesseract.image_to_string(processed, config=self.tesseract_config)
            return text.strip()
        except Exception as exc:
            logger.error("Tesseract error: %s", exc)
            return ""

    def read_text(self, image: np.ndarray) -> str:
        """
        Extract text using the best available engine.

        Tries EasyOCR first, then falls back to Tesseract.

        Parameters
        ----------
        image : np.ndarray
            BGR image region.

        Returns
        -------
        str
            Best text reading available.
        """
        text = self.read_text_easyocr(image)
        if not text and self._tesseract_available:
            text = self.read_text_tesseract(image)
        return text

    def read_number(self, image: np.ndarray) -> Optional[float]:
        """
        Extract a single numeric value from *image*.

        Uses Tesseract with a digit-only whitelist for maximum accuracy.
        Falls back to EasyOCR if Tesseract is unavailable.

        Parameters
        ----------
        image : np.ndarray
            BGR image cropped around the numeric area.

        Returns
        -------
        float or None
            Parsed float, or None if no valid number found.
        """
        # Try Tesseract with digit whitelist
        if self._tesseract_available:
            import pytesseract

            processed = self.preprocess_for_ocr(image)
            cfg = "--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789.$€,."
            raw = pytesseract.image_to_string(processed, config=cfg).strip()
        else:
            raw = self.read_text_easyocr(image)

        return self._parse_number(raw)

    # ------------------------------------------------------------------
    # Static parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_number(text: str) -> Optional[float]:
        """Parse the first numeric value from a raw OCR string."""
        if not text:
            return None
        # Remove currency symbols and normalise decimal separator
        cleaned = re.sub(r"[€$£,\s]", "", text).replace(",", ".")
        match = re.search(r"\d+(?:\.\d+)?", cleaned)
        if match:
            try:
                return float(match.group())
            except ValueError:
                pass
        return None

    def read_all_numbers(self, image: np.ndarray) -> List[float]:
        """
        Extract all numeric values found in *image*.

        Parameters
        ----------
        image : np.ndarray
            BGR image.

        Returns
        -------
        list[float]
            All detected numeric values in reading order.
        """
        text = self.read_text(image)
        numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
        result = []
        for n in numbers:
            try:
                result.append(float(n.replace(",", ".")))
            except ValueError:
                pass
        return result

    def read_region(
        self,
        image: np.ndarray,
        region: Tuple[int, int, int, int],
        numeric: bool = False,
    ) -> str | float | None:
        """
        Crop *image* to *region* and run OCR on the crop.

        Parameters
        ----------
        image : np.ndarray
            Full BGR image.
        region : tuple
            (x, y, width, height) of the crop.
        numeric : bool
            If True, return a float instead of a string.

        Returns
        -------
        str or float or None
        """
        x, y, w, h = region
        crop = image[y : y + h, x : x + w]
        if numeric:
            return self.read_number(crop)
        return self.read_text(crop)
