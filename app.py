\
from __future__ import annotations

import time
import threading
import traceback
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox, Canvas
from PIL import Image, ImageTk

from ocr_core import OCRConfig, run_ocr, export_txt, export_csv, export_overlay_png


class ZoomPanCanvas(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.canvas = Canvas(self, highlightthickness=0, bg="#1e1e1e")
        self.canvas.pack(expand=True, fill="both")

        self._img_pil: Image.Image | None = None
        self._img_tk: ImageTk.PhotoImage | None = None
        self._img_id = None

        self._scale = 1.0
        self._min_scale = 0.15
        self._max_scale = 8.0

        self._pan_start = None  # (x, y)
        self._offset = [0.0, 0.0]   # (dx, dy)

        self.canvas.bind("<ButtonPress-1>", self._on_pan_start)
        self.canvas.bind("<B1-Motion>", self._on_pan_move)
        self.canvas.bind("<Double-Button-1>", self.reset_view)

        # Windows wheel
        self.canvas.bind("<MouseWheel>", self._on_wheel_windows)
        # Linux wheel
        self.canvas.bind("<Button-4>", self._on_wheel_linux)
        self.canvas.bind("<Button-5>", self._on_wheel_linux)

        self.canvas.bind("<Configure>", lambda e: self._redraw())

    def set_image(self, pil_img: Image.Image):
        self._img_pil = pil_img.convert("RGB")
        self._scale = 1.0
        self._offset = [0.0, 0.0]
        self._redraw(fit=True)

    def clear(self):
        self._img_pil = None
        self._img_tk = None
        if self._img_id is not None:
            self.canvas.delete(self._img_id)
            self._img_id = None

    def reset_view(self, event=None):
        self._scale = 1.0
        self._offset = [0.0, 0.0]
        self._redraw(fit=True)

    def _on_pan_start(self, event):
        self._pan_start = (event.x, event.y)

    def _on_pan_move(self, event):
        if self._pan_start is None:
            return
        x0, y0 = self._pan_start
        dx = event.x - x0
        dy = event.y - y0
        self._offset[0] += dx
        self._offset[1] += dy
        self._pan_start = (event.x, event.y)
        self._redraw()

    def _on_wheel_windows(self, event):
        if event.delta > 0:
            self._zoom(1.12, event.x, event.y)
        else:
            self._zoom(1/1.12, event.x, event.y)

    def _on_wheel_linux(self, event):
        if event.num == 4:
            self._zoom(1.12, event.x, event.y)
        elif event.num == 5:
            self._zoom(1/1.12, event.x, event.y)

    def _zoom(self, factor: float, cx: int, cy: int):
        old = self._scale
        new = max(self._min_scale, min(self._max_scale, old * factor))
        if abs(new - old) < 1e-6:
            return

        # zoom around cursor (keep point under cursor stable)
        self._offset[0] = cx - (cx - self._offset[0]) * (new / old)
        self._offset[1] = cy - (cy - self._offset[1]) * (new / old)
        self._scale = new
        self._redraw()

    def _redraw(self, fit: bool = False):
        if self._img_pil is None:
            return

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())

        iw, ih = self._img_pil.size

        if fit:
            s = min(cw / iw, ch / ih, 1.0)
            self._scale = max(self._min_scale, min(self._max_scale, s))
            dw = iw * self._scale
            dh = ih * self._scale
            self._offset = [(cw - dw) / 2.0, (ch - dh) / 2.0]

        nw = max(1, int(iw * self._scale))
        nh = max(1, int(ih * self._scale))
        resized = self._img_pil.resize((nw, nh), Image.BICUBIC)

        self._img_tk = ImageTk.PhotoImage(resized)

        x = self._offset[0]
        y = self._offset[1]

        if self._img_id is None:
            self._img_id = self.canvas.create_image(x, y, anchor="nw", image=self._img_tk)
        else:
            self.canvas.coords(self._img_id, x, y)
            self.canvas.itemconfig(self._img_id, image=self._img_tk)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EasyOCR Screenshot GUI (EN, Offline) — One-page + Zoom")
        self.geometry("1250x800")
        self.minsize(1150, 720)

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.image_path: Path | None = None
        self.last_overlay_bgr = None
        self.last_lines: list[str] | None = None
        self._orig_pil: Image.Image | None = None
        self._overlay_pil: Image.Image | None = None

        self._running = False
        self._t0 = 0.0

        root = ctk.CTkFrame(self)
        root.pack(expand=True, fill="both", padx=12, pady=12)

        header = ctk.CTkFrame(root)
        header.pack(fill="x", padx=10, pady=(10, 8))

        self.btn_pick = ctk.CTkButton(header, text="Choose Image", command=self.pick_image, width=140)
        self.btn_pick.pack(side="left", padx=(10, 8), pady=10)

        self.lbl_img = ctk.CTkLabel(header, text="No image selected", anchor="w")
        self.lbl_img.pack(side="left", expand=True, fill="x", padx=(0, 10))

        self.btn_export_txt = ctk.CTkButton(header, text="Export TXT", command=self.export_txt_file, state="disabled", width=110)
        self.btn_export_txt.pack(side="right", padx=(8, 10), pady=10)

        self.btn_export_csv = ctk.CTkButton(header, text="Export CSV", command=self.export_csv_file, state="disabled", width=110)
        self.btn_export_csv.pack(side="right", padx=8, pady=10)

        self.btn_export_overlay = ctk.CTkButton(header, text="Export Overlay PNG", command=self.export_overlay, state="disabled", width=160)
        self.btn_export_overlay.pack(side="right", padx=8, pady=10)

        sumrow = ctk.CTkFrame(root)
        sumrow.pack(fill="x", padx=10, pady=(0, 10))
        self.lbl_summary = ctk.CTkLabel(sumrow, text="Theme: -  |  Words: -  |  Lines: -  |  Avg conf: -", anchor="w")
        self.lbl_summary.pack(side="left", fill="x", expand=True, padx=10, pady=8)

        self.lbl_time = ctk.CTkLabel(sumrow, text="Time: 0.00s", width=120, anchor="e")
        self.lbl_time.pack(side="right", padx=(0, 8), pady=8)

        self.progress = ctk.CTkProgressBar(sumrow, mode="indeterminate", width=220)
        self.progress.pack(side="right", padx=(0, 10), pady=8)
        self.progress.stop()
        self.progress.pack_forget()

        main = ctk.CTkFrame(root)
        main.pack(expand=True, fill="both", padx=10, pady=(0, 10))
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        left_top = ctk.CTkFrame(left)
        left_top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 8))
        ctk.CTkLabel(left_top, text="Preview", font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")

        self.preview_mode = ctk.StringVar(value="Original")
        self.preview_toggle = ctk.CTkSegmentedButton(
            left_top, values=["Original", "Overlay"], command=self.on_preview_toggle, variable=self.preview_mode
        )
        self.preview_toggle.pack(side="right")

        self.preview = ZoomPanCanvas(left)
        self.preview.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        right = ctk.CTkFrame(main)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        right_top = ctk.CTkFrame(right)
        right_top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 8))
        right_top.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(right_top, text="Extracted Text (editor-like order)", font=ctk.CTkFont(size=15, weight="bold")).grid(row=0, column=0, sticky="w")
        self.btn_run = ctk.CTkButton(right_top, text="Run OCR", command=self.run_clicked, width=120)
        self.btn_run.grid(row=0, column=1, sticky="e")

        self.textbox = ctk.CTkTextbox(right, wrap="none")
        self.textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        footer = ctk.CTkFrame(root)
        footer.pack(fill="x", padx=10, pady=(0, 10))

        self.status = ctk.CTkLabel(footer, text="Status: Idle", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=10, pady=8)

        self.allowlist_var = ctk.BooleanVar(value=True)
        self.chk_allow = ctk.CTkCheckBox(footer, text="Code allowlist", variable=self.allowlist_var)
        self.chk_allow.pack(side="right", padx=(0, 10))

        ctk.CTkLabel(footer, text="Min conf").pack(side="right", padx=(0, 6))
        self.minconf_entry = ctk.CTkEntry(footer, width=70)
        self.minconf_entry.insert(0, "0.20")
        self.minconf_entry.pack(side="right", padx=(0, 12))

        ctk.CTkLabel(footer, text="Scale").pack(side="right", padx=(0, 6))
        self.scale_entry = ctk.CTkEntry(footer, width=70)
        self.scale_entry.insert(0, "2.5")
        self.scale_entry.pack(side="right", padx=(0, 18))

    def _set_export_buttons(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.btn_export_overlay.configure(state=state)
        self.btn_export_txt.configure(state=state)
        self.btn_export_csv.configure(state=state)

    def pick_image(self):
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff"), ("All files", "*.*")]
        )
        if not path:
            return

        self.image_path = Path(path)
        self.lbl_img.configure(text=str(self.image_path))

        self.last_overlay_bgr = None
        self.last_lines = None
        self._overlay_pil = None

        self._orig_pil = Image.open(self.image_path).convert("RGB")
        self.preview_toggle.set("Original")
        self.preview.set_image(self._orig_pil)

        self.textbox.delete("1.0", "end")
        self._set_export_buttons(False)
        self.lbl_summary.configure(text="Theme: -  |  Words: -  |  Lines: -  |  Avg conf: -")
        self.status.configure(text="Status: Ready (image loaded)")

    def on_preview_toggle(self, value: str):
        if value == "Original":
            if self._orig_pil is not None:
                self.preview.set_image(self._orig_pil)
            else:
                self.preview.clear()
        else:
            if self._overlay_pil is not None:
                self.preview.set_image(self._overlay_pil)
            else:
                messagebox.showinfo("Overlay not ready", "Run OCR first to generate overlay.")
                self.preview_toggle.set("Original")
                if self._orig_pil is not None:
                    self.preview.set_image(self._orig_pil)

    def _start_loading(self):
        self._running = True
        self._t0 = time.perf_counter()
        self.lbl_time.configure(text="Time: 0.00s")
        self.progress.pack(side="right", padx=(0, 10), pady=8)
        self.progress.start()
        self._tick_timer()

    def _stop_loading(self):
        self._running = False
        self.progress.stop()
        self.progress.pack_forget()

    def _tick_timer(self):
        if not self._running:
            return
        dt = time.perf_counter() - self._t0
        self.lbl_time.configure(text=f"Time: {dt:.2f}s")
        self.after(100, self._tick_timer)

    def run_clicked(self):
        if self.image_path is None:
            messagebox.showwarning("No image", "Please choose an image first.")
            return

        try:
            scale = float(self.scale_entry.get().strip())
            min_conf = float(self.minconf_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Invalid settings", "Scale and Min conf must be numbers.")
            return

        self.status.configure(text="Status: Running OCR...")
        self.btn_run.configure(state="disabled")
        self._set_export_buttons(False)
        self._start_loading()

        cfg = OCRConfig(
            lang="en",
            gpu=False,
            scale=scale,
            min_conf=min_conf,
            use_allowlist=bool(self.allowlist_var.get()),
        )

        def worker():
            try:
                out = run_ocr(self.image_path, cfg)

                lines = out["lines"]
                theme = out["theme"]
                results = out["results"]
                overlay_bgr = out["overlay_bgr"]

                word_count = len(results)
                avg_conf = (sum([r[2] for r in results]) / word_count) if word_count else 0.0
                line_count = len(lines)

                self.last_lines = lines
                self.last_overlay_bgr = overlay_bgr

                import cv2
                rgb = cv2.cvtColor(overlay_bgr, cv2.COLOR_BGR2RGB)
                self._overlay_pil = Image.fromarray(rgb)

                def ui_update():
                    self._stop_loading()
                    self.textbox.delete("1.0", "end")
                    self.textbox.insert("1.0", "\n".join(lines))
                    self.lbl_summary.configure(
                        text=f"Theme: {theme}  |  Words: {word_count}  |  Lines: {line_count}  |  Avg conf: {avg_conf:.2f}"
                    )
                    self.status.configure(text="Status: Done")
                    self.btn_run.configure(state="normal")
                    self._set_export_buttons(True)

                    self.preview_toggle.set("Overlay")
                    self.preview.set_image(self._overlay_pil)

                self.after(0, ui_update)

            except Exception:
                err = traceback.format_exc()

                def ui_err():
                    self._stop_loading()
                    self.status.configure(text="Status: Error")
                    self.btn_run.configure(state="normal")
                    messagebox.showerror("Error", err)

                self.after(0, ui_err)

        threading.Thread(target=worker, daemon=True).start()

    def export_overlay(self):
        if self.last_overlay_bgr is None or self.image_path is None:
            return
        default_name = f"{self.image_path.stem}_overlay.png"
        path = filedialog.asksaveasfilename(
            title="Save overlay PNG",
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[("PNG", "*.png")]
        )
        if not path:
            return
        export_overlay_png(path, self.last_overlay_bgr)
        self.status.configure(text=f"Status: Saved overlay PNG -> {Path(path).name}")

    def export_txt_file(self):
        if not self.last_lines or self.image_path is None:
            return
        default_name = f"{self.image_path.stem}.txt"
        path = filedialog.asksaveasfilename(
            title="Save TXT",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Text", "*.txt")]
        )
        if not path:
            return
        export_txt(path, self.last_lines)
        self.status.configure(text=f"Status: Saved TXT -> {Path(path).name}")

    def export_csv_file(self):
        if not self.last_lines or self.image_path is None:
            return
        default_name = f"{self.image_path.stem}.csv"
        path = filedialog.asksaveasfilename(
            title="Save CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV", "*.csv")]
        )
        if not path:
            return
        export_csv(path, self.last_lines)
        self.status.configure(text=f"Status: Saved CSV -> {Path(path).name}")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
