# System Architecture

## Design Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                          Main Thread                            │
│  CLI args → load_config() → Pipeline.start() → dashboard loop  │
└────────────────────────────┬────────────────────────────────────┘
                             │
          ┌──────────────────▼──────────────────────┐
          │           Capture Thread                 │
          │  ScreenCapture (mss backend)             │
          │  → grabs frame every 1/fps seconds       │
          └──────────────────┬──────────────────────┘
                             │  raw BGR frame (numpy array)
          ┌──────────────────▼──────────────────────┐
          │          Worker Thread Pool              │
          │  ComputerVision.detect_poker_table()     │
          │    └─ HSV colour filter                  │
          │    └─ contour / shape analysis           │
          │    └─ confidence score                   │
          │  OCRProcessor.extract_numbers()          │
          │    └─ image preprocessing                │
          │    └─ Tesseract (primary)                │
          │    └─ EasyOCR (fallback)                 │
          │  PokerParser.parse_hand()                │
          │    └─ regex + heuristic logic            │
          │    └─ validation checks                  │
          └──────────────────┬──────────────────────┘
                             │  PokerHandData dict
          ┌──────────────────▼──────────────────────┐
          │        Inter-thread Queue                │
          │  thread-safe, maxsize = queue_size       │
          └──────────────────┬──────────────────────┘
                             │
          ┌──────────────────▼──────────────────────┐
          │         Database Thread                  │
          │  DatabaseManager.insert_hand()           │
          │    └─ SQLAlchemy ORM                     │
          │    └─ atomic transaction + rollback      │
          │    └─ batch flush when queue is busy     │
          └──────────────────┬──────────────────────┘
                             │
          ┌──────────────────▼──────────────────────┐
          │             SQLite DB                    │
          │  8-table normalised schema               │
          │  (tournaments, hands, actions, stats…)   │
          └──────────────────┬──────────────────────┘
                             │
          ┌──────────────────▼──────────────────────┐
          │           Statistics Cache               │
          │  session totals, VPIP, FPS, queue depth  │
          │  → read by dashboard thread every 2 s    │
          └─────────────────────────────────────────┘
```

---

## Components

### Capture module (`screen_capture.py`)

- Uses `mss` for low-latency, cross-platform screen capture.
- Runs in a dedicated **daemon thread** so the main thread stays responsive.
- Writes each frame to an internal slot; the worker pool reads from it concurrently.

### Computer vision module (`computer_vision.py`)

- Converts BGR frames to HSV colour space.
- Applies the configured `blue_hsv_range` mask to isolate the table felt.
- Finds contours, evaluates shape score, and returns a confidence value.
- Falls back gracefully when no table is visible (returns `detected=False`).

### OCR module (`ocr_processor.py`)

- Pre-processes the detected table region (grayscale, adaptive threshold, Gaussian blur).
- Calls Tesseract with a digit-only character whitelist for numeric fields.
- Falls back to EasyOCR when Tesseract confidence is below the threshold.
- Returns extracted text and a mean confidence score.

### Parser module (`poker_parser.py`)

- Uses regular expressions to find pot, blind, and stack patterns in the OCR text.
- Applies sanity checks (max pot, max stack, min blind) to reject obviously wrong values.
- Tracks running session statistics (VPIP, total hands, total pots).

### Pipeline (`pipeline.py`)

- Ties all modules together in a producer/consumer pattern.
- Handles `SIGINT`/`SIGTERM` for graceful shutdown (flushes the queue before exiting).
- Exposes `get_statistics()` for the dashboard thread.

### Database (`database/`)

- `schema.sql`: 8-table normalised schema (tournaments, players, hands, actions, statistics,
  bubble tracking, blind levels, session metadata).
- `models.py`: SQLAlchemy ORM mappings.
- `manager.py`: High-level methods (`insert_hand`, `query_sessions`, `export_to_csv`) plus
  8 pre-built analytical queries.

### Error recovery (`features/error_recovery.py`, `features/checkpoint_system.py`)

- Saves a JSON checkpoint every 100 frames (configurable).
- On startup, detects an incomplete previous session and resumes from the last valid
  checkpoint.
- Keeps up to 5 checkpoint files; older ones are deleted automatically.

### Performance monitor (`features/performance_monitor.py`)

- Tracks FPS with a sliding 10-frame window.
- Monitors CPU and memory usage via `psutil`.
- Records per-stage latency for bottleneck analysis.

---

## Data Flow

1. **Capture**: `ScreenCapture` grabs a frame every `1/fps` seconds.
2. **CV Detection**: `ComputerVision` checks for the blue table. Frames without a table are
   discarded.
3. **OCR**: `OCRProcessor` extracts numeric text from the table region.
4. **Parse**: `PokerParser` converts raw text into a structured hand dict.
5. **Queue**: The hand dict is placed on the inter-thread queue (capacity: `queue_size`).
6. **Database**: The consumer thread dequeues items and writes them to SQLite atomically.
7. **Statistics**: After each insert, aggregate counters are updated in the stats cache.

---

## Thread Safety

| Mechanism | Where used |
|---|---|
| `queue.Queue` (thread-safe FIFO) | Decouples worker pool from database thread |
| SQLAlchemy session-per-thread | Each database call uses its own session |
| `threading.Event` stop flags | Clean shutdown signalling to all threads |
| Atomic SQLite transactions | Rollback on any insert error; no partial writes |
| JSON checkpoint with backup copy | Recovery from crash mid-transaction |

---

## Directory Structure

```
live/
├── main.py                  # Entry point + CLI flags
├── pipeline.py              # Producer/consumer orchestrator
├── config.py                # Config loader + defaults
├── screen_capture.py        # mss-based capture thread
├── computer_vision.py       # HSV table detection
├── ocr_processor.py         # Tesseract/EasyOCR wrapper
├── poker_parser.py          # Regex + logic parser
├── data_exporter.py         # JSON/CSV export
├── database.py              # DatabaseManager facade
├── calibration.py           # Interactive calibration wizard
├── database/
│   ├── schema.sql           # 8-table SQL schema
│   ├── models.py            # SQLAlchemy ORM models
│   └── manager.py           # DB manager + queries
├── features/
│   ├── dashboard.py         # Rich terminal dashboard
│   ├── alerts.py            # Non-blocking alert system
│   ├── database_manager.py  # SQLite session manager
│   ├── error_recovery.py    # Checkpoint load/save
│   └── performance_monitor.py # FPS/CPU/memory tracking
├── utils/
│   ├── roi_manager.py       # Dynamic ROI zones
│   ├── validators.py        # Sanity check helpers
│   ├── constants.py         # 888 Poker constants + deep_merge
│   └── logger_setup.py      # Logging configuration
├── tests/                   # Unit + integration test suite
├── docs/                    # This documentation
└── output/                  # Database, JSON output, logs
```
