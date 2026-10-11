# RSC Mining Bot v1.4

YOLO-based mining bot for RuneScape Classic with OCR fatigue detection, anti-ban features, and a Tkinter GUI.

## Features
- **YOLO ore detection** — `best.pt` (all ores) + `adamantite.pt` (specialist model)
- **EasyOCR fatigue reading** — stops at 96% or "too tired" message
- **Live overlay** — in-game chroma-key or pop-out window
- **Anti-ban** — human-curve mouse, micro/long breaks, random delays, mouse-outside-window
- **Fast / Lazy mining modes** — configurable click timing
- **Theme presets** — Default, White+Blue, Magenta+Black, Red+Black, Green+Black, RSC Classic
- **Powermine** — continuous mining (still respects fatigue safety)

## Requirements
- Python 3.12+
- Windows (uses win32gui)

## Setup
```bash
pip install -r requirements.txt
```

## Run
```bash
python main.py
```
Or double-click `START_BOT.bat` (runs headless via `pythonw.exe`).

## Hotkey
**F6** — Start / Stop (global hotkey)

## Files
| File | Purpose |
|------|---------|
| `main.py` | GUI (Tkinter) |
| `bot.py` | Mining loop, OCR, overlay |
| `detector.py` | YOLO detection wrapper |
| `mouse.py` | Human-like mouse movement |
| `overlay.py` | Legacy overlay (unused) |
| `drag_drop_list.py` | Priority reorder widget |
| `best.pt` / `adamantite.pt` | YOLO models |
| `icons/` | Ore & pickaxe icons |
| `Tools&Test/` | OCR diagnostics & test scripts |
