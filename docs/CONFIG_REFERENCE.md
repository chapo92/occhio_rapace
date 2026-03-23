# Configuration Reference

All runtime parameters live in `config.json` in the project root. If the file does not exist,
the system starts with the defaults documented below. You can create or edit the file at any
time – changes take effect on the next run.

## Top-level keys

| Key | Type | Default | Description |
|---|---|---|---|
| `platform` | string | `"888poker"` | Target poker client. Also supports `"pokerstars"`. |
| `debug` | bool | `false` | Enables verbose debug logging to console and log file. |

---

## `capture` – Screen Capture

| Parameter | Type | Default | Range / Options | Description |
|---|---|---|---|---|
| `fps` | int | `5` | 1 – 30 | Target frames per second. Higher values increase CPU load. Reduce if CPU usage is too high. |
| `resolution` | string | `"auto"` | `"auto"` or `"WxH"` | Override the detected screen resolution (e.g. `"1920x1080"`). |
| `region` | array or null | `null` | `[left, top, width, height]` | Limit capture to a screen sub-region. `null` captures the full screen. Smaller regions are faster. |
| `backend` | string | `"mss"` | `"mss"` | Screen capture backend. `mss` is the only production backend. |
| `timeout_seconds` | int | `10` | 1 – 60 | How long to wait for the first valid frame before aborting. |

---

## `table_detection` – Computer Vision

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `method` | string | `"hsv_adaptive"` | – | Detection algorithm. `hsv_adaptive` uses the learned HSV range. |
| `blue_hsv_range.h_min` | int | `100` | 0 – 179 | Minimum hue for "blue". Run calibration wizard to tune this. |
| `blue_hsv_range.h_max` | int | `140` | 0 – 179 | Maximum hue for "blue". |
| `blue_hsv_range.s_min` | int | `30` | 0 – 255 | Minimum saturation. Lower values include greyer colours. |
| `blue_hsv_range.s_max` | int | `255` | 0 – 255 | Maximum saturation. |
| `blue_hsv_range.v_min` | int | `30` | 0 – 255 | Minimum brightness. Lower values include darker blues. |
| `blue_hsv_range.v_max` | int | `255` | 0 – 255 | Maximum brightness. |
| `shape_tolerance` | float | `0.05` | 0.0 – 1.0 | How much the detected contour can deviate from a rectangle. Lower = stricter. |
| `min_confidence` | float | `0.75` | 0.0 – 1.0 | Minimum detection confidence score to treat a region as a valid table. |
| `auto_calibrate` | bool | `true` | – | Automatically re-calibrate HSV thresholds when detection rate drops below 50 %. |

### When to adjust HSV values

- Run `python main.py --calibrate` for an interactive wizard.
- If the table is not detected: widen the hue range (lower `h_min`, raise `h_max`).
- If non-table areas are falsely detected: narrow the range or raise `min_confidence`.

---

## `ocr` – Optical Character Recognition

| Parameter | Type | Default | Description |
|---|---|---|---|
| `engine` | string | `"hybrid"` | OCR engine. `"hybrid"` uses Tesseract with EasyOCR as fallback. |
| `tesseract_lang` | string | `"eng"` | Tesseract language pack(s), e.g. `"eng"` or `"eng+ita"`. |
| `tesseract_path` | string or null | `null` | Absolute path to the `tesseract` binary. Required on Windows if Tesseract is not on `PATH`. |
| `preprocessing` | bool | `true` | Apply image preprocessing (grayscale, threshold, denoise) before OCR. Improves accuracy on low-contrast screens. |
| `whitelist_digits` | bool | `true` | Restrict character set to digits and currency symbols. Reduces errors in numeric fields. |
| `fallback_engine` | string | `"easyocr"` | Engine to use when Tesseract confidence is below the alert threshold. |

---

## `output` – Data Export

| Parameter | Type | Default | Description |
|---|---|---|---|
| `format` | string | `"json"` | Output format for raw hand data. |
| `directory` | string | `"./output/"` | Directory for JSON hand files. Created automatically. |
| `session_directory` | string | `"./output/sessions/"` | Per-session sub-directories. |
| `interval_ms` | int | `1000` | Milliseconds between output flushes. |
| `database_path` | string | `"./output/poker_data.db"` | SQLite database file path. |

---

## `validation` – Data Validation

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `enable` | bool | `true` | – | Enable sanity checks on parsed values. |
| `max_stack` | int | `10000` | 1 – ∞ | Maximum plausible stack size. Values above this are rejected. |
| `max_pot` | int | `50000` | 1 – ∞ | Maximum plausible pot size. |
| `min_blind` | float | `0.01` | 0 – ∞ | Minimum plausible blind amount. |
| `sanity_check_threshold` | float | `0.7` | 0.0 – 1.0 | Fraction of fields that must pass validation for a hand to be saved. |

---

## `alerts` – Alert System

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enable` | bool | `true` | Master switch for all alerts. |
| `sound` | bool | `true` | Play a system sound on important events. |
| `stage_change` | bool | `true` | Alert when the hand stage changes (flop/turn/river). |
| `ocr_confidence_threshold` | float | `0.7` | Hands with OCR confidence below this value trigger a low-confidence alert. |
| `confidence_alert_threshold` | float | `0.8` | Secondary threshold for dashboard warnings. |

---

## `performance` – Resource Limits

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `max_cpu_percent` | int | `30` | 1 – 100 | CPU usage warning threshold (percent). A bottleneck report is generated when exceeded. |
| `max_memory_mb` | int | `500` | 1 – ∞ | Memory usage warning threshold (MB). |
| `thread_pool_size` | int | `4` | 1 – 16 | Number of worker threads in the processing pool. |
| `queue_size` | int | `100` | 1 – 10000 | Maximum items in the inter-thread queue. Larger values buffer more frames during database slowdowns but use more memory. |

---

## `database` – SQLite Database

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enable` | bool | `true` | Write hand data to the SQLite database. |
| `auto_backup` | bool | `true` | Create a timestamped backup before each session. |
| `retention_days` | int | `30` | Automatically delete backups older than this many days. |

---

## Example `config.json`

```json
{
  "platform": "888poker",
  "debug": false,
  "capture": {
    "fps": 5,
    "region": null,
    "backend": "mss"
  },
  "table_detection": {
    "blue_hsv_range": {
      "h_min": 100, "h_max": 140,
      "s_min": 30, "s_max": 255,
      "v_min": 30, "v_max": 255
    },
    "min_confidence": 0.75
  },
  "ocr": {
    "tesseract_path": null,
    "preprocessing": true
  },
  "output": {
    "database_path": "./output/poker_data.db"
  },
  "performance": {
    "queue_size": 100
  }
}
```
