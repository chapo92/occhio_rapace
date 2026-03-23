# Troubleshooting Guide — Occhi di Falco 🦅

---

## Table of Contents

1. [Installation Issues](#installation-issues)
2. [Screen Capture Problems](#screen-capture-problems)
3. [Table Detection Issues](#table-detection-issues)
4. [OCR Problems](#ocr-problems)
5. [Performance Issues](#performance-issues)
6. [Database Issues](#database-issues)
7. [Dashboard Issues](#dashboard-issues)
8. [Calibration Issues](#calibration-issues)

---

## Installation Issues

### `ModuleNotFoundError: No module named 'cv2'`
```bash
pip install opencv-python
```

### `ModuleNotFoundError: No module named 'mss'`
```bash
pip install mss
```

### `pytesseract.pytesseract.TesseractNotFoundError`
Tesseract binary is not installed or not in PATH.

**Ubuntu/Debian:**
```bash
sudo apt install tesseract-ocr
```

**macOS:**
```bash
brew install tesseract
```

**Windows:**
Download from [UB-Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) and add to PATH.

Verify:
```bash
tesseract --version
```

### EasyOCR download taking too long
EasyOCR downloads model files on first use (~100-300 MB). This is normal.
Run once to pre-download:
```bash
python -c "import easyocr; easyocr.Reader(['en'])"
```

---

## Screen Capture Problems

### Black or empty frame captured
- Ensure the poker client window is **not minimised**
- On some systems, hardware-accelerated windows may appear black
- Try using `--region left,top,width,height` to specify exact coordinates

### `RuntimeError: No screen capture backend found`
Install at least one of:
```bash
pip install mss          # recommended
pip install pyautogui    # fallback
```

### High CPU usage during capture
Reduce FPS:
```bash
python main.py --fps 2
```

Or limit capture region:
```bash
python main.py --region 100,100,1200,900
```

---

## Table Detection Issues

### "Table not detected" — 888 Poker table not recognized

**Symptom:** Logs show `no_contours` or `too_small` for table detection.

**Causes and fixes:**

1. **Wrong colour range** — Run calibration:
   ```bash
   python main.py --calibrate
   ```

2. **Table partially off-screen** — Move the table window fully on screen.

3. **Too-dark or too-light theme** — Manually adjust HSV range in `config.json`:
   ```json
   "table_detection": {
     "blue_hsv_range": {
       "h_min": 95,
       "h_max": 145,
       "s_min": 25,
       "s_max": 255,
       "v_min": 25,
       "v_max": 255
     }
   }
   ```

4. **Debug mode** — Enable to see what the CV sees:
   ```bash
   python main.py --debug
   ```

### Table detected intermittently
- Increase `min_confidence` threshold tolerance by lowering it:
  ```json
  "table_detection": { "min_confidence": 0.6 }
  ```
- Check for UI overlays (chat boxes, menus) covering the table

---

## OCR Problems

### Stack values not extracted

**Check:**
- Is the text white/yellow on dark background? (888 Poker standard)
- Is the table zoomed in enough? OCR needs at least ~12px font height
- Enable debug to save OCR crops:
  ```bash
  python main.py --debug
  ```

### OCR reads wrong numbers (e.g. `1O` instead of `10`)

This is a common font recognition issue. Fix:

1. Ensure Tesseract is installed (digit-only mode is more accurate than EasyOCR for numbers)
2. Check `tesseract_config` in `config.json`:
   ```json
   "ocr": {
     "engine": "hybrid",
     "preprocessing": true,
     "whitelist_digits": true
   }
   ```

### `WARNING: EasyOCR not installed`

EasyOCR is optional but recommended as fallback:
```bash
pip install easyocr
```

---

## Performance Issues

### Low FPS (below target)

**Check system resources:**
```bash
python main.py --debug
# Watch "FPS:" in dashboard output
```

**Solutions:**
1. Reduce target FPS:
   ```json
   "capture": { "fps": 2 }
   ```
2. Reduce queue size:
   ```json
   "performance": { "queue_size": 20 }
   ```
3. Disable OCR GPU if causing delays (counterintuitive for small images):
   ```json
   "ocr": { "engine": "tesseract" }
   ```

### High memory usage

If memory grows unboundedly, the actions history may be accumulating.
Reset session periodically or reduce history limit in `core/poker_parser.py`:
```python
MAX_ACTIONS_HISTORY = 100  # default
```

---

## Database Issues

### `sqlite3.OperationalError: unable to open database file`

Ensure the output directory exists and is writable:
```bash
mkdir -p output/
```

Or change the database path:
```json
"output": { "database_path": "/tmp/poker_data.db" }
```

### Database grows too large

Enable auto-cleanup:
```json
"database": {
  "auto_backup": true,
  "retention_days": 7
}
```

Or manually clean:
```python
from features.database_manager import DatabaseManager
db = DatabaseManager("output/poker_data.db")
db.cleanup_old_sessions(days=7)
```

---

## Dashboard Issues

### `ModuleNotFoundError: No module named 'rich'`

Install rich for the live dashboard:
```bash
pip install rich
```

Or run without dashboard:
```bash
python main.py --no-dashboard
```

### Dashboard not updating / frozen

The dashboard uses `rich.Live` which may conflict with some terminals.

Try:
```bash
python main.py --no-dashboard
```

---

## Calibration Issues

### Calibration saves wrong colour range

1. Ensure the 888 Poker table is fully visible during calibration
2. Close other blue windows/apps
3. Re-run calibration:
   ```bash
   python main.py --calibrate
   ```

### `config.json` not updated after calibration

Check file permissions:
```bash
ls -la config.json
chmod 644 config.json
```

---

## Getting Help

1. Enable debug logging: `python main.py --debug`
2. Check log file: `output/occhi_di_falco.log`
3. Run tests to verify your installation:
   ```bash
   python -m pytest tests/ -v
   ```

---

## Version Info

```bash
python -c "import cv2, numpy; print(f'OpenCV {cv2.__version__}, NumPy {numpy.__version__}')"
python --version
```
