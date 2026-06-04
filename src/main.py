import time
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path
import winreg
import sys

try:
    import pyperclip
except ImportError:
    raise SystemExit("pyperclip is required: pip install pyperclip")

try:
    from PIL import Image, ImageDraw
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    import keyboard as kb
    HAS_HOTKEY = True
except ImportError:
    HAS_HOTKEY = False

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent

HISTORY_FILE = BASE_DIR / "clipboard_history.json"
MAX_HISTORY = 100
APP_NAME = "ClipboardManager"
HOTKEY = "ctrl+shift+v"
REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"

THEMES = {
    "light": {
        "bg": "#f5f5f5", "fg": "#1a1a1a",
        "entry_bg": "#ffffff", "tree_bg": "#ffffff", "tree_fg": "#1a1a1a",
        "preview_bg": "#ffffff", "button_bg": "#e1e1e1",
        "select_bg": "#0078d4", "select_fg": "#ffffff",
    },
    "dark": {
        "bg": "#1e1e1e", "fg": "#d4d4d4",
        "entry_bg": "#2d2d2d", "tree_bg": "#252526", "tree_fg": "#d4d4d4",
        "preview_bg": "#2d2d2d", "button_bg": "#3c3c3c",
        "select_bg": "#0078d4", "select_fg": "#ffffff",
    },
}

history: list[dict] = []
_lock = threading.Lock()
_running = False


def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_history():
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass


def add_entry(text: str):
    with _lock:
        if history and history[-1]["text"] == text:
            return
        entry = {"text": text, "timestamp": datetime.now().isoformat(timespec="seconds")}
        history.append(entry)
        if len(history) > MAX_HISTORY:
            history.pop(0)
    save_history()


def monitor_clipboard(on_change):
    last = ""
    while _running:
        try:
            current = pyperclip.paste()
            if current and current != last:
                last = current
                add_entry(current)
                on_change()
        except Exception:
            pass
        time.sleep(0.5)


def get_launch_cmd() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    return f'"{sys.executable}" "{Path(__file__).resolve()}" --minimized'


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enable: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN, 0, winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, get_launch_cmd())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


