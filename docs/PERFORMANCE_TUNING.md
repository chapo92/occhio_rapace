# Performance Tuning Guide

This guide explains how to improve the two main dimensions of system performance:
**speed** (frames per second processed) and **accuracy** (correctness of extracted data).

---

## Optimising for FPS

### Screen resolution impact

Capturing a smaller area reduces the amount of pixel data processed per frame.

```json
{
  "capture": {
    "region": [0, 0, 1280, 720]
  }
}
```

Use `--region left,top,width,height` on the command line or set `capture.region` in
`config.json`. Target just the poker window rather than the full desktop.

### Reducing target FPS

Most poker hands last several seconds. Reducing `capture.fps` to `2` – `3` is usually
sufficient and cuts CPU load proportionally.

```json
{ "capture": { "fps": 3 } }
```

### Thread pool size

The default `performance.thread_pool_size = 4` spreads OCR and vision work across CPU cores.
On a quad-core machine this is optimal. On a dual-core machine, reduce to `2`.

```json
{ "performance": { "thread_pool_size": 2 } }
```

### Queue sizing

The inter-thread queue (`performance.queue_size`) decouples the capture thread from the
database thread. A value between `50` and `200` covers most use-cases.

- **Too small** (< 20): capture blocks while the database is busy, dropping frames.
- **Too large** (> 500): high memory consumption with no throughput benefit.

```json
{ "performance": { "queue_size": 100 } }
```

### Batch sizes

Batch database inserts reduce SQLite overhead. The `features/database_manager.py` batches
writes automatically when the queue has multiple items pending. No manual tuning is required
for the default schema.

---

## Optimising for Accuracy

### HSV tuning

The most impactful accuracy setting is the HSV range used to detect the blue table felt.

1. Run the interactive wizard:

   ```bash
   python main.py --calibrate
   ```

2. The wizard samples the exact pixels from your screen and proposes `h_min / h_max` values.
   Accept them or fine-tune manually.

3. If tables are still missed, widen the hue range:

   ```json
   {
     "table_detection": {
       "blue_hsv_range": { "h_min": 90, "h_max": 150 }
     }
   }
   ```

### Confidence thresholds

`table_detection.min_confidence` controls how strict the shape-matching is. Lower values
detect more tables but also produce more false positives.

| Value | Effect |
|---|---|
| 0.90 | Very strict – misses unusual table layouts |
| 0.75 | Default – good balance |
| 0.50 | Permissive – may include non-table regions |

`alerts.ocr_confidence_threshold` controls when a hand result is flagged as low-confidence
and triggers an alert. Raise it to `0.85` if your screen contrast is high.

### OCR preprocessing

Enable `ocr.preprocessing` (default `true`) to apply grayscale conversion, adaptive
thresholding, and denoising before passing frames to Tesseract. This is especially important
on:

- Low-contrast themes
- Scaled / HiDPI screens
- 4K monitors running at 150 % scaling

### Detection parameters

Increase `table_detection.min_confidence` gradually (e.g. `0.75 → 0.80 → 0.85`) while
watching the "detection rate" in the dashboard. Stop when accuracy peaks without causing
too many misses.

---

## Memory Optimisation

### Queue management

Keep `performance.queue_size` between `50` and `200`. Each queued item holds a small
dictionary; at 200 items peak memory overhead is under 10 MB.

### Image caching

The system does not cache raw frames between processing steps. If you add custom pipeline
stages, avoid storing NumPy arrays in long-lived data structures.

### Database retention

Old backups are cleaned up automatically based on `database.retention_days`. Set this to
`7` on disk-constrained machines.

```json
{ "database": { "retention_days": 7 } }
```

---

## CPU Optimisation

### Threading strategy

The pipeline uses a producer/consumer pattern:

- **Capture thread** grabs frames and puts them on the queue.
- **Worker pool** (size `performance.thread_pool_size`) processes frames in parallel.
- **Database thread** drains the queue and writes to SQLite.

This design keeps the capture thread non-blocking. Avoid adding blocking I/O inside the
worker callbacks.

### Processing order

Each frame goes through: `Capture → CV Detection → OCR → Parse → Queue → DB`.

The most expensive stages are **OCR** and **CV Detection**. If the profiler shows OCR as
the bottleneck, reduce `capture.fps` rather than disabling preprocessing (which would hurt
accuracy).

### Parallel vs sequential

OCR for multiple ROI zones runs sequentially by default. If you add custom ROI zones and
experience slowdowns, you can parallelise zone-level OCR using the `thread_pool_size`
setting, but this increases CPU contention.

---

## Reading the Profiler Output

Run a benchmark to generate a bottleneck report:

```bash
python -m features.benchmark_suite --frames 100
```

This produces `bottleneck_report.html` in the `output/` directory. Open it in a browser to
see:

- **Per-stage latency** (P50, P95, P99 in milliseconds)
- **Queue depth over time** (spikes indicate the database is a bottleneck)
- **CPU and memory** usage timeline
- **Recommendations** (e.g. "Reduce FPS", "Increase queue size")

### Interpreting latency metrics

| Metric | Description |
|---|---|
| P50 (median) | Typical frame processing time |
| P95 | 95 % of frames finish within this time |
| P99 | Worst-case latency excluding outliers |

A healthy system should have P99 < 500 ms at 5 FPS.

### Identifying slow stages

The stage breakdown pie chart highlights which component consumes the most time. Common
findings:

| Slowest stage | Likely cause | Fix |
|---|---|---|
| OCR | High-resolution capture, many ROI zones | Lower resolution, fewer zones |
| CV Detection | Large frame size | Set `capture.region` |
| Database | Many concurrent writes | Batch more aggressively, add index |
| Capture | Backend overhead | Use `mss` (default) |
