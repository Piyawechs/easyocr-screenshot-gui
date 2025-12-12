# EasyOCR Screenshot GUI (English-only, Offline)

This app OCRs **screenshots** (especially code editors) using **EasyOCR** on CPU, with:
- Auto **dark/light theme detection** (adjusts preprocessing + OCR thresholds)
- **Overlay** bounding boxes saved as `*_overlay.png`
- Export text as `*.txt` **ordered like an editor** (top-to-bottom, left-to-right, with line grouping)

> Offline: after installing dependencies and the EasyOCR model once, you can run with no internet.

## Setup (uv)

```bash
uv venv
uv sync
uv run python app.py
```

Or run as a script entrypoint (optional):

```bash
uv run easyocr-screenshot-gui
```

## Tips
- If your screenshot has tiny fonts: increase **Scale** in the GUI (2.5–3.5).
- If you're OCR-ing code: enable **Code allowlist** (recommended).
- If the bottom area is missed: reduce **Min confidence** to 0.10–0.20.

Outputs are written to the selected output folder:
- `<image_name>.txt`
- `<image_name>_overlay.png`
