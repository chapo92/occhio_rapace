# Occhi di Falco 🦅
> Real-time 888 Poker data extraction — Production-Ready

Occhi di Falco ("Falcon Eyes") captures your desktop in real-time, detects the 888 Poker
blue table (with tolerance for dark/light variations), reads all hand data with advanced
OCR, and exports structured JSON + SQLite records.

---

## Features

| Feature | Details |
|---|---|
| **888 Poker blue table detection** | HSV-adaptive with ±30% colour tolerance, 3 shapes (round/octagonal/elongated) |
| Screen capture | mss (primary) / pyautogui (fallback), thread-safe queue |
| OCR engines | EasyOCR + Tesseract (dual-engine, confidence scoring) |
| Computer vision | OpenCV – blue table, card, chip detection |
| Data extracted | Pot, stacks, blinds, ante, positions, hand stage, player actions, fish detection |
| CLI Dashboard | `rich`-powered live dashboard with fallback |
| Alert system | Stage-change, OCR-uncertain, table-lost alerts (non-blocking) |
| SQLite database | Sessions, hands, players, actions + VPIP stats |
| Error recovery | Checkpoint save/restore, graceful degradation |
| Performance monitor | FPS, CPU, memory, thread count |
| Calibration wizard | First-run colour learning saved to config.json |
| ROI manager | Dynamic region-of-interest for fast OCR |
| Validators | Sanity checks on all extracted values |
| Output | JSON per session, SQLite database |
| **Auto-backup** | Daily database backup with rotation, USB drive support |
| OS | Windows, Linux, macOS |
| Python | 3.9+ |

---

## Project Structure

```
live/
├── main.py                   # Entry point + CLI
├── config.py                 # Configuration loader
├── calibration.py            # Calibration wizard
├── config.json               # Advanced configuration file
├── requirements.txt          # Runtime dependencies
├── requirements-dev.txt      # Dev/test dependencies
├── setup.py                  # Package setup
│
├── core/                     # Core processing modules
│   ├── screen_capture.py     # Thread-safe screen capture
│   ├── computer_vision.py    # 888 Poker blue table detection
│   ├── ocr_processor.py      # OCR with confidence scoring
│   ├── poker_parser.py       # Hand data parser
│   └── data_exporter.py      # JSON + session export
│
├── features/                 # Advanced features
│   ├── dashboard.py          # Rich CLI live dashboard
│   ├── alerts.py             # Alert system (stage, OCR, table)
│   ├── performance_monitor.py # FPS / CPU / memory monitor
│   ├── database_manager.py   # SQLite sessions + statistics
│   └── error_recovery.py     # Crash recovery + checkpoints
│
├── utils/                    # Utilities
│   ├── constants.py          # 888 Poker constants + deep_merge
│   ├── logger_setup.py       # Rotating file + console logging
│   ├── validators.py         # Data sanity checks
│   └── roi_manager.py        # Dynamic region-of-interest
│
├── tests/                    # Test suite
│   ├── test_ocr.py           # OCR unit tests
│   ├── test_vision.py        # Vision unit tests
│   ├── test_parser.py        # Parser unit tests
│   └── test_integration.py   # Integration tests
│
└── output/                   # Output directory (auto-created)
    └── sessions/             # Per-session JSON files
```

---

## Installation

### 1. Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Tesseract OCR (system package)

| OS | Command |
|---|---|
| Ubuntu/Debian | `sudo apt install tesseract-ocr` |
| macOS | `brew install tesseract` |
| Windows | Download installer from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) |

### 3. Verify installation

```bash
tesseract --version
python -c "import cv2, easyocr, mss; print('All OK')"
```

### 4. Run tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

---

## Usage

### First run — calibration (recommended)

```bash
python main.py --calibrate
```

This captures your screen, detects the 888 Poker blue table colour range, and saves it to `config.json`.

### Quick start (full screen, 5 FPS)

```bash
python main.py
```

### Custom options

```bash
python main.py \
  --fps 5 \
  --output output/ \
  --region 100,50,1200,800 \
  --debug
```

