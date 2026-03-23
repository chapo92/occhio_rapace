import cv2

# Carica l'immagine di riferimento
img = cv2.imread("frame_board_full.png")

# Coordinate ROI definite con lo script di calibrazione
BOARD_CORNERS = [
    (929, 519, 45, 65),
    (1060, 520, 45, 65),
    (1192, 522, 45, 65),
    (1322, 523, 45, 65),
    (1452, 523, 45, 65),
]

# Croppa e salva le immagini delle carte board
for idx, (x, y, w, h) in enumerate(BOARD_CORNERS, start=1):
    crop = img[y:y+h, x:x+w]
    outname = f"board_card_{idx}.png"
    cv2.imwrite(outname, crop)
    print(f"Salvato: {outname}")