# Linux Installation & Setup Guide

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Ubuntu / Debian | 20.04+ / Bookworm+ | Other distros work with minor adjustments |
| Python | 3.9 – 3.12 | Usually pre-installed; use `python3` |
| Tesseract OCR | 4.x or 5.x | Available via `apt` |
| libgl / libglib | Any | Required by OpenCV |

---

## Step 1 – Update Package Lists

```bash
sudo apt update && sudo apt upgrade -y
```

---

## Step 2 – Install System Dependencies

```bash
sudo apt install -y \
    python3 python3-pip python3-venv \
    tesseract-ocr tesseract-ocr-eng \
    libgl1 libglib2.0-0 \
    libsm6 libxext6 libxrender-dev \
    git
```

Verify Tesseract:

```bash
tesseract --version
```

---

## Step 3 – Download the Repository

```bash
git clone https://github.com/chapo92/live.git
cd live
```

---

## Step 4 – Create a Virtual Environment (Recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## Step 5 – Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Step 6 – Configure Tesseract Path

On most Linux systems, Tesseract is installed at `/usr/bin/tesseract` which is already on
`PATH`, so no extra configuration is needed.

If your installation is in a non-standard location, set it in `config.json`:

```json
{
  "ocr": {
    "tesseract_path": "/usr/local/bin/tesseract"
  }
}
```

---

## Step 7 – Screen Capture on Linux

`mss` (the default backend) works with **X11**. On **Wayland** you may need additional
packages or to fall back to an X11 session:

```bash
# Check your session type
echo $XDG_SESSION_TYPE
```

If the output is `wayland`, log out and choose an **Ubuntu on Xorg** session from the login
screen, or install `xdg-desktop-portal-gnome` and configure the portal backend.

---

## Step 8 – Run Calibration (Recommended)

```bash
python3 main.py --calibrate
```

Follow the prompts with 888 Poker open and a table visible.

---

## Step 9 – Start Capturing

```bash
python3 main.py
```

Press `Ctrl+C` to stop gracefully.

### Useful flags

| Flag | Description |
|---|---|
| `--fps 5` | Target frame rate |
| `--region 0,0,1920,1080` | Capture region (left,top,width,height) |
| `--db my_session.db` | Custom database path |
| `--debug` | Verbose logging |

---

## Running as a Systemd Service (Optional)

Create `/etc/systemd/system/occhi-di-falco.service`:

```ini
[Unit]
Description=Occhi di Falco – 888 Poker Data Extractor
After=graphical-session.target

[Service]
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/live
ExecStart=/home/YOUR_USERNAME/live/.venv/bin/python main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

Enable and start:

```bash
systemctl --user enable occhi-di-falco
systemctl --user start occhi-di-falco
```

---

## Linux-Specific Troubleshooting

### "No module named 'cv2'"

```bash
pip install opencv-python-headless
```

### "Cannot connect to X server"

Make sure you are running inside a graphical session (not SSH without X forwarding).
For remote access with X forwarding use `ssh -X`.

### "mss: Cannot get resolution"

On headless servers, install a virtual framebuffer:

```bash
sudo apt install -y xvfb
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 &
python3 main.py
```

### Low OCR accuracy on HiDPI screens

Set your display scale to 100 % in **Settings → Displays** or pass the exact pixel
dimensions via `--region`.

---

## Updating

```bash
git pull
pip install -r requirements.txt --upgrade
```
