# 888 Poker Data Extractor – Complete Guide

## Overview

**Occhi di Falco** is a production-grade, real-time data extraction system for the 888 Poker
desktop client. It captures your screen, detects the poker table using computer vision, reads
card and chip values via OCR, and persists every hand to a local SQLite database for later
analysis.

### What it does

1. Continuously captures your screen (or a configurable region) at a target frame rate.
2. Detects the 888 Poker table by its characteristic blue colour using HSV colour filtering.
3. Extracts numeric data (blinds, pot, stack sizes, player counts) with Tesseract OCR.
4. Parses raw OCR output into structured hand records and tracks per-session statistics (VPIP,
   total hands, pot sizes, etc.).
5. Stores everything in a normalised SQLite database using SQLAlchemy ORM.
6. Displays a live Rich terminal dashboard and non-blocking alerts.

### Key features

| Feature | Details |
|---|---|
| Real-time screen capture | `mss` backend, configurable FPS & region |
| 888 Poker table detection | HSV colour model + shape tolerance, confidence score |
| Hybrid OCR | Tesseract primary, EasyOCR fallback |
| Structured poker parsing | Blinds, pot, stacks, positions, VPIP |
| Normalised database | 8-table SQLite schema via SQLAlchemy |
| Pipeline architecture | Producer/consumer queues, thread-safe |
| Error recovery | JSON checkpoints, auto-resume after crash |
| Performance monitoring | Per-stage latency, CPU/memory, bottleneck reports |
| Interactive calibration | Wizard to learn your table's exact blue colour |
| Rich dashboard | Live stats in the terminal |

### System requirements

| Component | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 / Ubuntu 20.04 | Windows 11 / Ubuntu 22.04 |
| Python | 3.9 | 3.11 |
| RAM | 2 GB | 4 GB |
| CPU | Dual-core 2 GHz | Quad-core 3 GHz |
| Disk | 500 MB | 2 GB |
| Tesseract OCR | 4.x | 5.x |

---

## Quick Start (5 minutes)

> These steps assume Python 3.9+ and Tesseract OCR are already installed.

```bash
# 1. Clone the repository
git clone https://github.com/chapo92/live.git
cd live

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. (Optional) Run the calibration wizard to tune HSV thresholds
python main.py --calibrate

# 4. Start capturing
python main.py
```

Press `Ctrl+C` to stop. Data is saved to `output/poker_data.db`.

---

## Full Setup (30 minutes)

Follow the platform-specific guides for a complete, production-grade installation:

- **Windows** → [`SETUP_GUIDE_WINDOWS.md`](SETUP_GUIDE_WINDOWS.md)
- **Linux** → [`SETUP_GUIDE_LINUX.md`](SETUP_GUIDE_LINUX.md)

---

## Further Reading

| Document | Purpose |
|---|---|
| [`CONFIG_REFERENCE.md`](CONFIG_REFERENCE.md) | Every `config.json` parameter explained |
| [`PERFORMANCE_TUNING.md`](PERFORMANCE_TUNING.md) | How to squeeze more FPS and accuracy |
| [`API_REFERENCE.md`](API_REFERENCE.md) | Public API for all major classes |
| [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | Fix common errors |
| [`FAQ.md`](FAQ.md) | Frequently asked questions |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System design and data-flow diagram |
