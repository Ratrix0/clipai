# ClipAI - Clipboard Manager

A lightweight clipboard manager for Windows with a clean GUI.

## Features

- Monitors your clipboard automatically and saves history
- Live search through clipboard history
- Click any entry to preview the full content
- Double-click or press Enter to copy an entry back to your clipboard
- Delete individual entries or clear all history
- **Dark mode** toggle
- **System tray icon** — close the window to minimize to tray; it keeps running silently
- **Global hotkey** — press `Ctrl+Shift+V` from anywhere to bring the window up
- **Start with Windows** — optional checkbox to launch automatically on boot
- History persisted to `clipboard_history.json` (up to 100 entries)

## Download

Grab the latest `ClipboardManager.exe` from the [Releases](https://github.com/Ratrix0/clipai/releases) page — no Python required.

## Run from source

```bash
pip install pyperclip pystray Pillow keyboard
python src/main.py
```

## Build exe

```bash
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name ClipboardManager src/main.py
```

The exe will be in `dist/ClipboardManager.exe`.
