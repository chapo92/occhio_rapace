import cv2
import os
import json
from pathlib import Path
import subprocess

# ========== CONFIGURAZIONE ==========
VIDEO_PATH = "pokere_1980.mp4"
FRAMES_DIR = Path("frames_auto")
ROI_DIR = Path("cropped_auto")
RANKS_DIR = Path("card_templates/ranks")
SUITS_DIR = Path("card_templates/suits")
RESULTS_JSON = "video_cards_test_results.json"

FRAME_RATE = 5    # Estrai 1 frame ogni 5

# ROI delle 5 carte board (PERSONALIZZA!)
BOARD_CORNERS = [
    (710, 440, 64, 64),
    (835, 440, 64, 64),
    (960, 440, 64, 64),
    (1085, 440, 64, 64),
    (1210, 440, 64, 64),
]
# ROI delle tue due carte personali (PERSONALIZZA coordinata se serve)
PLAYER_CARDS = [
    (1110, 610, 40, 40),
    (1180, 610, 40, 40),
]

# ========== STEP 1: ESTRARRE I FRAME ==========
FRAMES_DIR.mkdir(exist_ok=True)
if not any(FRAMES_DIR.glob("*.jpg")):
    print("🔄 Estrazione frame dal video...")
    cmd = [
        "ffmpeg", "-i", VIDEO_PATH, "-vf",
        f"select=not(mod(n\\,{FRAME_RATE}))", "-vsync", "vfr",
        "-qscale:v", "2",
        str(FRAMES_DIR / "frame_%05d.jpg")
    ]
    subprocess.run(cmd, check=True)
    print(f"✅ Estratti i frame in '{FRAMES_DIR}'")
else:
    print(f"✅ Frame già presenti in '{FRAMES_DIR}', salto estrazione.")

# ========== STEP 2: CROP ROI SU OGNI FRAME ==========
ROI_DIR.mkdir(exist_ok=True)
print("🔄 Cropping ROI board e tue carte...")
for frame_path in sorted(FRAMES_DIR.glob("*.jpg")):
    img = cv2.imread(str(frame_path))
    # Board
    for i, (x, y, w, h) in enumerate(BOARD_CORNERS, 1):
        crop = img[y:y+h, x:x+w]
        out_path = ROI_DIR / f"{frame_path.stem}_board_{i}.jpg"
        cv2.imwrite(str(out_path), crop)
    # Player
    for j, (x, y, w, h) in enumerate(PLAYER_CARDS, 1):
        crop = img[y:y+h, x:x+w]
        out_path = ROI_DIR / f"{frame_path.stem}_mycard_{j}.jpg"
        cv2.imwrite(str(out_path), crop)
print("✅ Cropping completato.")

# ========== FUNZIONI DI MATCHING ==========
def match_templates(input_img, templates_dir):
    best_match = None
    best_score = -1
    for tpl_path in templates_dir.glob("*.png"):
        template = cv2.imread(str(tpl_path), 0)
        if (
            template is None or
            input_img is None or
            input_img.shape[0] < template.shape[0] or
            input_img.shape[1] < template.shape[1]
        ):
            continue
        res = cv2.matchTemplate(input_img, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, _ = cv2.minMaxLoc(res)
        if score > best_score:
            best_score = score
            best_match = tpl_path.stem
    return best_match, float(best_score)

def crop_rank(img):
    # Croppa la parte ALTA della ROI (es: top 55%)
    h = img.shape[0]
    return img[0:int(h*0.55), :]

def crop_suit(img):
    # Croppa la parte BASSA della ROI (es: bottom 45%)
    h = img.shape[0]
    return img[int(h*0.55):, :]

# ========== STEP 3: MATCHING TEMPLATE RANK + SUIT SU TUTTE LE ROI ==========
print("🔎 Matching rank & suit (con crop specifici)...")
results = {}

for roi_img in sorted(ROI_DIR.glob("*.jpg")):
    full_img = cv2.imread(str(roi_img), 0)
    if full_img is None or min(full_img.shape) < 10:
        # Immagini vuote o corrotte, saltale
        results[roi_img.name] = {
            "rank": None, "rank_score": None, "suit": None, "suit_score": None
        }
        continue
    # Cropping zone
    img_rank = crop_rank(full_img)
    img_suit = crop_suit(full_img)
    # Match rank e suit SOLO nelle loro zone dedicate
    best_rank, rank_score = match_templates(img_rank, RANKS_DIR)
    best_suit, suit_score = match_templates(img_suit, SUITS_DIR)
    results[roi_img.name] = {
        "rank": best_rank,
        "rank_score": rank_score,
        "suit": best_suit,
        "suit_score": suit_score
    }

print("✅ Matching completato.")

# ========== STEP 4: SALVATAGGIO E RIEPILOGO ==========
with open(RESULTS_JSON, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"✅ Risultati salvati in '{RESULTS_JSON}'")

# Riepilogo
from collections import Counter
rank_counter = Counter([v['rank'] for v in results.values() if v['rank']])
suit_counter = Counter([v['suit'] for v in results.values() if v['suit']])

print("\n===== RIEPILOGO RANKS RICONOSCIUTI =====")
for rank, count in rank_counter.most_common():
    print(f"{rank}: {count}")
print("\n===== RIEPILOGO SUITS RICONOSCIUTI =====")
for suit, count in suit_counter.most_common():
    print(f"{suit}: {count}")

print("\n✅ PIPELINE COMPLETATA!")