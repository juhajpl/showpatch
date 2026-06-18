# ShowPatch

A small desktop app that monitors MIDI Program Change messages and displays the current patch name in large text — handy for keeping track of patches on a Roland SE-02 (or any MIDI device with a CSV patch list).

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- Detects all connected MIDI input devices and lets you pick one
- Auto-connects to SE-02 if detected, and auto-loads its patch CSV
- Listens for Bank Select (CC 0) + Program Change messages
- Displays patch number, name, and bank/category in large clear text
- Orange activity dot blinks on every incoming MIDI message
- Works without a CSV too — shows raw Bank/PC numbers as fallback

## Requirements

- Python 3.10 or newer
- `python-rtmidi`
- `tkinter` (included with standard Python on Windows and macOS)

## Installation

```bash
git clone https://github.com/juhajpl/showpatch.git
cd showpatch
pip install -r requirements.txt
```

On Linux, tkinter may need a separate install:
```bash
sudo apt install python3-tk
```

## Usage

```bash
python showpatch.py
```

1. Select your MIDI input device from the dropdown
2. Click **Connect**
3. If a matching CSV is found next to the script it loads automatically
4. Otherwise click **Load CSV** and pick your patch list file

Change patches on the SE-02 — the name appears instantly.

## Patch list CSV format

Place a CSV file next to `showpatch.py`. For the SE-02, name it `SE-02_patches.csv`.

Expected columns (column names are detected automatically, case-insensitive):

| Column | Examples of accepted names |
|--------|---------------------------|
| Patch number | `Number`, `No`, `Patch No`, `#` |
| Patch name   | `Name`, `Patch Name`, `Title` |
| Bank / category | `Bank`, `Category`, `Group` *(optional)* |

Patch numbers can be plain integers (`1`, `42`) or prefixed (`U01`, `P99`, `A16`):

- `U` prefix → User bank (Bank Select 0)
- `P` prefix → Preset bank (Bank Select 1)
- Letter prefix (`A`–`Z`) → bank number derived from letter position

## Adding more devices

Edit `DEVICE_CSV_MAP` near the top of `showpatch.py`:

```python
DEVICE_CSV_MAP = {
    "se-02": "SE-02_patches.csv",
    "se02":  "SE-02_patches.csv",
    "juno":  "Juno_patches.csv",   # example — add your own
}
```

The key is a substring matched (case-insensitively) against the MIDI device name.
The value is the CSV filename to auto-load, looked up next to `showpatch.py`.

## License

MIT
