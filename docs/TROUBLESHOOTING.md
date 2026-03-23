# Troubleshooting Guide

## Common Issues

---

### "Cannot find Tesseract" / "TesseractNotFound"

**Symptoms:** The application exits immediately with an error mentioning Tesseract.

**Solutions:**

1. Set the explicit path in `config.json`:

   ```json
   { "ocr": { "tesseract_path": "C:\\Program Files\\Tesseract-OCR\\tesseract.exe" } }
   ```

2. On Windows, verify the installation path in File Explorer, then add it to `PATH`:
   - Open *System Properties → Advanced → Environment Variables*.
   - Select *Path* → Edit → New → paste the Tesseract directory.

3. On Linux:
   ```bash
   which tesseract          # should print /usr/bin/tesseract
   sudo apt install tesseract-ocr
   ```

---

### "Blue table not detected" / Detection rate 0 %

**Symptoms:** The dashboard shows `Detection: 0 %` even though a poker table is on screen.

**Solutions:**

1. Run the calibration wizard with the table visible:
   ```bash
   python main.py --calibrate
   ```

2. Manually widen the HSV range in `config.json`:
   ```json
   {
     "table_detection": {
       "blue_hsv_range": { "h_min": 90, "h_max": 150 }
     }
   }
   ```

3. Check lighting: if the room lighting is very warm (orange/yellow), the table colour
   shifts in HSV. Lower `s_min` to `20` to include less-saturated blues.

4. Verify screen resolution: the system captures `capture.region` pixels. If the region
   does not include the poker window, no table will ever be found.

---

### "OCR accuracy low" / Numbers extracted incorrectly

**Symptoms:** Pot or blind values in the dashboard are wrong or missing.

**Solutions:**

1. Enable preprocessing if it is disabled:
   ```json
   { "ocr": { "preprocessing": true } }
   ```

2. Lower the confidence alert threshold to reduce false "low confidence" warnings:
   ```json
   { "alerts": { "ocr_confidence_threshold": 0.6 } }
   ```

3. Make sure `ocr.whitelist_digits` is `true` to restrict recognition to numeric characters.

4. On HiDPI screens (150 %+ scaling), reduce capture region to the exact poker window
   bounds so that OCR receives full-resolution pixels.

5. Check the font: if the 888 Poker client has a custom theme with unusual fonts, the
   Tesseract `eng` model may struggle. Try adding EasyOCR as the primary engine:
   ```json
   { "ocr": { "engine": "easyocr" } }
   ```

---

### "Database locked" / SQLite error

**Symptoms:** Error message containing `database is locked` in the log file.

**Solutions:**

1. Ensure only one instance of the application is running.
2. Close any SQLite browser (e.g. DB Browser for SQLite) that has the database open.
3. Restart the application – the error recovery system will resume from the last checkpoint.
4. If the database file is on a network drive, move it to a local path:
   ```json
   { "output": { "database_path": "C:/Users/you/poker_data.db" } }
   ```

---

### "Out of memory" / System becomes unresponsive

**Symptoms:** RAM usage climbs over several minutes; OS shows low-memory warnings.

**Solutions:**

1. Reduce the inter-thread queue size:
   ```json
   { "performance": { "queue_size": 50 } }
   ```

2. Lower the capture resolution or region size:
   ```json
   { "capture": { "region": [0, 0, 1280, 720] } }
   ```

3. Reduce `capture.fps` to `2` or `3`.

4. Disable EasyOCR fallback if you don't need it – the EasyOCR model loads ~500 MB:
   ```json
   { "ocr": { "engine": "tesseract" } }
   ```

---

### "FPS dropping" / Sluggish performance

**Symptoms:** The dashboard shows current FPS well below the target.

**Solutions:**

1. Lower the target FPS:
   ```json
   { "capture": { "fps": 2 } }
   ```

2. Restrict the capture region to the poker window only (smaller = faster).

3. Run the profiler to identify the slowest stage:
   ```bash
   python -m features.benchmark_suite --frames 100
   ```
   Open `output/bottleneck_report.html` to see which stage is the bottleneck.

4. On Windows, close other applications to free CPU cores.

5. Reduce `performance.thread_pool_size` on dual-core machines to avoid context-switching
   overhead:
   ```json
   { "performance": { "thread_pool_size": 2 } }
   ```

---

### "Checkpoint not found" / Cannot resume session

**Symptoms:** After a crash, the system starts a fresh session instead of resuming.

**Solutions:**

1. Checkpoints are stored in the `output/` directory as `checkpoint_*.json`. Verify the
   directory is writable.
2. If the checkpoint file is corrupted (shown in the log), the system falls back to a clean
   start. This is intentional – hand data already saved to the database is preserved.
3. Increase checkpoint frequency by reducing `features/checkpoint_system.py`'s interval
   constant (default: every 100 frames).

---

## Reading the Performance Profiler

After running a benchmark (`python -m features.benchmark_suite`), open
`output/bottleneck_report.html` in a browser.

### Key sections

| Section | What to look for |
|---|---|
| Stage latency chart | Bars significantly taller than others indicate bottlenecks |
| Queue depth timeline | Spikes indicate the database thread is slower than capture |
| CPU timeline | Sustained > 80 % suggests reducing FPS or thread count |
| Memory timeline | Continuous growth (no plateau) indicates a memory leak |
| Recommendations box | Automated suggestions based on the above data |

### Interpreting latency metrics

- **P50**: half of frames process faster than this. Aim for < 200 ms at 5 FPS.
- **P95**: 95 % of frames finish within this time.
- **P99**: worst-case latency. Values > 1000 ms suggest intermittent blocking.
