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
    p = argparse.ArgumentParser(
        description="Preview 5 board-card ROIs (rank/suit corner) from a screenshot frame (888poker tuned)."
    )
    p.add_argument("--image", default="frame_10s.jpg", help="Input image (default: frame_10s.jpg)")
    p.add_argument("--out", default="roi_preview", help="Output directory (default: roi_preview)")

    # Board rect (full-frame coordinates)
    p.add_argument("--board-x", type=int, default=710)
    p.add_argument("--board-y", type=int, default=470)
    p.add_argument("--board-w", type=int, default=500)
    p.add_argument("--board-h", type=int, default=230)

    # Approx card top-left positions inside the board area (percent across / percent down)
    # We use these to locate each card, then crop ONLY the top-left corner (rank/suit).
    p.add_argument("--p1", type=float, default=0.02)
    p.add_argument("--p2", type=float, default=0.22)
    p.add_argument("--p3", type=float, default=0.42)
    p.add_argument("--p4", type=float, default=0.62)
    p.add_argument("--p5", type=float, default=0.82)
    p.add_argument("--py-top", type=float, default=0.02)

    # Fine tuning in pixels (applied inside board ROI)
    # ✅ Updated defaults based on your last screenshots:
    # move RIGHT (+8) and UP (-6) so the corner contains rank+small suit.
    p.add_argument("--dx", type=int, default=8, help="Shift card top-left X by pixels (default tuned)")
    p.add_argument("--dy", type=int, default=-6, help="Shift card top-left Y by pixels (default tuned)")

    # Corner crop size (rank/suit region)
    p.add_argument("--corner-w", type=int, default=64)
    p.add_argument("--corner-h", type=int, default=64)

    args = p.parse_args()

    img_path = Path(args.image)
    if not img_path.exists():
        raise SystemExit(f"Image not found: {img_path.resolve()}")

    img = cv2.imread(str(img_path))
    if img is None:
        raise SystemExit(f"Failed to read image: {img_path.resolve()}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Crop the board area
    board = crop(img, args.board_x, args.board_y, args.board_w, args.board_h)
    cv2.imwrite(str(out_dir / "board_area.jpg"), board)

    pxs = [args.p1, args.p2, args.p3, args.p4, args.p5]

    # Create overlay on full image
    vis = img.copy()
    cv2.rectangle(
        vis,
        (args.board_x, args.board_y),
        (args.board_x + args.board_w, args.board_y + args.board_h),
        (0, 255, 255),
        2
    )

    # Add label
    label = f"dx={args.dx} dy={args.dy} corner={args.corner_w}x{args.corner_h}"
    cv2.putText(
        vis,
        label,
        (args.board_x, max(30, args.board_y - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 255),
        2
    )

    for i, px in enumerate(pxs, start=1):
        # Approx card top-left inside board ROI
        tlx = int(px * args.board_w) + args.dx
        tly = int(args.py_top * args.board_h) + args.dy

        # Corner ROI inside board
        corner = crop(board, tlx, tly, args.corner_w, args.corner_h)
        cv2.imwrite(str(out_dir / f"corner_{i}.jpg"), corner)

        # Draw corner ROI on full image
        x = args.board_x + tlx
        y = args.board_y + tly
        cv2.rectangle(vis, (x, y), (x + args.corner_w, y + args.corner_h), (0, 255, 0), 2)
        cv2.putText(vis, str(i), (x + 2, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    cv2.imwrite(str(out_dir / "overlay.jpg"), vis)

    print(f"✅ Wrote corner previews to: {out_dir.resolve()}")
    print("   Check roi_preview/overlay.jpg and roi_preview/corner_1.jpg ... corner_5.jpg")
    print("   Goal: each corner image contains rank+small suit clearly (e.g. '8♦', 'J♣', 'J♥').")
    print("   If needed, override with: py tools/preview_board_rois.py --dx N --dy N")


if __name__ == "__main__":
    main()