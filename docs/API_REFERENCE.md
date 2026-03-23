# API Reference

This document describes the public API of all major classes. Import paths assume you are
running from the project root.

---

## ScreenCapture

```python
from screen_capture import ScreenCapture
```

Manages continuous screen capture in a background thread using the `mss` backend.

### Constructor

```python
ScreenCapture(cfg: dict)
```

| Parameter | Type | Description |
|---|---|---|
| `cfg` | dict | Configuration dictionary returned by `config.load_config()`. |

### Methods

#### `start() -> None`

Start the capture background thread. Frames are written to an internal ring buffer.

#### `stop() -> None`

Signal the capture thread to stop and wait for it to finish.

#### `capture_frame() -> numpy.ndarray | None`

Return the most recently captured frame as a BGR NumPy array, or `None` if no frame is
available yet.

#### `set_roi(region: tuple[int, int, int, int]) -> None`

Restrict the capture area at runtime.

| Parameter | Type | Description |
|---|---|---|
| `region` | tuple | `(left, top, width, height)` in screen pixels. |

---

## ComputerVision

```python
from computer_vision import ComputerVision
```

Detects the 888 Poker table in a captured frame using HSV colour filtering and shape
analysis.

### Constructor

```python
ComputerVision(cfg: dict)
```

### Methods

#### `detect_poker_table_with_confidence(frame: numpy.ndarray) -> tuple[bool, float, dict]`

Analyse *frame* for a poker table.

Returns `(detected, confidence, metadata)` where:

- `detected` – `True` if a table was found.
- `confidence` – float in `[0, 1]` indicating detection certainty.
- `metadata` – dict with keys `contour`, `bounding_rect`, `area`, `shape_score`.

#### `extract_table_region(frame: numpy.ndarray) -> numpy.ndarray | None`

Return the sub-image corresponding to the detected table region, or `None` if no table
is found.

#### `preprocess_image(frame: numpy.ndarray) -> numpy.ndarray`

Apply grayscale conversion, adaptive thresholding, and Gaussian denoising to *frame*.
Use this before OCR to improve character recognition.

---

## OCRProcessor

```python
from ocr_processor import OCRProcessor
```

Wraps Tesseract (primary) and EasyOCR (fallback) with confidence scoring.

### Constructor

```python
OCRProcessor(cfg: dict)
```

### Methods

#### `extract_text(image: numpy.ndarray) -> str`

Run OCR on *image* and return the raw text string.

#### `extract_numbers(image: numpy.ndarray) -> list[float]`

Run OCR and parse all numeric values (integers and decimals) found in *image*.

Returns a list of `float` values in order of appearance.

#### `get_confidence_score(image: numpy.ndarray) -> float`

Return the mean confidence score (`[0, 1]`) of the last `extract_text` call.

---

## PokerParser

```python
from poker_parser import PokerParser
```

Converts raw OCR text into structured `PokerHandData` dictionaries and tracks session
statistics.

### Constructor

```python
PokerParser(cfg: dict)
```

### Methods

#### `parse_hand(ocr_text: str) -> dict | None`

Parse *ocr_text* and return a hand dictionary, or `None` if the text cannot be parsed.

The returned dict contains:

| Key | Type | Description |
|---|---|---|
| `hand_id` | str | UUID for the hand |
| `timestamp` | float | Unix timestamp |
| `pot` | float | Pot size |
| `small_blind` | float | Small blind amount |
| `big_blind` | float | Big blind amount |
| `players` | list[dict] | Stack sizes and positions |
| `stage` | str | `"preflop"` / `"flop"` / `"turn"` / `"river"` |

#### `extract_pot(ocr_text: str) -> float | None`

Extract just the pot value from *ocr_text*, returning `None` if not found.

#### `extract_blinds(ocr_text: str) -> tuple[float, float] | None`

Return `(small_blind, big_blind)` or `None`.

#### `calculate_vpip(hands: list[dict]) -> float`

Calculate VPIP (Voluntarily Put money In Pot) as a percentage over the supplied hand list.

---

## Pipeline

```python
from pipeline import Pipeline
```

Orchestrates the full capture → CV → OCR → parse → database pipeline using a
producer/consumer architecture.

### Constructor

```python
Pipeline(cfg: dict)
```

### Methods

#### `start() -> None`

Start all background threads (capture, worker pool, database consumer).

#### `stop() -> None`

Send stop signals to all threads and wait for them to finish. Data already in the queue is
flushed to the database before shutdown.

#### `get_statistics() -> dict`

Return a snapshot of runtime statistics:

| Key | Type | Description |
|---|---|---|
| `frames_captured` | int | Total frames grabbed from screen |
| `frames_processed` | int | Frames that passed CV detection |
| `hands_parsed` | int | Successfully parsed hand records |
| `hands_saved` | int | Records written to the database |
| `queue_depth` | int | Current items waiting in the queue |
| `fps_current` | float | Measured FPS (sliding 10-frame window) |
| `uptime_seconds` | float | Seconds since `start()` |

---

## Configuration helpers

```python
from config import load_config, _DEFAULTS
```

#### `load_config() -> dict`

Load `config.json` from the project root, merge with `_DEFAULTS`, and return the combined
configuration dictionary.

#### `_DEFAULTS`

Module-level dictionary containing all default values. Do not mutate this directly; use
`config.json` overrides instead.

---

## Database helpers

```python
from database import DatabaseManager
```

High-level wrapper around the SQLAlchemy ORM models.

#### `insert_hand(hand: dict) -> int`

Persist a hand dictionary to the database. Returns the new row ID.

#### `query_sessions(limit: int = 50) -> list[dict]`

Return a list of recent sessions ordered by start time descending.

#### `export_to_csv(output_path: str, session_id: str | None = None) -> None`

Export hand data to a CSV file. If *session_id* is given, export only that session;
otherwise export all data.
