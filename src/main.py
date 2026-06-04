import time
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path

try:
    import pyperclip
except ImportError:
    raise SystemExit("pyperclip is required: pip install pyperclip")

HISTORY_FILE = Path(__file__).parent.parent / "clipboard_history.json"
MAX_HISTORY = 100

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
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Clipboard Manager")
        self.geometry("700x500")
        self.minsize(500, 350)
        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        # Top bar: search + clear button
        top = tk.Frame(self, pady=6, padx=8)
        top.pack(fill="x")

        tk.Label(top, text="Search:").pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh_list())
        search_entry = tk.Entry(top, textvariable=self._search_var, width=30)
        search_entry.pack(side="left", padx=(4, 12))

        tk.Button(top, text="Clear History", fg="red", command=self._clear_history).pack(side="right")

        # History list with scrollbar
        frame = tk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        cols = ("time", "preview")
        self._tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        self._tree.heading("time", text="Time")
        self._tree.heading("preview", text="Content")
        self._tree.column("time", width=160, stretch=False)
        self._tree.column("preview", width=500)

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._tree.bind("<Double-1>", lambda _: self._copy_selected())
        self._tree.bind("<Return>", lambda _: self._copy_selected())

        # Preview pane
        preview_frame = tk.LabelFrame(self, text="Preview", padx=6, pady=4)
        preview_frame.pack(fill="x", padx=8, pady=(0, 4))

        self._preview = tk.Text(preview_frame, height=5, wrap="word", state="disabled",
                                bg=self.cget("bg"), relief="flat")
        self._preview.pack(fill="x")
        self._tree.bind("<<TreeviewSelect>>", lambda _: self._update_preview())

        # Bottom bar
        bottom = tk.Frame(self, pady=4, padx=8)
        bottom.pack(fill="x")

        self._status = tk.StringVar(value="Ready")
        tk.Label(bottom, textvariable=self._status, anchor="w").pack(side="left")
        tk.Button(bottom, text="Copy Selected", command=self._copy_selected).pack(side="right")
        tk.Button(bottom, text="Delete Selected", command=self._delete_selected).pack(side="right", padx=(0, 6))

    def _filtered(self):
        query = self._search_var.get().lower()
        with _lock:
            items = list(history)
        if query:
            items = [e for e in items if query in e["text"].lower()]
        return list(reversed(items))

    def _refresh_list(self):
        selected_iid = self._tree.focus()
        self._tree.delete(*self._tree.get_children())
        for entry in self._filtered():
            preview = entry["text"].replace("\n", " ")[:120]
            self._tree.insert("", "end", iid=entry["timestamp"], values=(entry["timestamp"], preview),
                              tags=(entry["text"],))
        if selected_iid and self._tree.exists(selected_iid):
            self._tree.focus(selected_iid)
            self._tree.selection_set(selected_iid)
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
        # Called from monitor thread — schedule UI update on main thread
        self.after(0, self._refresh_list)


def main():
    global _running, history

    history = load_history()
    _running = True

    app = App()

    monitor_thread = threading.Thread(
        target=monitor_clipboard, args=(app.notify_change,), daemon=True
    )
    monitor_thread.start()

    app.mainloop()
    _running = False


if __name__ == "__main__":
    main()
