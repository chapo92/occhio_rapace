"""
Video test analysis script - processes pokere_1980.mp4
Analyzes poker community cards area (ROI) to reduce false positives.
Counts hands based on presence/absence of detections over time.

Update: presence=True only when >=3 card-like detections are found in ROI
(community cards appear from flop onward).
"""

import argparse
import cv2
import sys
import json
from pathlib import Path
from datetime import datetime
import numpy as np
from tqdm import tqdm


class VideoAnalyzer:
    def __init__(self, video_path, config_path='config/card_recognition.json', roi=None):
        self.video_path = Path(video_path)
        self.config = self._load_config(config_path)
        self.cap = None

        # ROI in full-frame coordinates: (x, y, w, h)
        self.roi = roi  # None = full frame

        self.results = {
            'total_frames': 0,
            'analyzed_frames': 0,
            'cards_detected': 0,
            'hands_detected': 0,
            'accuracy_score': 0.0,
            'detected_cards': [],
            'presence_events': [],  # list of {'frame': int, 'time': float, 'present': bool, 'count': int}
            'errors': []
        }

    def _load_config(self, path):
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(config_path, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in config file {path}: {exc}") from exc

    def _crop_roi(self, frame):
        if self.roi is None:
            return frame, (0, 0)

        x, y, w, h = self.roi
        H, W = frame.shape[:2]
        x = max(0, min(x, W - 1))
        y = max(0, min(y, H - 1))
        w = max(1, min(w, W - x))
        h = max(1, min(h, H - y))
        return frame[y:y + h, x:x + w], (x, y)

    def verify_video(self):
        if not self.video_path.exists():
            print(f"❌ Video not found: {self.video_path}")
            return False

        self.cap = cv2.VideoCapture(str(self.video_path))
        if not self.cap.isOpened():
            print(f"❌ Cannot open video: {self.video_path}")
            return False

        fps = self.cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        print(f"\n✅ Video loaded successfully!")
        print(f"   Resolution: {width}x{height}")
        print(f"   FPS: {fps}")
        print(f"   Total frames: {total_frames}")
        print(f"   Duration: {total_frames/fps:.1f} seconds ({total_frames/fps/60:.1f} minutes)")
        if self.roi is not None:
            x, y, w, h = self.roi
            print(f"   ROI: x={x}, y={y}, w={w}, h={h}")

        self.results['total_frames'] = total_frames
        return True

    def analyze_video(self, sample_rate=10, presence_min_cards=3):
        """
        Analyze video frames.

        presence_min_cards:
          Consider "community cards present" only if at least this many card-like
          detections are found in the ROI (>=3 is typical for flop).
        """
        if not self.cap:
            print("❌ Video not loaded")
            return False

        print(f"\n🎬 ANALYZING VIDEO...")
        print(f"   Sampling: every {sample_rate} frames")
        print(f"   Presence rule: present = (detections_in_roi >= {presence_min_cards})")

        frame_count = 0
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

        with tqdm(total=total_frames, desc="Processing frames") as pbar:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    break

                if frame_count % sample_rate == 0:
                    self.results['analyzed_frames'] += 1

                    roi_frame, (ox, oy) = self._crop_roi(frame)
                    cards = self._detect_cards_in_frame(roi_frame)

                    card_count = len(cards)
                    present = card_count >= presence_min_cards

                    self.results['presence_events'].append({
                        'frame': frame_count,
                        'time': frame_count / fps,
                        'present': present,
                        'count': card_count,
                    })

                    if cards:
                        self.results['cards_detected'] += len(cards)
                        for card in cards:
                            x, y, w, h = card['bbox']
                            card_full = dict(card)
                            card_full['bbox'] = (x + ox, y + oy, w, h)
                            self.results['detected_cards'].append({
                                'frame': frame_count,
                                'time': frame_count / fps,
                                'card': card_full
                            })

                frame_count += 1
                pbar.update(1)

        self.cap.release()
        print(f"\n✅ Video analysis complete!")
        return True

    def _detect_cards_in_frame(self, frame):
        cards = []
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
            for color in self.config['hsv_ranges']:
                lower = np.array(self.config['hsv_ranges'][color]['lower'])
                upper = np.array(self.config['hsv_ranges'][color]['upper'])
                mask |= cv2.inRange(hsv, lower, upper)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            min_area = self.config['card_detection']['min_area']
            max_area = self.config['card_detection']['max_area']
            min_ratio = self.config['card_detection']['min_aspect_ratio']
            max_ratio = self.config['card_detection']['max_aspect_ratio']

            for contour in contours:
                area = cv2.contourArea(contour)
                if min_area < area < max_area:
                    x, y, w, h = cv2.boundingRect(contour)
                    ratio = w / h if h > 0 else 0
                    if min_ratio < ratio < max_ratio:
                        cards.append({
                            'bbox': (x, y, w, h),
                            'area': float(area),
                            'ratio': float(ratio)
                        })

        except Exception as e:
            self.results['errors'].append(f"Frame error: {str(e)}")

        return cards

    def count_hands(self, min_silence_seconds=8.0):
        """
        Count hands based on presence/absence timeline.

        A new hand starts when we see present=True after a long enough silent period.
        """
        events = self.results['presence_events']
        if not events:
            self.results['hands_detected'] = 0
            return

        hands = 0
        last_present_time = None
        was_present = False

        for ev in events:
            t = ev['time']
            present = ev['present']

            if present and not was_present:
                if last_present_time is None:
                    hands += 1
                else:
                    silence = t - last_present_time
                    if silence >= min_silence_seconds:
                        hands += 1

            if present:
                last_present_time = t

            was_present = present

        self.results['hands_detected'] = hands

    def calculate_accuracy(self):
        if self.results['analyzed_frames'] == 0:
            self.results['accuracy_score'] = 0.0
            return

        expected_cards = self.results['hands_detected'] * 4.0
        detected = self.results['cards_detected']
        if expected_cards > 0:
            accuracy = (detected / expected_cards) * 100
            accuracy = min(100.0, accuracy)
        else:
            accuracy = 0.0
        self.results['accuracy_score'] = float(accuracy)

    def print_report(self):
        print("\n" + "=" * 70)
        print("📊 VIDEO ANALYSIS REPORT - pokere_1980.mp4")
        print("=" * 70)

        print(f"\n📈 FRAME STATISTICS:")
        print(f"   Total frames: {self.results['total_frames']}")
        print(f"   Analyzed frames: {self.results['analyzed_frames']}")
        analyzed = self.results['analyzed_frames']
        sample_label = f"{self.results['total_frames'] / analyzed:.1f}x" if analyzed > 0 else "N/A"
        print(f"   Sample rate: {sample_label}")

        print(f"\n🎴 CARD DETECTION (ROI-based):")
        print(f"   Cards detected: {self.results['cards_detected']}")
        print(f"   Hands estimated: {self.results['hands_detected']}")
        avg = self.results['cards_detected'] / max(1, self.results['hands_detected'])
        print(f"   Avg detections per hand: {avg:.1f}")

        print(f"\n✅ ACCURACY (heuristic):")
        print(f"   Detection accuracy: {self.results['accuracy_score']:.1f}%")

        if self.results['errors']:
            print(f"\n⚠️ ERRORS ({len(self.results['errors'])}):")
            for error in self.results['errors'][:5]:
                print(f"   - {error}")

        print("\n" + "=" * 70)
        print("✅ TEST COMPLETE!")
        print("=" * 70 + "\n")

    def save_results(self, output_file='test_results.json'):
        output_path = Path(output_file)
        results = {
            'timestamp': datetime.now().isoformat(),
            'video': str(self.video_path),
            'roi': None if self.roi is None else list(self.roi),
            'total_frames': self.results['total_frames'],
            'analyzed_frames': self.results['analyzed_frames'],
            'cards_detected': self.results['cards_detected'],
            'hands_detected': self.results['hands_detected'],
            'accuracy_score': self.results['accuracy_score'],
            'errors_count': len(self.results['errors']),
            'errors': self.results['errors'][:10],
        }
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"✅ Results saved to: {output_path}")
        return True


