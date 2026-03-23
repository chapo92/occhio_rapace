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
    ap = argparse.ArgumentParser(description="Manual player cards corner ROI extractor (modifica i parametri a piacere).")
    ap.add_argument("--image", default="player_cards_frame.jpg", help="Input image/frame")
    ap.add_argument("--out", default="roi_out_player", help="Output directory")

    # Modifica liberamente questi valori!
    ap.add_argument("--card1-x", type=int, default=1110)
    ap.add_argument("--card1-y", type=int, default=610)
    ap.add_argument("--card2-x", type=int, default=1175)
    ap.add_argument("--card2-y", type=int, default=610)
    ap.add_argument("--corner-w", type=int, default=40)
    ap.add_argument("--corner-h", type=int, default=40)

    args = ap.parse_args()

    img_path = Path(args.image)
    if not img_path.exists():
        raise SystemExit(f"Image not found: {img_path.resolve()}")

    img = cv2.imread(str(img_path))
    if img is None:
        raise SystemExit(f"Failed to read image: {img_path.resolve()}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Crop delle due carte (modifica card1-x, card1-y, card2-x, card2-y per aggiustare)
    card1 = crop(img, args.card1-x, args.card1-y, args.corner-w, args.corner-h)
    card2 = crop(img, args.card2-x, args.card2-y, args.corner-w, args.corner-h)

    cv2.imwrite(str(out_dir / "player_card1_corner.jpg"), card1)
    cv2.imwrite(str(out_dir / "player_card2_corner.jpg"), card2)

    print(f"✅ Saved manual corners to: {out_dir.resolve()}")
    print("Regola --card1-x/y, --card2-x/y, --corner-w/h per centrare i crop sulle tue carte.")

if __name__ == "__main__":
    main()