def make_tray_image() -> "Image.Image":
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 14, 56, 60], radius=6, fill="#0078d4")
    d.rounded_rectangle([22, 8, 42, 20], radius=4, fill="#005a9e")
    for y in (28, 36, 44):
        d.rectangle([16, y, 48, y + 3], fill="white")
    return img


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Clipboard Manager")
        self.geometry("700x520")
        self.minsize(500, 400)
        self._theme = "light"
        self._tray: "pystray.Icon | None" = None
        self._autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        self._build_ui()
        self._apply_theme()
        self._setup_tray()
        self._setup_hotkey()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self._refresh_list()

    def _build_ui(self):
        top = tk.Frame(self, pady=6, padx=8)
        top.pack(fill="x")

        tk.Label(top, text="Search:").pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh_list())
        self._search_entry = tk.Entry(top, textvariable=self._search_var, width=28)
        self._search_entry.pack(side="left", padx=(4, 12))

        self._theme_btn = tk.Button(top, text="Dark Mode", width=10, command=self._toggle_theme)
        self._theme_btn.pack(side="right", padx=(4, 0))

        self._autostart_cb = tk.Checkbutton(
            top, text="Start with Windows",
            variable=self._autostart_var,
            command=self._toggle_autostart,
        )
        self._autostart_cb.pack(side="right", padx=(4, 0))

        self._clear_btn = tk.Button(top, text="Clear History", command=self._clear_history)
        self._clear_btn.pack(side="right")

        frame = tk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        self._tree = ttk.Treeview(frame, columns=("time", "preview"), show="headings", selectmode="browse")
        self._tree.heading("time", text="Time")
        self._tree.heading("preview", text="Content")
        self._tree.column("time", width=160, stretch=False)
        self._tree.column("preview", width=500)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._tree.bind("<Double-1>", lambda _: self._copy_selected())
        self._tree.bind("<Return>", lambda _: self._copy_selected())
        self._tree.bind("<<TreeviewSelect>>", lambda _: self._update_preview())

        self._preview_frame = tk.LabelFrame(self, text="Preview", padx=6, pady=4)
        self._preview_frame.pack(fill="x", padx=8, pady=(0, 4))
        self._preview = tk.Text(self._preview_frame, height=5, wrap="word",
                                state="disabled", relief="flat")
        self._preview.pack(fill="x")

        bottom = tk.Frame(self, pady=4, padx=8)
        bottom.pack(fill="x")

        self._status = tk.StringVar(value="Ready")
        self._status_lbl = tk.Label(bottom, textvariable=self._status, anchor="w")
        self._status_lbl.pack(side="left")

        if HAS_HOTKEY:
            self._hotkey_lbl = tk.Label(bottom, text=f"  Hotkey: {HOTKEY.upper()}", anchor="w")
            self._hotkey_lbl.pack(side="left")

        self._delete_btn = tk.Button(bottom, text="Delete", command=self._delete_selected)
        self._delete_btn.pack(side="right", padx=(4, 0))
        self._copy_btn = tk.Button(bottom, text="Copy Selected", command=self._copy_selected)
        self._copy_btn.pack(side="right")

    def _apply_theme(self):
        t = THEMES[self._theme]
        self.configure(bg=t["bg"])
        self._theme_btn.config(text="Light Mode" if self._theme == "dark" else "Dark Mode")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=t["tree_bg"], foreground=t["tree_fg"],
                        fieldbackground=t["tree_bg"], rowheight=24)
        style.configure("Treeview.Heading", background=t["button_bg"], foreground=t["fg"])
        style.map("Treeview",
                  background=[("selected", t["select_bg"])],
                  foreground=[("selected", t["select_fg"])])

        for w in self._walk(self):
            cls = w.__class__.__name__
            try:
                if cls == "Frame":
                    w.configure(bg=t["bg"])
                elif cls == "Label":
                    w.configure(bg=t["bg"], fg=t["fg"])
                elif cls == "Button":
                    w.configure(bg=t["button_bg"], fg=t["fg"],
                                activebackground=t["select_bg"], activeforeground=t["select_fg"])
                elif cls == "Entry":
                    w.configure(bg=t["entry_bg"], fg=t["fg"], insertbackground=t["fg"])
                elif cls == "Checkbutton":
                    w.configure(bg=t["bg"], fg=t["fg"], selectcolor=t["entry_bg"],
                                activebackground=t["bg"], activeforeground=t["fg"])
                elif cls == "LabelFrame":
                    w.configure(bg=t["bg"], fg=t["fg"])
                elif cls == "Text":
                    w.configure(bg=t["preview_bg"], fg=t["fg"], insertbackground=t["fg"])
            except tk.TclError:
                pass

        self._clear_btn.configure(fg="#ff4444")

    def _walk(self, parent):
        yield parent
        for child in parent.winfo_children():
            yield from self._walk(child)

    def _toggle_theme(self):
        self._theme = "dark" if self._theme == "light" else "light"
        self._apply_theme()

    def _setup_tray(self):
        if not HAS_TRAY:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda icon, item: self.after(0, self._show_window), default=True),
            pystray.MenuItem("Quit", lambda icon, item: self.after(0, self._quit_app)),
        )
        self._tray = pystray.Icon(APP_NAME, make_tray_image(), APP_NAME, menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _setup_hotkey(self):
        if not HAS_HOTKEY:
            return
        try:
            kb.add_hotkey(HOTKEY, lambda: self.after(0, self._show_window))
        except Exception:
            pass

    def _show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _hide_to_tray(self):
        if HAS_TRAY and self._tray:
            self.withdraw()
        else:
            self._quit_app()

    def _quit_app(self):
        global _running
        _running = False
        if self._tray:
            self._tray.stop()
        self.destroy()

    def _toggle_autostart(self):
        try:
            set_autostart(self._autostart_var.get())
        except OSError as e:
            messagebox.showerror("Error", f"Could not update autostart: {e}")
            self._autostart_var.set(not self._autostart_var.get())

    def _filtered(self):
        query = self._search_var.get().lower()
        with _lock:
            items = list(history)
        if query:
            items = [e for e in items if query in e["text"].lower()]
        return list(reversed(items))

    def _refresh_list(self):
        focused = self._tree.focus()
        self._tree.delete(*self._tree.get_children())
        for entry in self._filtered():
            preview = entry["text"].replace("\n", " ")[:120]
            self._tree.insert("", "end", iid=entry["timestamp"],
                              values=(entry["timestamp"], preview),
                              tags=(entry["text"],))
        if focused and self._tree.exists(focused):
            self._tree.focus(focused)
            self._tree.selection_set(focused)
        count = len(self._tree.get_children())
        self._status.set(f"{count} item{'s' if count != 1 else ''}")

    def _update_preview(self):
        sel = self._tree.selection()
        if not sel:
            return
        text = self._tree.item(sel[0], "tags")[0]
        self._preview.config(state="normal")
        self._preview.delete("1.0", "end")
        self._preview.insert("1.0", text)
        self._preview.config(state="disabled")

    def _copy_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        text = self._tree.item(sel[0], "tags")[0]
        pyperclip.copy(text)
        self._status.set("Copied to clipboard!")
        self.after(2000, lambda: self._status.set(f"{len(self._tree.get_children())} items"))

    def _delete_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        with _lock:
            history[:] = [e for e in history if e["timestamp"] != iid]
        save_history()
        self._refresh_list()

    def _clear_history(self):
        if messagebox.askyesno("Clear History", "Delete all clipboard history?"):
            with _lock:
                history.clear()
            save_history()
            self._preview.config(state="normal")
            self._preview.delete("1.0", "end")
            self._preview.config(state="disabled")
            self._refresh_list()

    def notify_change(self):
        self.after(0, self._refresh_list)


def main():
    global _running, history

    history = load_history()
    _running = True

    app = App()

    if "--minimized" in sys.argv:
        app.withdraw()

    threading.Thread(target=monitor_clipboard, args=(app.notify_change,), daemon=True).start()

    app.mainloop()
    _running = False


if __name__ == "__main__":
    main()
