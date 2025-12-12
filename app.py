
from __future__ import annotations

import time
import threading
import traceback
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image ,ImageTk

from ocr_core import OCRConfig, run_ocr, export_txt, export_csv, export_overlay_png


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EasyOCR Screenshot GUI (EN, Offline) — One-page Output")
        self.geometry("1200x760")
        self.minsize(1100, 700)

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.image_path: Path | None = None
        self.last_overlay_bgr = None
        self.last_lines: list[str] | None = None
        self._orig_preview_path: Path | None = None
        self._overlay_preview_path: Path | None = None

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

        summary = ctk.CTkFrame(root)
        summary.pack(fill="x", padx=10, pady=(0, 10))
        self.lbl_summary = ctk.CTkLabel(summary, text="Theme: -  |  Words: -  |  Lines: -  |  Avg conf: -", anchor="w")
        self.lbl_summary.pack(side="left", fill="x", expand=True, padx=10, pady=8)

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
            left_top,
            values=["Original", "Overlay"],
            command=self.on_preview_toggle,
            variable=self.preview_mode,
        )
        self.preview_toggle.pack(side="right")

        self.preview_label = ctk.CTkLabel(left, text="(Select an image to preview)")
        self.preview_label.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self._preview_ctk = None

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

    def _fit_image(self, pil_img: Image.Image, max_w: int, max_h: int) -> Image.Image:
        w, h = pil_img.size
        scale = min(max_w / w, max_h / h, 1.0)
        nw, nh = int(w * scale), int(h * scale)
        return pil_img.resize((max(nw, 1), max(nh, 1)))

    def _show_preview_path(self, path: Path):
        pil = Image.open(path).convert("RGB")

        max_w, max_h = 560, 520
        w, h = pil.size
        scale = min(max_w / w, max_h / h, 1.0)
        pil = pil.resize((max(1, int(w * scale)), max(1, int(h * scale))))

        photo = ImageTk.PhotoImage(pil)

        # IMPORTANT: keep references so Tk doesn't destroy it
        self._preview_photo = photo
        self.preview_label.configure(text="", image=photo)
        self.preview_label.image = photo

    def on_preview_toggle(self, value: str):
        if value == "Original":
            if self._orig_preview_path and self._orig_preview_path.exists():
                self._show_preview_path(self._orig_preview_path)
            else:
                self.preview_label.configure(text="(Select an image to preview)", image=None)
        else:
            if self._overlay_preview_path and self._overlay_preview_path.exists():
                self._show_preview_path(self._overlay_preview_path)
            else:
                self.preview_label.configure(text="(Run OCR to preview overlay)", image=None)

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
        self._overlay_preview_path = None

        self._orig_preview_path = self.image_path
        self.preview_toggle.set("Original")
        self._show_preview_path(self._orig_preview_path)

        self.textbox.delete("1.0", "end")
        self._set_export_buttons(False)
        self.lbl_summary.configure(text="Theme: -  |  Words: -  |  Lines: -  |  Avg conf: -")
        self.status.configure(text="Status: Ready (image loaded)")

    def _set_export_buttons(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.btn_export_overlay.configure(state=state)
        self.btn_export_txt.configure(state=state)
        self.btn_export_csv.configure(state=state)

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

        cfg = OCRConfig(
            lang="en",
            gpu=False,
            scale=scale,
            min_conf=min_conf,
            use_allowlist=bool(self.allowlist_var.get()),
        )

        def worker():
            t0 = time.time()
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

                tmp_overlay = Path.cwd() / "__overlay_preview.png"
                import cv2
                cv2.imwrite(str(tmp_overlay), overlay_bgr)
                self._overlay_preview_path = tmp_overlay

                dt = time.time() - t0

                def ui_update():
                    self.textbox.delete("1.0", "end")
                    self.textbox.insert("1.0", "\n".join(lines))
                    self.lbl_summary.configure(
                        text=f"Theme: {theme}  |  Words: {word_count}  |  Lines: {line_count}  |  Avg conf: {avg_conf:.2f}"
                    )
                    self.status.configure(text=f"Status: Done in {dt:.2f}s")
                    self.btn_run.configure(state="normal")
                    self._set_export_buttons(True)

                    self.preview_toggle.set("Overlay")
                    self.on_preview_toggle("Overlay")

                self.after(0, ui_update)
            except Exception:
                err = traceback.format_exc()

                def ui_err():
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
