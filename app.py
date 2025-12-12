from __future__ import annotations

import threading
import traceback
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

from ocr_core import OCRConfig, run_ocr, save_outputs


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EasyOCR Screenshot GUI (EN, Offline)")
        self.geometry("980x650")
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.image_path: Path | None = None
        self.out_dir: Path = Path("outputs")

        # Left panel
        left = ctk.CTkFrame(self)
        left.pack(side="left", fill="y", padx=12, pady=12)

        ctk.CTkLabel(left, text="Inputs", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10, pady=(10, 6))

        self.btn_pick = ctk.CTkButton(left, text="Choose Image (PNG/JPG)", command=self.pick_image)
        self.btn_pick.pack(fill="x", padx=10, pady=(0, 8))

        self.lbl_img = ctk.CTkLabel(left, text="No image selected", wraplength=280, justify="left")
        self.lbl_img.pack(fill="x", padx=10, pady=(0, 12))

        self.btn_out = ctk.CTkButton(left, text="Choose Output Folder", command=self.pick_out_dir)
        self.btn_out.pack(fill="x", padx=10, pady=(0, 8))

        self.lbl_out = ctk.CTkLabel(left, text=f"Output: {self.out_dir.resolve()}", wraplength=280, justify="left")
        self.lbl_out.pack(fill="x", padx=10, pady=(0, 16))

        ctk.CTkLabel(left, text="Settings", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10, pady=(0, 6))

        self.scale_var = ctk.DoubleVar(value=2.5)
        self.minconf_var = ctk.DoubleVar(value=0.20)
        self.allowlist_var = ctk.BooleanVar(value=True)

        ctk.CTkLabel(left, text="Scale (tiny fonts):").pack(anchor="w", padx=10)
        self.scale_slider = ctk.CTkSlider(left, from_=1.0, to=4.0, number_of_steps=30, variable=self.scale_var)
        self.scale_slider.pack(fill="x", padx=10, pady=(6, 2))
        self.scale_val = ctk.CTkLabel(left, textvariable=self.scale_var)
        self.scale_val.pack(anchor="e", padx=10, pady=(0, 10))

        ctk.CTkLabel(left, text="Min confidence (export/overlay):").pack(anchor="w", padx=10)
        self.minconf_slider = ctk.CTkSlider(left, from_=0.0, to=0.8, number_of_steps=40, variable=self.minconf_var)
        self.minconf_slider.pack(fill="x", padx=10, pady=(6, 2))
        self.minconf_val = ctk.CTkLabel(left, textvariable=self.minconf_var)
        self.minconf_val.pack(anchor="e", padx=10, pady=(0, 10))

        self.chk_allow = ctk.CTkCheckBox(left, text="Code allowlist (recommended)", variable=self.allowlist_var)
        self.chk_allow.pack(anchor="w", padx=10, pady=(0, 12))

        self.btn_run = ctk.CTkButton(left, text="Run OCR + Export", command=self.run_clicked)
        self.btn_run.pack(fill="x", padx=10, pady=(6, 10))

        self.status = ctk.CTkLabel(left, text="Status: Idle", wraplength=280, justify="left")
        self.status.pack(fill="x", padx=10, pady=(0, 10))

        # Right panel
        right = ctk.CTkFrame(self)
        right.pack(side="right", expand=True, fill="both", padx=12, pady=12)

        ctk.CTkLabel(right, text="Extracted Text (editor-like order)", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=12, pady=(12, 6)
        )

        self.textbox = ctk.CTkTextbox(right, wrap="none")
        self.textbox.pack(expand=True, fill="both", padx=12, pady=(0, 12))

    def pick_image(self):
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff"), ("All files", "*.*")]
        )
        if not path:
            return
        self.image_path = Path(path)
        self.lbl_img.configure(text=str(self.image_path))

    def pick_out_dir(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if not folder:
            return
        self.out_dir = Path(folder)
        self.lbl_out.configure(text=f"Output: {self.out_dir.resolve()}")

    def run_clicked(self):
        if self.image_path is None:
            messagebox.showwarning("No image", "Please choose an image first.")
            return

        self.status.configure(text="Status: Running OCR...")
        self.btn_run.configure(state="disabled")
        self.textbox.delete("1.0", "end")

        cfg = OCRConfig(
            lang="en",
            gpu=False,
            scale=float(self.scale_var.get()),
            min_conf=float(self.minconf_var.get()),
            use_allowlist=bool(self.allowlist_var.get()),
        )

        def worker():
            try:
                out = run_ocr(self.image_path, cfg)
                lines = out["lines"]
                theme = out["theme"]
                txt_path, overlay_path = save_outputs(self.image_path, self.out_dir, lines, out["overlay_bgr"])

                def ui_update():
                    self.textbox.insert("1.0", "\n".join(lines))
                    self.status.configure(text=f"Status: Done (theme={theme}). Saved: {txt_path.name}, {overlay_path.name}")
                    self.btn_run.configure(state="normal")

                self.after(0, ui_update)
            except Exception:
                err = traceback.format_exc()

                def ui_err():
                    self.status.configure(text="Status: Error")
                    self.btn_run.configure(state="normal")
                    messagebox.showerror("Error", err)

                self.after(0, ui_err)

        threading.Thread(target=worker, daemon=True).start()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
