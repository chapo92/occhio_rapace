"""
Occhi di Falco - Configuration Module
Centralized configuration loader for all system parameters.
"""

from __future__ import annotations
import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

# --- Screen Capture ---
CAPTURE_FPS = 2           # Frames per second for screen capture
CAPTURE_REGION = None     # None = full screen; or (left, top, width, height)

# --- OCR ---
OCR_LANGUAGES = ["en"]    # Languages for EasyOCR
OCR_GPU = False           # Set True if CUDA GPU is available
TESSERACT_CONFIG = "--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789.$€,."

# --- Computer Vision ---
CV_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
CV_MATCH_THRESHOLD = 0.75  # Template matching confidence threshold

# --- Poker Parsing ---
POKER_PLATFORMS = ["pokerstars", "888poker"]
POSITIONS_ORDER = ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "MP+1", "CO"]
HAND_STAGES = ["preflop", "flop", "turn", "river", "showdown"]

# --- Data Export ---
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
OUTPUT_FILE_PREFIX = "hand_data"
EXPORT_PRETTY_JSON = True

# --- Database (v2.1) ---
DB_PATH = os.path.join(os.path.dirname(__file__), "poker.db")

# --- Pipeline ---
PIPELINE_QUEUE_SIZE = 50       # Max items in the inter-thread queue
DASHBOARD_INTERVAL = 2.0       # Seconds between dashboard refreshes

# --- Logging ---
LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_FILE = os.path.join(os.path.dirname(__file__), "occhi_di_falco.log")

# --- Runtime config override from config.json ---
_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

_DEFAULTS: Dict[str, Any] = {
    "platform": "888poker",
    "debug": False,
    "capture": {
        "fps": 5,
        "resolution": "auto",
        "region": None,
        "backend": "mss",
        "timeout_seconds": 10,
    },
    "table_detection": {
        "method": "hsv_adaptive",
        "blue_hsv_range": {
            "h_min": 100, "h_max": 140,
            "s_min": 30, "s_max": 255,
            "v_min": 30, "v_max": 255,
        },
        "shape_tolerance": 0.05,
        "min_confidence": 0.75,
        "auto_calibrate": True,
    },
    "ocr": {
        "engine": "hybrid",
        "tesseract_lang": "eng",
        "tesseract_path": None,
        "preprocessing": True,
        "whitelist_digits": True,
        "fallback_engine": "easyocr",
    },
    "output": {
        "format": "json",
        "directory": "./output/",
        "session_directory": "./output/sessions/",
        "interval_ms": 1000,
        "database_path": "./output/poker_data.db",
    },
    "validation": {
        "enable": True,
        "max_stack": 10000,
        "max_pot": 50000,
        "min_blind": 0.01,
        "sanity_check_threshold": 0.7,
    },
    "alerts": {
        "enable": True,
        "sound": True,
        "stage_change": True,
        "ocr_confidence_threshold": 0.7,
        "confidence_alert_threshold": 0.8,
    },
    "performance": {
        "max_cpu_percent": 30,
        "max_memory_mb": 500,
        "thread_pool_size": 4,
        "queue_size": 100,
    },
    "database": {
        "enable": True,
        "auto_backup": True,
        "retention_days": 30,
    },
}

def load_config() -> dict:
    """
    Load runtime configuration from config.json (if present) and
    merge it with the module-level defaults above.

    Returns:
        dict: merged configuration dictionary.
    """
    cfg = {
        "capture_fps": CAPTURE_FPS,
        "capture_region": CAPTURE_REGION,
        "ocr_languages": OCR_LANGUAGES,
        "ocr_gpu": OCR_GPU,
        "tesseract_config": TESSERACT_CONFIG,
        "cv_template_dir": CV_TEMPLATE_DIR,
        "cv_match_threshold": CV_MATCH_THRESHOLD,
        "poker_platforms": POKER_PLATFORMS,
        "positions_order": POSITIONS_ORDER,
        "hand_stages": HAND_STAGES,
        "output_dir": OUTPUT_DIR,
        "output_file_prefix": OUTPUT_FILE_PREFIX,
        "export_pretty_json": EXPORT_PRETTY_JSON,
        "db_path": DB_PATH,
        "pipeline_queue_size": PIPELINE_QUEUE_SIZE,
        "dashboard_interval": DASHBOARD_INTERVAL,
        "log_level": LOG_LEVEL,
        "log_format": LOG_FORMAT,
        "log_file": LOG_FILE,
    }

def load_config() -> Dict[str, Any]:
    """Load config.json and merge with defaults. Returns merged dict."""
    from utils.constants import deep_merge
    import copy
    cfg = copy.deepcopy(_DEFAULTS)
    if os.path.isfile(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as fh:
                overrides = json.load(fh)
            deep_merge(cfg, overrides)
            logger.debug("Loaded config from %s", _CONFIG_FILE)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load %s: %s", _CONFIG_FILE, exc)
    output_dir = cfg.get("output", {}).get("directory", "./output/")
    os.makedirs(output_dir, exist_ok=True)
    return cfg
