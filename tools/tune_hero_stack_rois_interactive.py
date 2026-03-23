"""
Interactive calibration tool for hero card corners, hero stack,
seat name/stack ROIs, and blinds ROI on a 888 Poker 9-max layout.

Usage
-----
    python tools/tune_hero_stack_rois_interactive.py --image frame.jpg

Controls (OpenCV window)
------------------------
    Mouse drag   : draw a new ROI rectangle on the image
    r            : reset the drawn rectangle
    Enter / s    : save current ROI to rois_888.json for the active slot
    n            : cycle to the next ROI slot
    p            : cycle to the previous ROI slot
    q / Esc      : quit and write updated rois_888.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROIS_CFG = _REPO_ROOT / "config" / "rois_888.json"


def _load_cfg() -> Dict[str, Any]:
    if _ROIS_CFG.exists():
        with open(_ROIS_CFG, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _save_cfg(cfg: Dict[str, Any]) -> None:
    _ROIS_CFG.parent.mkdir(parents=True, exist_ok=True)
    with open(_ROIS_CFG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    print(f"✅  Saved: {_ROIS_CFG}")


# ---------------------------------------------------------------------------
# ROI slot definitions — what we want to calibrate
# ---------------------------------------------------------------------------

ROI_SLOTS: List[Dict[str, Any]] = [
    {"key": "hero_corners", "index": 0, "label": "Hero card 1 corner",
     "cfg_path": ["hero_corners", 0]},
    {"key": "hero_corners", "index": 1, "label": "Hero card 2 corner",
     "cfg_path": ["hero_corners", 1]},
    {"key": "hero_stack", "index": None, "label": "Hero stack OCR region",
     "cfg_path": ["hero_stack"]},
    {"key": "blinds_roi", "index": None, "label": "Blinds OCR region",
     "cfg_path": ["blinds", "roi"]},
]

# Add 9 seat slots dynamically
for _i in range(9):
    ROI_SLOTS.append({
        "key": f"seat_{_i+1}_name",
        "index": _i,
        "label": f"Seat {_i+1} name OCR",
        "cfg_path": ["seats_9max", "name_rois", _i],
    })
    ROI_SLOTS.append({
        "key": f"seat_{_i+1}_stack",
        "index": _i,
        "label": f"Seat {_i+1} stack OCR",
        "cfg_path": ["seats_9max", "stack_rois", _i],
    })


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _cfg_get(cfg: Dict, path: List) -> Optional[Any]:
    """Navigate nested dict/list by path."""
    cur: Any = cfg
    for part in path:
        if isinstance(cur, list):
            if not isinstance(part, int) or part >= len(cur):
                return None
            cur = cur[part]
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def _cfg_set(cfg: Dict, path: List, value: Any) -> None:
    """Set a value in nested dict/list, creating intermediate containers."""
    cur: Any = cfg
    for i, part in enumerate(path[:-1]):
        next_part = path[i + 1]
        if isinstance(cur, list):
            while len(cur) <= part:
                cur.append(None)
            if cur[part] is None:
                cur[part] = [] if isinstance(next_part, int) else {}
            cur = cur[part]
        else:
            if part not in cur or cur[part] is None:
                cur[part] = [] if isinstance(next_part, int) else {}
            cur = cur[part]
    # Set final value
    last = path[-1]
    if isinstance(cur, list):
        while len(cur) <= last:
            cur.append(None)
        cur[last] = value
    else:
        cur[last] = value


# ---------------------------------------------------------------------------
# Drawing state
# ---------------------------------------------------------------------------

class DrawState:
    def __init__(self):
        self.drawing = False
        self.start: Optional[Tuple[int, int]] = None
        self.end: Optional[Tuple[int, int]] = None
        self.rect: Optional[Tuple[int, int, int, int]] = None  # x, y, w, h

    def reset(self):
        self.drawing = False
        self.start = None
        self.end = None
        self.rect = None


_state = DrawState()
_base_img: Optional[np.ndarray] = None


def _mouse_cb(event, x, y, flags, param):
    global _state
    if event == cv2.EVENT_LBUTTONDOWN:
        _state.drawing = True
        _state.start = (x, y)
        _state.end = (x, y)
        _state.rect = None
    elif event == cv2.EVENT_MOUSEMOVE and _state.drawing:
        _state.end = (x, y)
    elif event == cv2.EVENT_LBUTTONUP:
        _state.drawing = False
        _state.end = (x, y)
        if _state.start:
            x1, y1 = _state.start
            x2, y2 = _state.end
            rx, ry = min(x1, x2), min(y1, y2)
            rw, rh = abs(x2 - x1), abs(y2 - y1)
            if rw > 2 and rh > 2:
                _state.rect = (rx, ry, rw, rh)


def _draw_overlay(
    base: np.ndarray,
    slot: Dict,
    cfg: Dict,
    state: DrawState,
) -> np.ndarray:
    img = base.copy()
    label = slot["label"]

    # Existing ROI from config (green)
    existing = _cfg_get(cfg, slot["cfg_path"])
    if existing and len(existing) == 4:
        x, y, w, h = existing
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 200, 0), 1)
        cv2.putText(img, "cfg", (x, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 0), 1)

    # Currently drawn ROI (yellow, live)
    if state.drawing and state.start and state.end:
        x1, y1 = state.start
        x2, y2 = state.end
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 200, 255), 1)
    elif state.rect:
        rx, ry, rw, rh = state.rect
        cv2.rectangle(img, (rx, ry), (rx + rw, ry + rh), (0, 0, 255), 2)

    # Instructions overlay
    cv2.rectangle(img, (0, 0), (500, 60), (0, 0, 0), -1)
    cv2.putText(img, f"Slot: {label}", (6, 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
    cv2.putText(img, "Drag=draw  Enter/s=save  n=next  p=prev  r=reset  q=quit",
                (6, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    if state.rect:
        cv2.putText(img, f"New ROI: {state.rect}", (6, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
    return img


def run(image_path: str) -> None:
    global _base_img, _state

    img = cv2.imread(image_path)
    if img is None:
        sys.exit(f"❌  Cannot read image: {image_path}")

    _base_img = img.copy()
    cfg = _load_cfg()

    win = "888poker ROI calibration"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, _mouse_cb)

    slot_idx = 0
    print(f"\n{'='*60}")
    print("888poker ROI calibration tool")
    print(f"{'='*60}")
    print("Drag to draw ROI, Enter/s to save, n/p to change slot, q to quit.")
    print()

    while True:
        slot = ROI_SLOTS[slot_idx % len(ROI_SLOTS)]
        frame = _draw_overlay(_base_img, slot, cfg, _state)
        cv2.imshow(win, frame)
        key = cv2.waitKey(16) & 0xFF

        if key in (ord('q'), 27):  # q or Esc
            break
        elif key in (13, ord('s')):  # Enter or s — save
            if _state.rect:
                _cfg_set(cfg, slot["cfg_path"], list(_state.rect))
                print(f"  Saved {slot['label']}: {_state.rect}")
                _state.reset()
            else:
                print("  ⚠  No ROI drawn yet (drag to draw)")
        elif key == ord('r'):
            _state.reset()
        elif key == ord('n'):
            slot_idx += 1
            _state.reset()
            print(f"  → {ROI_SLOTS[slot_idx % len(ROI_SLOTS)]['label']}")
        elif key == ord('p'):
            slot_idx = max(0, slot_idx - 1)
            _state.reset()
            print(f"  → {ROI_SLOTS[slot_idx % len(ROI_SLOTS)]['label']}")

    cv2.destroyAllWindows()
    _save_cfg(cfg)


def main():
    ap = argparse.ArgumentParser(
        description="Interactive ROI calibration for 888poker hero/stack/seat layout."
    )
    ap.add_argument("--image", default="frame_10s.jpg",
                    help="Reference screenshot (full-frame 1920×1080 recommended)")
    args = ap.parse_args()

    image_path = args.image
    if not os.path.isabs(image_path):
        # Try relative to repo root first, then cwd
        candidate = str(_REPO_ROOT / image_path)
        if os.path.exists(candidate):
            image_path = candidate

    run(image_path)


if __name__ == "__main__":
    main()
