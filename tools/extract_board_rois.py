import argparse
from pathlib import Path
import cv2


def clamp(v, lo, hi):
    return max(lo, min(v, hi))


def crop(img, x, y, w, h):
    H, W = img.shape[:2]
    x = clamp(x, 0, W - 1)
    y = clamp(y, 0, H - 1)
    w = clamp(w, 1, W - x)
    h = clamp(h, 1, H - y)
    return img[y:y + h, x:x + w]


def main():
    ap = argparse.ArgumentParser(description="Extract rank/suit corner ROIs for 5 board cards (888poker tuned).")
    ap.add_argument("--image", default="frame_10s.jpg")
    ap.add_argument("--out", default="roi_out_corner")

    # Board rect (full-frame coords) - from your earlier setup
    ap.add_argument("--board-x", type=int, default=710)
    ap.add_argument("--board-y", type=int, default=470)
    ap.add_argument("--board-w", type=int, default=500)
    ap.add_argument("--board-h", type=int, default=230)

    # Slot centers across board
    ap.add_argument("--p1", type=float, default=0.10)
    ap.add_argument("--p2", type=float, default=0.30)
    ap.add_argument("--p3", type=float, default=0.50)
    ap.add_argument("--p4", type=float, default=0.70)
    ap.add_argument("--p5", type=float, default=0.90)

    # Approx card width used to convert slot-center to slot-top-left
    ap.add_argument("--card-w", type=int, default=98)

    # ✅ Your CORNER saved params
    ap.add_argument("--dx", type=int, default=0)
    ap.add_argument("--dy", type=int, default=-31)
    ap.add_argument("--corner-w", type=int, default=64)
    ap.add_argument("--corner-h", type=int, default=64)
    ap.add_argument("--corner-py-top", type=float, default=0.02)

    args = ap.parse_args()

    img_path = Path(args.image)
    if not img_path.exists():
        raise SystemExit(f"Image not found: {img_path.resolve()}")

    img = cv2.imread(str(img_path))
    if img is None:
        raise SystemExit(f"Failed to read image: {img_path.resolve()}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    board = crop(img, args.board_x, args.board_y, args.board_w, args.board_h)
    cv2.imwrite(str(out_dir / "board_area.jpg"), board)

    positions = [args.p1, args.p2, args.p3, args.p4, args.p5]

    for i, px in enumerate(positions, start=1):
        # card-slot top-left inside board ROI
        tlx = int(px * args.board_w) - args.card_w // 2 + args.dx
        tly = int(args.corner_py_top * args.board_h) + args.dy

        corner = crop(board, tlx, tly, args.corner_w, args.corner_h)
        cv2.imwrite(str(out_dir / f"corner_{i}.jpg"), corner)

    print(f"✅ Saved corners to: {out_dir.resolve()}")
    print("Check corner_1.jpg..corner_5.jpg (should show rank+suit).")


if __name__ == "__main__":
    main()