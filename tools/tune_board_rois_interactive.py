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


def draw_overlay(img, board_rect, rects, mode, dx, dy):
    board_x, board_y, board_w, board_h = board_rect
    vis = img.copy()

    cv2.rectangle(vis, (board_x, board_y), (board_x + board_w, board_y + board_h), (0, 255, 255), 2)

    for i, (x, y, w, h) in enumerate(rects, start=1):
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(vis, str(i), (x + 3, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    txt1 = f"MODE={mode}  dx={dx} dy={dy}"
    txt2 = "Move: Arrows or WASD or IJKL | Size: +/- | m=switch | s=save | q=quit"
    cv2.putText(vis, txt1, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(vis, txt2, (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return vis


def main():
    ap = argparse.ArgumentParser(description="Interactive ROI tuner for 888poker board cards.")
    ap.add_argument("--image", default="frame_10s.jpg")
    ap.add_argument("--out", default="roi_preview")
    ap.add_argument("--board-x", type=int, default=710)
    ap.add_argument("--board-y", type=int, default=470)
    ap.add_argument("--board-w", type=int, default=500)
    ap.add_argument("--board-h", type=int, default=230)

    ap.add_argument("--p1", type=float, default=0.10)
    ap.add_argument("--p2", type=float, default=0.30)
    ap.add_argument("--p3", type=float, default=0.50)
    ap.add_argument("--p4", type=float, default=0.70)
    ap.add_argument("--p5", type=float, default=0.90)

    ap.add_argument("--card-w", type=int, default=98)
    ap.add_argument("--card-h", type=int, default=116)
    ap.add_argument("--py", type=float, default=0.22)

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

    board_rect = (args.board_x, args.board_y, args.board_w, args.board_h)
    positions = [args.p1, args.p2, args.p3, args.p4, args.p5]

    mode = "CORNER"  # start directly in CORNER (more useful)
    dx = 0
    dy = 0

    card_w, card_h, py = args.card_w, args.card_h, args.py
    corner_w, corner_h, corner_py_top = args.corner_w, args.corner_h, args.corner_py_top

    def compute_rects():
        board_x, board_y, board_w, board_h = board_rect
        rects = []
        if mode == "FULL":
            for px in positions:
                cx = int(px * board_w) - card_w // 2 + dx
                cy = int(py * board_h) - card_h // 2 + dy
                rects.append((board_x + cx, board_y + cy, card_w, card_h))
        else:
            for px in positions:
                # anchor near card top-left: (slot_center - card_w/2) then crop corner
                tlx = int(px * board_w) - card_w // 2 + dx
                tly = int(corner_py_top * board_h) + dy
                rects.append((board_x + tlx, board_y + tly, corner_w, corner_h))
        return rects

    def refresh():
        rects = compute_rects()
        vis = draw_overlay(img, board_rect, rects, mode, dx, dy)
        cv2.imshow("overlay (click here, then press keys)", vis)

        for i in range(3):
            x, y, w, h = rects[i]
            c = crop(img, x, y, w, h)
            c = cv2.resize(c, (w * 5, h * 5), interpolation=cv2.INTER_NEAREST)
            cv2.imshow(f"crop_{i+1}", c)

    refresh()

    while True:
        k = cv2.waitKey(0)
        if k == -1:
            continue

        # Normalize
        k8 = k & 0xFF  # ASCII part

        # Quit
        if k8 in (ord("q"), 27):
            break

        moved = False

        # Move: WASD
        if k8 == ord("a"):
            dx -= 1; moved = True
        elif k8 == ord("d"):
            dx += 1; moved = True
        elif k8 == ord("w"):
            dy -= 1; moved = True
        elif k8 == ord("s"):
            dy += 1; moved = True

        # Move: IJKL
        elif k8 == ord("j"):
            dx -= 1; moved = True
        elif k8 == ord("l"):
            dx += 1; moved = True
        elif k8 == ord("i"):
            dy -= 1; moved = True
        elif k8 == ord("k"):
            dy += 1; moved = True

        # Move: Arrows (some OpenCV builds return these codes)
        # left=2424832 right=2555904 up=2490368 down=2621440
        elif k in (2424832,):
            dx -= 1; moved = True
        elif k in (2555904,):
            dx += 1; moved = True
        elif k in (2490368,):
            dy -= 1; moved = True
        elif k in (2621440,):
            dy += 1; moved = True

        # Size
        elif k8 in (ord("+"), ord("=")):
            if mode == "FULL":
                card_w += 1; card_h += 1
            else:
                corner_w += 1; corner_h += 1
        elif k8 in (ord("-"), ord("_")):
            if mode == "FULL":
                card_w = max(10, card_w - 1)
                card_h = max(10, card_h - 1)
            else:
                corner_w = max(10, corner_w - 1)
                corner_h = max(10, corner_h - 1)

        # Switch mode
        elif k8 == ord("m"):
            mode = "FULL" if mode == "CORNER" else "CORNER"

        # Save
        elif k8 == ord("p"):  # print/debug
            print("raw key:", k, "ascii:", k8)
        elif k8 == ord("S"):  # (rare) if you have caps lock
            pass
        elif k8 == ord("s") and not moved:
            # NOTE: lowercase s is used for DOWN movement; to save press uppercase 'S' or use 'x' below
            pass
        elif k8 == ord("x"):
            rects = compute_rects()
            # write overlay
            vis = draw_overlay(img, board_rect, rects, mode, dx, dy)
            cv2.imwrite(str(out_dir / "overlay_tuned.jpg"), vis)

            for i, (x, y, w, h) in enumerate(rects, start=1):
                c = crop(img, x, y, w, h)
                cv2.imwrite(str(out_dir / f"{mode.lower()}_{i}.jpg"), c)

            print("=== SAVED ===")
            print("mode:", mode)
            print("dx:", dx, "dy:", dy)
            print("FULL params:", f"card_w={card_w} card_h={card_h} py={py}")
            print("CORNER params:", f"corner_w={corner_w} corner_h={corner_h} corner_py_top={corner_py_top}")
            print(f"Saved to: {out_dir.resolve()}")

        refresh()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()