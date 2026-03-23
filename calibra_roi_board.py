import cv2

# Carica l'immagine originale (deve essere a dimensione piena, NESSUN RESIZE)
img = cv2.imread("frame_board_full.png")
coords = []

def click_event(event, x, y, flags, param):
    global coords, img
    if event == cv2.EVENT_LBUTTONDOWN:
        coords.append((x, y))
        print(f"Board {len(coords)}: x={x}, y={y}")
        # Disegna un rettangolo d'esempio (puoi variare la dimensione)
        w, h = 45, 65
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.imshow("Clicca sopra a sinistra di ogni carta board", img)

cv2.imshow("Clicca sopra a sinistra di ogni carta board", img)
cv2.setMouseCallback("Clicca sopra a sinistra di ogni carta board", click_event)

print("Clicca col mouse sull’ANGOLO in alto a sinistra di OGNI carta board (da sinistra a destra). Premi ESC per chiudere.")
while True:
    key = cv2.waitKey(1)
    if key == 27 or len(coords) >= 5:
        break

cv2.destroyAllWindows()

print("\nCoordinate raccolte (incollale in BOARD_CORNERS):")
print("BOARD_CORNERS = [")
for c in coords:
    print(f"    ({c[0]}, {c[1]}, 45, 65),")
print("]")

# Salva in un file pronto per il copia-incolla
with open('coordinate_board_pronte.txt', 'w') as f:
    f.write("BOARD_CORNERS = [\n")
    for c in coords:
        f.write(f"    ({c[0]}, {c[1]}, 45, 65),\n")
    f.write("]\n")
print('\nCoordinate salvate su "coordinate_board_pronte.txt"!')