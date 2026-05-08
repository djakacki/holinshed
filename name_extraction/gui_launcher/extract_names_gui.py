#!/usr/bin/env python3
"""
Small GUI launcher for name_extraction/extract_names.py.

Lets a user select:
- an authority list CSV
- an XML file to parse

Remembers the last used files and runs extraction without needing CLI args.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

LAUNCHER_DIR = Path(__file__).resolve().parent
NAME_EXTRACTION_DIR = LAUNCHER_DIR.parent
sys.path.insert(0, str(NAME_EXTRACTION_DIR))

from extract_names import REPO_ROOT, SCRIPT_DIR, run_extraction

STATE_FILE = LAUNCHER_DIR / "extract_names_gui_state.json"
DEFAULT_AUTHORITY = SCRIPT_DIR / "holinshed_disambiguated.csv"


class ExtractNamesLauncher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Holinshed Name Extraction")
        self.root.resizable(True, False)
        self.root.geometry("1100x240")
        self.root.minsize(900, 220)

        self.result_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.authority_var = tk.StringVar()
        self.xml_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select an authority CSV and an XML file.")

        self._build_ui()
        self._load_state()
        self.root.after(150, self._poll_worker)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Authority list CSV").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        ttk.Entry(frame, textvariable=self.authority_var, width=70).grid(row=0, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(frame, text="Browse...", command=self._browse_authority).grid(row=0, column=2, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="XML file").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        ttk.Entry(frame, textvariable=self.xml_var, width=70).grid(row=1, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(frame, text="Browse...", command=self._browse_xml).grid(row=1, column=2, sticky="ew", pady=(0, 8))

        self.run_button = ttk.Button(frame, text="Run Extraction", command=self._start_run)
        self.run_button.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 8))

        status = ttk.Label(
            frame,
            textvariable=self.status_var,
            relief="sunken",
            anchor="w",
            justify="left",
            wraplength=700,
        )
        status.grid(row=3, column=0, columnspan=3, sticky="ew")

    def _load_state(self) -> None:
        self.authority_var.set(str(DEFAULT_AUTHORITY))
        self.xml_var.set("")

        if not STATE_FILE.exists():
            return

        try:
            with open(STATE_FILE, encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, json.JSONDecodeError):
            self.status_var.set("State file could not be read. Using default paths.")
            return

        self.authority_var.set(state.get("authority_csv", str(DEFAULT_AUTHORITY)))
        self.xml_var.set(state.get("xml_file", ""))

        missing = []
        for label, raw in [("authority CSV", self.authority_var.get()), ("XML file", self.xml_var.get())]:
            if raw and not Path(raw).expanduser().exists():
                missing.append(label)
        if missing:
            self.status_var.set(f"Saved {' and '.join(missing)} not found. Update the selection before running.")

    def _save_state(self) -> None:
        payload = {
            "authority_csv": self.authority_var.get(),
            "xml_file": self.xml_var.get(),
        }
        with open(STATE_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def _browse_authority(self) -> None:
        start_dir = Path(self.authority_var.get()).expanduser().parent if self.authority_var.get() else SCRIPT_DIR
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Select authority list CSV",
            initialdir=str(start_dir),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if filename:
            self.authority_var.set(filename)
            self.status_var.set("Authority CSV selected.")

    def _browse_xml(self) -> None:
        start_dir = Path(self.xml_var.get()).expanduser().parent if self.xml_var.get() else REPO_ROOT
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Select XML file",
            initialdir=str(start_dir),
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")],
        )
        if filename:
            self.xml_var.set(filename)
            self.status_var.set("XML file selected.")

    def _start_run(self) -> None:
        authority = Path(self.authority_var.get()).expanduser()
        xml_file = Path(self.xml_var.get()).expanduser()

        if not self.authority_var.get().strip():
            self.status_var.set("Choose an authority CSV first.")
            return
        if not self.xml_var.get().strip():
            self.status_var.set("Choose an XML file first.")
            return
        if not authority.exists():
            self.status_var.set(f"Authority CSV not found: {authority}")
            return
        if not xml_file.exists():
            self.status_var.set(f"XML file not found: {xml_file}")
            return
        if self.worker and self.worker.is_alive():
            self.status_var.set("Extraction is already running.")
            return

        self.run_button.configure(state="disabled")
        self.status_var.set("Running extraction...")
        self.worker = threading.Thread(target=self._run_worker, args=(xml_file, authority), daemon=True)
        self.worker.start()

    def _run_worker(self, xml_file: Path, authority: Path) -> None:
        try:
            output = run_extraction(xml_file, authority)
        except Exception as exc:
            self.result_queue.put(("error", str(exc)))
            return
        self.result_queue.put(("success", str(output)))

    def _poll_worker(self) -> None:
        try:
            status, message = self.result_queue.get_nowait()
        except queue.Empty:
            self.root.after(150, self._poll_worker)
            return

        self.run_button.configure(state="normal")
        if status == "success":
            self._save_state()
            self.status_var.set(f"Extraction complete. Output written to: {message}")
        else:
            self.status_var.set(f"Extraction failed: {message}")
        self.root.after(150, self._poll_worker)


def main() -> int:
    root = tk.Tk()
    ExtractNamesLauncher(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
