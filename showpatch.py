"""
showpatch.py — Roland SE-02 Patch Monitor
Listens for MIDI Program Change messages and displays the current patch name.
Patch names are loaded from a CSV file matched to the connected device.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import rtmidi
import csv
import os
import sys
import threading
import time

# ── Constants ────────────────────────────────────────────────────────────────

APP_TITLE   = "ShowPatch"
WIN_W, WIN_H = 620, 300
BG          = "#111115"
SURFACE     = "#1c1c22"
SURFACE2    = "#26262f"
BORDER      = "#2e2e3a"
ACCENT      = "#e06030"
ACCENT_L    = "#ff7a44"
TEXT        = "#dddde8"
TEXT_DIM    = "#7777a0"
TEXT_XS     = "#55556a"
GREEN       = "#44cc77"
RED         = "#cc5555"

# Maps substrings in device names to CSV filenames placed next to this script.
DEVICE_CSV_MAP = {
    "se-02": "SE-02_patches.csv",
    "se02":  "SE-02_patches.csv",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))


# ── CSV helpers ──────────────────────────────────────────────────────────────

def _split_csv_line(line: str) -> list[str]:
    """Minimal CSV parser that handles quoted fields."""
    result, current, in_quotes = [], "", False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ',' and not in_quotes:
            result.append(current)
            current = ""
        else:
            current += ch
    result.append(current)
    return result


def _detect_col(header: list[str], candidates: list[str]) -> int:
    for name in candidates:
        for i, h in enumerate(header):
            if h == name or name in h:
                return i
    return -1


def _patch_address(raw_num: str, fallback: int, bank_str: str) -> tuple[int, int]:
    """
    Return (program_change_0based, bank_select_msb) from a raw patch-number
    string such as 'U01', 'P99', 'A16', or plain '42'.
    """
    import re
    m = re.match(r'^([A-Za-z]+)(\d+)$', raw_num.strip())
    if m:
        prefix = m.group(1).upper()
        num    = int(m.group(2))
        if prefix in ('P', 'PR'):
            bank_msb = 1
        elif prefix == 'U':
            bank_msb = 0
        else:
            bank_msb = ord(prefix[0]) - ord('A')
        return max(0, num - 1) % 128, bank_msb

    try:
        n = int(raw_num)
        bl = bank_str.lower()
        bank_msb = 1 if ('preset' in bl or bl == 'p') else 0
        return max(0, n - 1) % 128, bank_msb
    except ValueError:
        pass

    return fallback % 128, 0


def load_patches_from_csv(path: str) -> dict:
    """
    Parse a patch CSV file.
    Returns dict keyed by (bank_msb, pc) → {"num": str, "name": str, "bank": str}
    """
    with open(path, newline='', encoding='utf-8-sig') as f:
        raw = f.read()

    lines = [l for l in raw.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        raise ValueError("CSV has no data rows.")

    header = [h.strip().strip('"').lower() for h in _split_csv_line(lines[0])]

    num_col  = _detect_col(header, ['number','num','patch number','patch no',
                                     'patch_number','no','#','id','patch_no'])
    name_col = _detect_col(header, ['name','patch name','patchname',
                                     'title','patch_name','label'])
    bank_col = _detect_col(header, ['bank','category','cat','group',
                                     'type','bank/category','bank_category'])

    if name_col < 0:
        raise ValueError(
            "Could not detect a 'name' column in the CSV.\n"
            f"Columns found: {header}"
        )

    patches = {}
    for i, line in enumerate(lines[1:]):
        cols = _split_csv_line(line)
        if all(not c.strip() for c in cols):
            continue
        raw_num  = cols[num_col].strip().strip('"')  if num_col  >= 0 else str(i + 1)
        raw_name = cols[name_col].strip().strip('"') if name_col >= 0 else f"Patch {i+1}"
        raw_bank = cols[bank_col].strip().strip('"') if bank_col >= 0 else ""

        pc, bank_msb = _patch_address(raw_num, i, raw_bank)
        patches[(bank_msb, pc)] = {"num": raw_num, "name": raw_name, "bank": raw_bank}

    return patches


def find_csv_for_device(device_name: str) -> str | None:
    """Return path to a CSV file that matches the device name, or None."""
    lower = device_name.lower()
    for key, filename in DEVICE_CSV_MAP.items():
        if key in lower:
            candidate = os.path.join(SCRIPT_DIR, filename)
            if os.path.isfile(candidate):
                return candidate
    return None


# ── Main application ─────────────────────────────────────────────────────────

class ShowPatch:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG)
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.minsize(400, 220)

        self.midi_in        = None          # rtmidi.MidiIn instance
        self.connected_port = None          # index of open port
        self.patches        = {}            # (bank_msb, pc) → patch info
        self.current_bank   = 0             # last seen Bank Select MSB
        self.csv_path       = None          # path of loaded CSV
        self._blink_job     = None

        self._build_ui()
        self._refresh_devices()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Top bar ──────────────────────────────────────────────────────────
        topbar = tk.Frame(self.root, bg=SURFACE, pady=0)
        topbar.pack(fill='x')

        tk.Label(topbar, text="MIDI In:", bg=SURFACE, fg=TEXT_DIM,
                 font=("Segoe UI", 10)).pack(side='left', padx=(12, 4), pady=8)

        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(topbar, textvariable=self.device_var,
                                          state='readonly', width=32)
        self.device_combo.pack(side='left', padx=(0, 6), pady=8)

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TCombobox', fieldbackground=SURFACE2,
                         background=SURFACE2, foreground=TEXT,
                         selectbackground=SURFACE2, selectforeground=TEXT)

        self.connect_btn = tk.Button(topbar, text="Connect",
                                      command=self._connect,
                                      bg=SURFACE2, fg=TEXT, relief='flat',
                                      padx=12, pady=3, cursor='hand2',
                                      activebackground=BORDER, activeforeground=ACCENT_L)
        self.connect_btn.pack(side='left', padx=(0, 4), pady=8)

        self.refresh_btn = tk.Button(topbar, text="⟳",
                                      command=self._refresh_devices,
                                      bg=SURFACE2, fg=TEXT_DIM, relief='flat',
                                      padx=8, pady=3, cursor='hand2',
                                      font=("Segoe UI", 12),
                                      activebackground=BORDER)
        self.refresh_btn.pack(side='left', pady=8)

        self.csv_btn = tk.Button(topbar, text="Load CSV",
                                  command=self._load_csv_dialog,
                                  bg=SURFACE2, fg=TEXT, relief='flat',
                                  padx=12, pady=3, cursor='hand2',
                                  activebackground=BORDER, activeforeground=ACCENT_L)
        self.csv_btn.pack(side='right', padx=12, pady=8)

        # ── Centre display ───────────────────────────────────────────────────
        center = tk.Frame(self.root, bg=BG)
        center.pack(fill='both', expand=True)

        self.num_label = tk.Label(center, text="—", bg=BG, fg=TEXT_DIM,
                                   font=("Consolas", 16, 'bold'))
        self.num_label.pack(pady=(20, 2))

        self.name_label = tk.Label(center, text="Waiting for MIDI…",
                                    bg=BG, fg=TEXT_DIM,
                                    font=("Segoe UI", 30, 'bold'),
                                    wraplength=580)
        self.name_label.pack(pady=(0, 4))

        self.bank_label = tk.Label(center, text="",
                                    bg=BG, fg=TEXT_XS,
                                    font=("Segoe UI", 12))
        self.bank_label.pack()

        # ── Status bar ───────────────────────────────────────────────────────
        statusbar = tk.Frame(self.root, bg=SURFACE)
        statusbar.pack(fill='x', side='bottom')

        self.status_dot = tk.Label(statusbar, text="●", bg=SURFACE, fg=TEXT_XS,
                                    font=("Segoe UI", 10))
        self.status_dot.pack(side='left', padx=(10, 2), pady=4)

        self.status_msg = tk.Label(statusbar, text="Not connected",
                                    bg=SURFACE, fg=TEXT_DIM,
                                    font=("Segoe UI", 10), anchor='w')
        self.status_msg.pack(side='left', pady=4)

        self.blink_dot = tk.Label(statusbar, text="●", bg=SURFACE, fg=BORDER,
                                   font=("Segoe UI", 12))
        self.blink_dot.pack(side='right', padx=10, pady=4)

        self.csv_status = tk.Label(statusbar, text="No patch list loaded",
                                    bg=SURFACE, fg=TEXT_XS,
                                    font=("Segoe UI", 10))
        self.csv_status.pack(side='right', padx=(0, 16), pady=4)

    # ── Device management ─────────────────────────────────────────────────────

    def _refresh_devices(self):
        probe = rtmidi.MidiIn()
        ports = probe.get_ports()
        probe.close_port()
        del probe

        self.device_combo['values'] = ports if ports else ["(no MIDI devices found)"]
        if ports and not self.device_var.get():
            # Auto-select SE-02 if present
            for i, name in enumerate(ports):
                if any(k in name.lower() for k in DEVICE_CSV_MAP):
                    self.device_combo.current(i)
                    return
            self.device_combo.current(0)

    def _connect(self):
        sel = self.device_combo.current()
        if sel < 0:
            messagebox.showwarning(APP_TITLE, "Please select a MIDI input device.")
            return

        # Close previous connection
        if self.midi_in:
            try:
                self.midi_in.close_port()
            except Exception:
                pass

        self.midi_in = rtmidi.MidiIn()
        ports = self.midi_in.get_ports()
        if sel >= len(ports):
            messagebox.showerror(APP_TITLE, "Device not found — try refreshing.")
            return

        device_name = ports[sel]
        self.midi_in.open_port(sel)
        self.midi_in.ignore_types(sysex=False, timing=True, active_sense=True)
        self.midi_in.set_callback(self._midi_callback)
        self.connected_port = sel

        self._set_status('ok', f"Connected: {device_name}")
        self.connect_btn.config(text="Disconnect", command=self._disconnect)

        # Auto-load CSV for this device
        csv_path = find_csv_for_device(device_name)
        if csv_path:
            self._load_csv(csv_path)
        elif not self.patches:
            self._set_status('ok',
                f"Connected: {device_name}  ·  No patch list — load a CSV")

    def _disconnect(self):
        if self.midi_in:
            try:
                self.midi_in.close_port()
            except Exception:
                pass
            self.midi_in = None
        self.connected_port = None
        self._set_status('idle', "Disconnected")
        self.connect_btn.config(text="Connect", command=self._connect)
        self.name_label.config(text="Waiting for MIDI…", fg=TEXT_DIM)
        self.num_label.config(text="—")
        self.bank_label.config(text="")

    # ── CSV loading ───────────────────────────────────────────────────────────

    def _load_csv_dialog(self):
        path = filedialog.askopenfilename(
            title="Select patch list CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=SCRIPT_DIR,
        )
        if path:
            self._load_csv(path)

    def _load_csv(self, path: str):
        try:
            self.patches  = load_patches_from_csv(path)
            self.csv_path = path
            name = os.path.basename(path)
            count = len(self.patches)
            self.csv_status.config(
                text=f"{name}  ({count} patches)", fg=GREEN)
            if self.connected_port is not None:
                self._set_status('ok',
                    self.status_msg.cget('text').split('·')[0].strip()
                    + f"  ·  {count} patches loaded")
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not load CSV:\n{e}")
            self.csv_status.config(text="CSV load failed", fg=RED)

    # ── MIDI callback ─────────────────────────────────────────────────────────

    def _midi_callback(self, event, data=None):
        message, _ = event
        if not message:
            return

        self._flash_blink()

        status = message[0]
        msg_type = status & 0xF0

        if msg_type == 0xB0 and len(message) >= 3:
            # Control Change
            cc, value = message[1], message[2]
            if cc == 0x00:          # Bank Select MSB
                self.current_bank = value

        elif msg_type == 0xC0 and len(message) >= 2:
            # Program Change
            pc = message[1]
            self.root.after(0, self._show_patch, self.current_bank, pc)

    def _show_patch(self, bank_msb: int, pc: int):
        key = (bank_msb, pc)
        if self.patches:
            info = self.patches.get(key)
            if info:
                self.name_label.config(text=info["name"], fg=ACCENT_L)
                self.num_label.config(text=info["num"], fg=TEXT_DIM)
                self.bank_label.config(
                    text=info["bank"] if info["bank"] else "", fg=TEXT_XS)
            else:
                # Patch received but not in list
                self.name_label.config(
                    text=f"(unknown patch)", fg=TEXT_DIM)
                self.num_label.config(
                    text=f"Bank {bank_msb}  PC {pc}", fg=TEXT_XS)
                self.bank_label.config(text="")
        else:
            # No CSV loaded — show raw MIDI values
            self.name_label.config(
                text=f"PC {pc}", fg=ACCENT_L)
            self.num_label.config(
                text=f"Bank {bank_msb}", fg=TEXT_DIM)
            self.bank_label.config(text="No patch list loaded")

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _set_status(self, state: str, msg: str):
        colors = {'ok': GREEN, 'err': RED, 'idle': TEXT_XS}
        self.status_dot.config(fg=colors.get(state, TEXT_XS))
        self.status_msg.config(text=msg)

    def _flash_blink(self):
        self.root.after(0, self._blink_on)

    def _blink_on(self):
        self.blink_dot.config(fg=ACCENT)
        if self._blink_job:
            self.root.after_cancel(self._blink_job)
        self._blink_job = self.root.after(100, self._blink_off)

    def _blink_off(self):
        self.blink_dot.config(fg=BORDER)
        self._blink_job = None

    def _on_close(self):
        self._disconnect()
        self.root.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ShowPatch()
