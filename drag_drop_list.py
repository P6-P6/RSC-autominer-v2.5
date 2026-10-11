import os
import tkinter as tk
from tkinter import ttk

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


class OreList(tk.Frame):
    """
    Combined ore-selection + priority widget.
    Each row: [# priority]  [≡ handle]  [✓ checkbox]  [icon]  [Ore name]
    Drag any row to reorder priority. Checkbox enables/disables that ore.
    """

    ORE_DISPLAY = {
        'coal_rock':       'Coal',
        'mithril_rock':    'Mithril',
        'iron_rock':       'Iron',
        'tin_rock':        'Tin',
        'copper_rock':     'Copper',
    }

    ORE_ICON = {
        'coal_rock':    'Coal.png',
        'mithril_rock': 'Mithril_ore.png',
        'iron_rock':    'Iron_ore.png',
        'tin_rock':     'Tin_ore.png',
        'copper_rock':  'Copper_ore.png',
    }

    ORE_TINT = {
        'coal_rock':    '#555555',
        'mithril_rock': '#6a6aff',
        'iron_rock':    '#b87333',
        'tin_rock':     '#9cb4c7',
        'copper_rock':  '#c87533',
    }

    def __init__(self, parent, priority_order, checkbox_vars, bg, fg, surface, accent, muted):
        super().__init__(parent, bg=bg)
        self.bg      = bg
        self.fg      = fg
        self.surface = surface
        self.accent  = accent
        self.muted   = muted

        self._order = list(priority_order)
        self._vars  = checkbox_vars

        self._drag_src = None
        self._rows = []
        self._icons = {}  # keep PhotoImage refs alive
        self._load_icons()
        self._build()

    def _load_icons(self):
        if not _HAS_PIL:
            return
        icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icons')
        for ore, fname in self.ORE_ICON.items():
            path = os.path.join(icon_dir, fname)
            if not os.path.exists(path):
                continue
            try:
                img = Image.open(path).resize((18, 18), Image.LANCZOS)
                self._icons[ore] = ImageTk.PhotoImage(img)
            except Exception:
                pass

    # ── public API ──────────────────────────────────────────────────────────

    def get_priority_order(self):
        return [ore for _outer, ore, _badge in self._rows]

    def get_checkbox_vars(self):
        return self._vars

    # ── build / rebuild ─────────────────────────────────────────────────────

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        self._rows.clear()
        for ore in self._order:
            self._add_row(ore)
        for ore in self.ORE_DISPLAY:
            if ore not in self._order:
                self._add_row(ore)
        self._refresh_priority_numbers()

    def _add_row(self, ore):
        # Outer frame provides a 1px border for a clean "card" look.
        outer = tk.Frame(self, bg='#2a2a2a')
        outer.pack(fill='x', pady=2, padx=2)
        row = tk.Frame(outer, bg=self.surface, pady=4)
        row.pack(fill='x', padx=1, pady=1)

        # Priority badge (the row index + 1)
        pr_num = tk.Label(row, text='1', bg=self.ORE_TINT.get(ore, self.accent),
                          fg='#000000', font=('Consolas', 9, 'bold'),
                          width=2, padx=2)
        pr_num.pack(side='left', padx=(6, 4))

        handle = tk.Label(row, text='≡', bg=self.surface, fg=self.muted,
                          font=('Consolas', 14, 'bold'), cursor='fleur', width=2)
        handle.pack(side='left', padx=(0, 2))

        cb = ttk.Checkbutton(row, variable=self._vars[ore])
        cb.pack(side='left', padx=(0, 6))

        icon = self._icons.get(ore)
        if icon is not None:
            ic_lbl = tk.Label(row, image=icon, bg=self.surface)
            ic_lbl.pack(side='left', padx=(0, 6))
        else:
            ic_lbl = None

        name = self.ORE_DISPLAY.get(ore, ore.replace('_rock', '').title())
        lbl = tk.Label(row, text=name, bg=self.surface,
                       fg=self.ORE_TINT.get(ore, self.fg),
                       font=('Consolas', 11, 'bold'), anchor='w')
        lbl.pack(side='left', fill='x', expand=True)

        self._rows.append((outer, ore, pr_num))

        drag_widgets = [handle, lbl, row, outer]
        if ic_lbl is not None:
            drag_widgets.append(ic_lbl)
        for widget in drag_widgets:
            widget.bind('<Button-1>',        self._drag_start)
            widget.bind('<B1-Motion>',       self._drag_motion)
            widget.bind('<ButtonRelease-1>', self._drag_end)

    def _refresh_priority_numbers(self):
        for i, (_outer, _ore, badge) in enumerate(self._rows):
            badge.config(text=str(i + 1))

    # ── drag & drop ─────────────────────────────────────────────────────────

    def _row_at_y(self, y_abs):
        for i, (frm, _ore, _badge) in enumerate(self._rows):
            fy = frm.winfo_rooty()
            fh = frm.winfo_height()
            if fy <= y_abs < fy + fh:
                return i
        return None

    def _drag_start(self, event):
        idx = self._row_at_y(event.y_root)
        if idx is not None:
            self._drag_src = idx
            self._rows[idx][0].configure(bg=self.accent)

    def _drag_motion(self, event):
        if self._drag_src is None:
            return
        dst = self._row_at_y(event.y_root)
        if dst is None or dst == self._drag_src:
            return
        self._rows[self._drag_src], self._rows[dst] = \
            self._rows[dst], self._rows[self._drag_src]
        self._drag_src = dst
        for frm, _ore, _badge in self._rows:
            frm.pack_forget()
        for frm, _ore, _badge in self._rows:
            frm.pack(fill='x', pady=2, padx=2)
        self._refresh_priority_numbers()

    def _drag_end(self, event):
        if self._drag_src is not None:
            self._rows[self._drag_src][0].configure(bg='#2a2a2a')
        self._drag_src = None
        self._refresh_priority_numbers()


# ── Legacy shim — keeps old call sites working ──────────────────────────────

class DragDropList(ttk.Frame):
    def __init__(self, parent, items=None):
        super().__init__(parent)
        self.items = items if items else []
        self.drag_start_index = None
        self.listbox = tk.Listbox(self, height=8, selectmode=tk.SINGLE,
                                   activestyle='none', font=('Arial', 10))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)
        self.refresh_listbox()
        self.listbox.bind('<Button-1>',        self.on_drag_start)
        self.listbox.bind('<B1-Motion>',       self.on_drag_motion)
        self.listbox.bind('<ButtonRelease-1>', self.on_drag_release)

    def refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for item in self.items:
            self.listbox.insert(tk.END, item.replace('_', ' ').title())

    def on_drag_start(self, event):
        self.drag_start_index = self.listbox.nearest(event.y)

    def on_drag_motion(self, event):
        if self.drag_start_index is None:
            return
        current_index = self.listbox.nearest(event.y)
        if current_index != self.drag_start_index and 0 <= current_index < len(self.items):
            self.items[self.drag_start_index], self.items[current_index] = \
                self.items[current_index], self.items[self.drag_start_index]
            self.drag_start_index = current_index
            self.refresh_listbox()
            self.listbox.selection_set(current_index)

    def on_drag_release(self, event):
        self.drag_start_index = None

    def get_items(self):
        return self.items

    def set_items(self, items):
        self.items = items
        self.refresh_listbox()
