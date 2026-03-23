"""Configured logging with rotation and optional colored output."""
import logging
import logging.handlers
import os
import sys
from typing import Optional

try:
    import colorlog
    COLORLOG_AVAILABLE = True
except ImportError:
    COLORLOG_AVAILABLE = False


def setup_logger(name: str = "occhi_di_falco", level: int = logging.INFO,
                 log_file: Optional[str] = None, colored: bool = True) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if logger.handlers:
        return logger
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    if colored and COLORLOG_AVAILABLE:
        color_fmt = "%(log_color)s%(asctime)s [%(levelname)s]%(reset)s %(name)s: %(message)s"
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(colorlog.ColoredFormatter(
            color_fmt, datefmt=datefmt,
            log_colors={'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow',
                        'ERROR': 'red', 'CRITICAL': 'bold_red'}))
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    logger.addHandler(console_handler)
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        logger.addHandler(file_handler)
    return logger
