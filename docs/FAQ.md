# Frequently Asked Questions

---

**Q: Can I run multiple instances simultaneously?**

A: Not on the same screen with the same capture region – both instances would read identical
frames and write duplicate records. Instead, use `capture.region` to point each instance at
a different poker window, and use separate database paths:

```json
{ "capture": { "region": [0, 0, 960, 1080] }, "output": { "database_path": "./table1.db" } }
```

---

**Q: How accurate is the OCR?**

A: With calibration, accuracy is typically 95 % or higher on clear, standard-resolution
screens. Accuracy depends on:
- Font clarity (standard 888 Poker fonts score best)
- Screen contrast and brightness
- Presence of overlapping UI elements

Run `python main.py --calibrate` and enable `ocr.preprocessing` to maximise accuracy.

---

**Q: Can I replay hands from a previous session?**

A: Yes. Export the session to JSON or CSV:

```bash
python data_exporter.py --session SESSION_ID --format json
```

Then re-import or process the exported file with your analysis tool of choice.

---

**Q: How much disk space does the database need?**

A: Approximately **100 MB per 1 000 hands**, depending on how many action records are
stored per hand and whether debug logging is enabled. A typical 4-hour session generates
300–500 MB including logs.

To reduce disk usage:
- Set `database.retention_days` to a lower value (e.g. `7`).
- Disable verbose logging (`debug: false`).

---

**Q: Can I export data to CSV / Excel?**

A: Yes. Use `data_exporter.py`:

```bash
# All sessions
python data_exporter.py --format csv --output all_hands.csv

# Single session
python data_exporter.py --session SESSION_ID --format csv --output session.csv
```

The CSV is compatible with Excel, Google Sheets, and Pandas.

---

**Q: Does it work on Mac?**

A: The core libraries (`mss`, `opencv-python`, `pytesseract`) support macOS. However,
the project is primarily developed and tested on Windows and Linux. On macOS:
- `mss` requires Screen Recording permission (grant in *System Preferences → Privacy*).
- Tesseract can be installed via Homebrew: `brew install tesseract`.

---

**Q: Is it compatible with other poker clients (PokerStars, GGPoker)?**

A: The computer-vision layer is tuned for the 888 Poker blue table felt. Support for
`"pokerstars"` is partially implemented (see `config.platform`). Community contributions
for additional platforms are welcome.

---

**Q: How do I reduce CPU usage?**

A: The three most effective settings:

1. Lower `capture.fps` to `2` – most hands last several seconds, so 2 FPS is sufficient.
2. Set `capture.region` to the poker window only – smaller images process faster.
3. Reduce `performance.thread_pool_size` on low-core machines.

---

**Q: The dashboard shows "Queue full". What does this mean?**

A: The inter-thread queue (`performance.queue_size`) is at capacity. The database thread
cannot keep up with the capture thread. Solutions:
- Increase `performance.queue_size` to give more buffer.
- Lower `capture.fps` to produce fewer frames.
- Ensure the database is on a fast local drive (not a network share).

---

**Q: How do I update the software?**

A:
```bash
git pull
pip install -r requirements.txt --upgrade
```

No database migration is needed for minor updates. Check the `CHANGELOG` for breaking
changes before updating.

---

**Q: Is this tool allowed by 888 Poker's terms of service?**

A: We are not lawyers and this is not legal advice. Please review the
[888 Poker Terms of Service](https://www.888poker.com/poker/terms-conditions) before using
this tool. The user is solely responsible for compliance with applicable terms and laws.
