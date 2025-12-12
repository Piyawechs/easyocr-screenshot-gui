\
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
import easyocr


@dataclass
class OCRConfig:
    lang: str = "en"
    gpu: bool = False
    scale: float = 2.5

    # EasyOCR knobs (tuned for screenshots)
    text_threshold: float = 0.55
    low_text: float = 0.2
    link_threshold: float = 0.35
    contrast_ths: float = 0.03
    adjust_contrast: float = 0.8

    # Output filtering
    min_conf: float = 0.20

    # Optional allowlist to reduce confusion on code/log screenshots
    use_allowlist: bool = True


DEFAULT_CODE_ALLOWLIST = r"""0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_()[]{}.,=:+-*/\\"'\\\\:;<>#@! """


def load_image(path: str | Path) -> np.ndarray:
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(f"Image not found: {path}")
    return img


def detect_theme(bgr: np.ndarray) -> str:
    """Auto-detect theme: 'dark' or 'light' from a screenshot."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    mean = float(np.mean(gray))
    std = float(np.std(gray))

    if mean < 115:
        return "dark"
    if mean > 165:
        return "light"
    return "dark" if mean < 140 and std > 45 else "light"


def _apply_clahe_bgr(bgr: np.ndarray, clip_limit: float = 2.0, tile: Tuple[int, int] = (8, 8)) -> np.ndarray:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=float(clip_limit), tileGridSize=tile)
    l2 = clahe.apply(l)
    merged = cv2.merge([l2, a, b])
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def _gamma(gray: np.ndarray, gamma: float) -> np.ndarray:
    inv = 1.0 / max(gamma, 1e-6)
    table = (np.array([(i / 255.0) ** inv * 255 for i in range(256)])).astype("uint8")
    return cv2.LUT(gray, table)


def preprocess_for_screenshot(bgr: np.ndarray, theme: str, scale: float) -> np.ndarray:
    """Preprocess screenshot for OCR. Returns GRAY image."""
    if abs(scale - 1.0) > 1e-6:
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    bgr = _apply_clahe_bgr(bgr, clip_limit=2.0)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    if theme == "dark":
        gray = _gamma(gray, gamma=1.25)

    gray = cv2.bilateralFilter(gray, 7, 50, 50)
    sharp = cv2.addWeighted(gray, 1.7, cv2.GaussianBlur(gray, (0, 0), 3), -0.7, 0)
    return sharp


def _bbox_to_rect(bbox: List[List[float]]) -> Tuple[int, int, int, int]:
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
    return x1, y1, x2, y2


def group_into_lines(results: List[Tuple[List[List[float]], str, float]], y_tol: float) -> List[str]:
    """Editor-like line ordering: top-to-bottom, left-to-right."""
    items = []
    for bbox, text, conf in results:
        x1, y1, x2, y2 = _bbox_to_rect(bbox)
        cy = 0.5 * (y1 + y2)
        items.append((y1, cy, x1, text))

    items.sort(key=lambda t: (t[0], t[2]))

    lines: List[List[Tuple[int, str]]] = []
    line_cys: List[float] = []

    for y1, cy, x1, text in items:
        placed = False
        for i, lcy in enumerate(line_cys):
            if abs(cy - lcy) <= y_tol:
                lines[i].append((x1, text))
                line_cys[i] = 0.7 * line_cys[i] + 0.3 * cy
                placed = True
                break
        if not placed:
            lines.append([(x1, text)])
            line_cys.append(cy)

    out_lines: List[str] = []
    for line in lines:
        line.sort(key=lambda t: t[0])
        out_lines.append(" ".join([t[1] for t in line]).rstrip())
    return out_lines


def draw_overlay(bgr_scaled: np.ndarray, results: List[Tuple[List[List[float]], str, float]], min_conf: float) -> np.ndarray:
    out = bgr_scaled.copy()
    for bbox, text, conf in results:
        if conf < min_conf:
            continue
        x1, y1, x2, y2 = _bbox_to_rect(bbox)
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{text} ({conf:.2f})"
        cv2.putText(out, label, (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2, cv2.LINE_AA)
    return out


def run_ocr(image_path: str | Path, cfg: OCRConfig) -> dict:
    image_path = Path(image_path)
    bgr = load_image(image_path)

    theme = detect_theme(bgr)
    prep = preprocess_for_screenshot(bgr, theme=theme, scale=cfg.scale)

    bgr_scaled = bgr
    if abs(cfg.scale - 1.0) > 1e-6:
        bgr_scaled = cv2.resize(bgr, None, fx=cfg.scale, fy=cfg.scale, interpolation=cv2.INTER_CUBIC)

    reader = easyocr.Reader([cfg.lang], gpu=cfg.gpu)

    kwargs = dict(
        detail=1,
        paragraph=False,
        text_threshold=float(cfg.text_threshold),
        low_text=float(cfg.low_text),
        link_threshold=float(cfg.link_threshold),
        contrast_ths=float(cfg.contrast_ths),
        adjust_contrast=float(cfg.adjust_contrast),
    )
    if cfg.use_allowlist:
        kwargs["allowlist"] = DEFAULT_CODE_ALLOWLIST

    results = reader.readtext(prep, **kwargs)

    filtered = [(bbox, text, float(conf)) for (bbox, text, conf) in results if float(conf) >= float(cfg.min_conf)]

    y_tol = 18.0 * max(cfg.scale / 2.5, 0.6)
    lines = group_into_lines(filtered, y_tol=float(y_tol))

    overlay = draw_overlay(bgr_scaled, filtered, min_conf=float(cfg.min_conf))

    return {
        "theme": theme,
        "lines": lines,
        "results": filtered,
        "overlay_bgr": overlay,
        "bgr_scaled": bgr_scaled,
    }


def export_txt(txt_path: str | Path, lines: List[str]) -> Path:
    txt_path = Path(txt_path)
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return txt_path


def export_csv(csv_path: str | Path, lines: List[str]) -> Path:
    import csv as _csv
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(["line_no", "text"])
        for i, line in enumerate(lines, start=1):
            w.writerow([i, line])
    return csv_path


def export_overlay_png(png_path: str | Path, overlay_bgr: np.ndarray) -> Path:
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(png_path), overlay_bgr)
    return png_path
