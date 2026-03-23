# Windows Installation & Setup Guide

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Windows | 10 / 11 | 64-bit required |
| Python | 3.9 – 3.12 | Download from python.org |
| Tesseract OCR | 4.x or 5.x | UB Mannheim installer recommended |
| Visual C++ Build Tools | 2019 or later | Required by OpenCV wheel |
| Git | Any recent | Optional – you can download a ZIP instead |

---

## Step 1 – Install Python

1. Download the latest Python 3.11 installer from <https://www.python.org/downloads/windows/>.
2. Run the installer. **Tick "Add Python to PATH"** before clicking Install Now.
3. Verify the installation:

```cmd
python --version
pip --version
```

---

## Step 2 – Install Visual C++ Build Tools

Some dependencies (notably `opencv-python`) require a C++ compiler.

1. Download **Build Tools for Visual Studio** from
   <https://visualstudio.microsoft.com/visual-cpp-build-tools/>.
2. In the installer, select the **"C++ build tools"** workload and click Install.

> **Tip:** If you already have Visual Studio 2019/2022 installed you can skip this step.

---

## Step 3 – Download the Repository

**Option A – Git:**

```cmd
git clone https://github.com/chapo92/live.git
cd live
```

**Option B – ZIP:**

1. Open <https://github.com/chapo92/live> in your browser.
2. Click **Code → Download ZIP**.
3. Extract the archive and `cd` into the extracted folder.

---

## Step 4 – Install Python Dependencies

```cmd
pip install -r requirements.txt
```

This installs: `mss`, `opencv-python`, `pytesseract`, `easyocr`, `sqlalchemy`, `rich`,
`psutil`, and the rest of the stack listed in `requirements.txt`.

---

## Step 5 – Install Tesseract OCR

1. Download the UB Mannheim installer from
   <https://github.com/UB-Mannheim/tesseract/wiki>.  
   Use the **64-bit** installer (e.g. `tesseract-ocr-w64-setup-5.x.x.exe`).
2. During installation, note the path – by default:  
   `C:\Program Files\Tesseract-OCR\tesseract.exe`
3. Verify from a new Command Prompt:

```cmd
tesseract --version
```

---

## Step 6 – Configure Paths

Open `config.json` (create it if it does not exist) and set the Tesseract path:

```json
{
  "ocr": {
    "tesseract_path": "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
  }
}
```

Alternatively, add Tesseract to your system `PATH`:

1. Open **System Properties → Advanced → Environment Variables**.
2. Under **System variables**, select `Path` and click **Edit**.
3. Add `C:\Program Files\Tesseract-OCR`.

---

## Step 7 – Run Calibration (Recommended)

Open 888 Poker so a table is visible on screen, then run:

```cmd
python main.py --calibrate
```

Follow the on-screen prompts to teach the system your table's exact blue colour and the
correct screen region.

---

## Step 8 – Start Capturing

```cmd
python main.py
```

A Rich terminal dashboard appears. Press `Ctrl+C` to stop gracefully.

### Useful flags

| Flag | Description |
|---|---|
| `--fps 5` | Target frame rate |
| `--region 0,0,1920,1080` | Capture region (left,top,width,height) |
| `--db my_session.db` | Custom database path |
| `--debug` | Verbose logging |

---

## Windows-Specific Troubleshooting

### "pip is not recognised"

Python was not added to `PATH`. Re-run the Python installer, choose **Modify**, and tick
**Add Python to environment variables**.

### "DLL load failed" when importing OpenCV

Install the Visual C++ Redistributable from Microsoft:
<https://aka.ms/vs/17/release/vc_redist.x64.exe>

### "Tesseract is not installed or not in your PATH"

Set `ocr.tesseract_path` in `config.json` (see Step 6).

### Screen capture returns a black image

888 Poker uses hardware acceleration. Try:

1. Right-click the 888 Poker shortcut → Properties → Compatibility.
2. Tick **Disable fullscreen optimisations**.
3. Add the flag `--override-use-software-gl-for-tests` if available.

Alternatively, run the game in **windowed mode**.

### Antivirus blocks the script

Add the project folder to your antivirus exclusions. Screen-capture libraries legitimately
access display memory, which some heuristic engines flag.

---

## Updating

```cmd
git pull
pip install -r requirements.txt --upgrade
```