def main():
    parser = argparse.ArgumentParser(description="Analyze poker video for card detection")
    parser.add_argument("video", nargs="?", default="pokere_1980.mp4")
    parser.add_argument("--sample-rate", type=int, default=10)
    parser.add_argument("--config", default="config/card_recognition.json")
    parser.add_argument("--output", default="test_results_pokere_1980.json")

    # Default ROI tuned from your screenshot (community cards zone)
    parser.add_argument("--roi-x", type=int, default=710)
    parser.add_argument("--roi-y", type=int, default=470)
    parser.add_argument("--roi-w", type=int, default=500)
    parser.add_argument("--roi-h", type=int, default=230)
    parser.add_argument("--no-roi", action="store_true")

    parser.add_argument("--hand-gap", type=float, default=8.0, help="Seconds of no-presence to count a new hand")
    parser.add_argument("--presence-min-cards", type=int, default=3,
                        help="Presence=True only if detections in ROI >= this (default: 3)")

    args = parser.parse_args()

    roi = None if args.no_roi else (args.roi_x, args.roi_y, args.roi_w, args.roi_h)

    print("\n🎬 VIDEO TEST ANALYZER")
    print("=" * 70)
    print(f"Video: {args.video}")
    print("=" * 70)

    analyzer = VideoAnalyzer(args.video, config_path=args.config, roi=roi)

    if not analyzer.verify_video():
        sys.exit(1)

    if not analyzer.analyze_video(sample_rate=args.sample_rate, presence_min_cards=args.presence_min_cards):
        sys.exit(1)

    analyzer.count_hands(min_silence_seconds=args.hand_gap)
    analyzer.calculate_accuracy()
    analyzer.print_report()
    analyzer.save_results(args.output)


if __name__ == "__main__":
    main()