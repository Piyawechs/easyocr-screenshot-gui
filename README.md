# EasyOCR Screenshot GUI v0.4 (One-page + Zoom + Loading + Timer)

## Features
- One-page layout (balanced): Preview left + Text right
- Preview toggle: Original / Overlay
- Preview supports **zoom (mouse wheel)** + **pan (drag)**
- Loading bar (indeterminate) while OCR is running
- Shows OCR runtime (seconds)
- Export: Overlay PNG / TXT / CSV

## Run (uv)
```bash
uv venv
uv sync
uv run python app.py
```

## Controls
- Zoom: Mouse wheel on preview
- Pan: Left mouse drag on preview
- Reset view: Double click on preview
