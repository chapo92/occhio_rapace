# Video Test Guide - pokere_1980.mp4

## Quick Start

```bash
python scripts/test/test_video_analysis.py
```

Analyzes the entire 20-minute `pokere_1980.mp4` video.

---

## What Happens

### Step 1: Load Video
- Opens `pokere_1980.mp4`
- Verifies: 720p HD, MP4, 20 minutes

### Step 2: Frame Sampling
- Analyzes every 5th frame (fast processing)
- Processes ~120 frames/minute
- Full 20-min video = ~2400 frames analyzed

### Step 3: Card Detection
- HSV color matching per frame
- Detects poker cards
- Counts cards per hand

### Step 4: Hand Counting
- Heuristic: 5+ second gap = new hand
- Estimates total hands in video

### Step 5: Accuracy Calculation
- Expected: 4-5 cards per hand
- Detected: actual cards found
- Accuracy % = (detected/expected) × 100

---

## Expected Results

For `pokere_1980.mp4` (20 minutes):

```
Approximate:
  - Total frames: 36,000 (at 30 FPS)
  - Analyzed: 7,200 frames
  - Hands: 50-100 hands
  - Cards: 200-500 cards detected
  - Accuracy: 60-90% (depends on lighting)
```

---

## Output

### Console Report

```
📊 VIDEO ANALYSIS REPORT - pokere_1980.mp4
══════════════════════════════════════════

📈 FRAME STATISTICS:
   Total frames: 36000
   Analyzed frames: 7200
   Sample rate: 5.0x

🎴 CARD DETECTION:
   Cards detected: 350
   Hands estimated: 75
   Avg cards per hand: 4.7

✅ ACCURACY:
   Detection accuracy: 82.5%

✅ TEST COMPLETE!
```

### JSON Results

File: `test_results_pokere_1980.json`

```json
{
  "timestamp": "2026-03-22T...",
  "video": "chapo92/pokere/pokere_1980.mp4",
  "total_frames": 36000,
  "analyzed_frames": 7200,
  "cards_detected": 350,
  "hands_detected": 75,
  "accuracy_score": 82.5,
  "errors_count": 2,
  "errors": [...]
}
```

---

## Troubleshooting

**"Video not found"**
- Check path: `chapo92/pokere/pokere_1980.mp4`
- Verify the file exists
- Check the file is readable

**"Cannot open video"**
- Verify MP4 codec is supported
- Try: `ffmpeg -i pokere_1980.mp4` to check

**"Low accuracy (< 50%)"**
- Adjust HSV ranges in `config/card_recognition.json`
- Try manual calibration
- Check lighting conditions in the video

---

## Next Step: LIVE TEST

After video test verification:

```bash
python main.py --live
```

Live 888 Poker test (30-60 minutes)!
