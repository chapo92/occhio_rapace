import cv2
from pathlib import Path

image_path = "player_cards_frame.jpg"      # Cambia se serve
output_dir = Path("roi_out_player")
output_dir.mkdir(parents=True, exist_ok=True)

rectangles = []
drawing = False
ix, iy = -1, -1

def draw_rectangle(event, x, y, flags, param):
    global ix, iy, drawing, rectangles, img_display

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        ix, iy = x, y

    elif event == cv2.EVENT_MOUSEMOVE:
        if drawing:
            img_display = img.copy()
            cv2.rectangle(img_display, (ix, iy), (x, y), (0,255,0), 2)

    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        cv2.rectangle(img_display, (ix, iy), (x, y), (0,255,0), 2)
        rectangles.append((min(ix, x), min(iy, y), abs(x - ix), abs(y - iy)))

img = cv2.imread(image_path)
if img is None:
    raise SystemExit(f"Image not found: {image_path}")

img_display = img.copy()
cv2.namedWindow('Draw two rectangles (1 per card), then press ENTER')
cv2.setMouseCallback('Draw two rectangles (1 per card), then press ENTER', draw_rectangle)

print("Disegna due rettangoli sulle tue carte (uno per carta). PREMI ENTER quando hai finito.")
while True:
    cv2.imshow('Draw two rectangles (1 per card), then press ENTER', img_display)
    key = cv2.waitKey(1) & 0xFF
    if key == 13 or key == 10:  # ENTER
        break

cv2.destroyAllWindows()

if len(rectangles) != 2:
    print(f"Hai selezionato {len(rectangles)} rettangoli. Selezionane due e riprova.")
    exit(1)

for idx, (x, y, w, h) in enumerate(rectangles, 1):
    crop = img[y:y+h, x:x+w]
    filename = output_dir / f"player_card{idx}_manual_crop.jpg"
    cv2.imwrite(str(filename), crop)
    print(f"✔️ Crop {idx} salvato in {filename}")

print("Fatto! Trovi i ritagli in", output_dir)