| Argument | Default | Description |
|---|---|---|
| `--fps` | 5 | Capture rate (frames/second) |
| `--output` | `output/` | Directory for JSON output |
| `--region` | full screen | `left,top,width,height` in pixels |
| `--debug` | off | Enable verbose logging |
| `--calibrate` | off | Run calibration wizard before starting |
| `--no-dashboard` | off | Disable rich live dashboard |
| `--no-backup` | off | Disable automatic daily backup scheduler |
| `--max-frames` | 0 (∞) | Stop after N frames |

---

## Output JSON format

```json
{
  "timestamp": "2026-03-22T10:30:45.123456+00:00",
  "session_id": "sess_20260322_103045",
  "table_detected": true,
  "table_confidence": 0.98,
  "stage": "flop",
  "small_blind": 0.5,
  "big_blind": 1.0,
  "ante": 0.0,
  "pot": 45.50,
  "player_count": 4,
  "community_cards_count": 3,
  "players": [
    {
      "seat": 1,
      "position": "BTN",
      "stack": 145.30,
      "is_dealer": true,
      "is_fish": false,
      "vpip_pct": 35.5,
      "last_action": "raise",
      "ocr_confidence": 0.95
    }
  ],
  "actions_history": [
    {
      "stage": "preflop",
      "action": "raise",
      "amount": 3.0,
      "timestamp": "2026-03-22T10:30:43.000000+00:00"
    }
  ],
  "system_status": {
    "fps": 5.2,
    "cpu_percent": 12.5,
    "memory_mb": 245.3,
    "queue_size": 3
  }
}
```

---

## Configuration

The full configuration is in `config.json`. Key settings:

```json
{
  "platform": "888poker",
  "capture": { "fps": 5, "region": null },
  "table_detection": {
    "blue_hsv_range": { "h_min": 100, "h_max": 140, "s_min": 30, "s_max": 255, "v_min": 30, "v_max": 255 },
    "shape_tolerance": 0.05,
    "min_confidence": 0.75
  },
  "ocr": { "engine": "hybrid", "preprocessing": true, "whitelist_digits": true },
  "output": { "directory": "./output/", "database_path": "./output/poker_data.db" },
  "alerts": { "enable": true, "sound": true, "stage_change": true },
  "database": { "enable": true, "retention_days": 30 }
}
```

---

## Auto-Backup System

The backup scheduler starts automatically in the background every time you run `main.py`.
It creates a daily snapshot of the SQLite database at midnight and keeps the last 4 backups.

| Config key (`config.json`) | Default | Description |
|---|---|---|
| `database.auto_backup` | `true` | Enable/disable auto-backup |

Backup settings (paths, retention, email alerts) are in `scripts/backup/backup_config.json`.

### Disable backup for a single run
```bash
python main.py --no-backup
```

### Manual operations
```bash
# List backups
python scripts/backup/restore_manager.py list

# Restore latest backup
python scripts/backup/restore_manager.py restore latest

# Rotate to USB drive
python -c "from scripts.backup.backup_manager import BackupManager; BackupManager().rotate_to_external_drive('/mnt/usb/')"
```

See [scripts/backup/README_BACKUP.md](scripts/backup/README_BACKUP.md) for the full guide.

---

## 888 Poker Table Detection

The system uses **HSV-adaptive colour detection** tuned for 888 Poker's blue table:

- **Colour range**: H 100–140, S 30–255, V 30–255 (tolerates dark and light variants)
- **Shapes detected**: Round, Octagonal, Elongated Round (±5% tolerance)
- **Confidence scoring**: 0.0–1.0 per detection

Run `--calibrate` to auto-learn your specific screen's blue range.

---

## Fish Detection

A player is tagged as a **fish** (`is_fish: true`) when their observed VPIP
(voluntarily put money in pot) rate exceeds **40%** over at least **10 tracked hands**.
Until enough data is collected, `is_fish` is `null`.

---

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for detailed solutions to common problems.

| Problem | Quick fix |
|---|---|
| Table not detected | Run `python main.py --calibrate` |
| `No screen capture backend` | `pip install mss` |
| `Tesseract not available` | Install Tesseract system package |
| Low OCR accuracy | Use `--region` to crop the table area |

---

## License

MIT – see `LICENSE` for details.
