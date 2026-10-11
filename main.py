import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import random
import os
import threading
import time
import win32gui
import win32api
import win32con
from bot import MiningBot
from drag_drop_list import DragDropList, OreList
import ctypes
from ctypes import wintypes
import psutil
from PIL import Image, ImageTk

# Force 100% DPI — tell Windows this process is DPI-unaware so it
# handles all scaling via GDI stretching. The GUI always renders at
# 96 DPI regardless of the user's display scale setting.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware — mss/win32 use physical pixels
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

WM_HOTKEY = 0x0312
VK_F6 = 0x75

# ── Theme Presets ─────────────────────────────────────────────────────────────
THEMES = {
    'RS-Classic': {
        'BG': '#000000', 'SURFACE': '#0c0c00', 'BORDER': '#333300',
        'FG': '#ffff00', 'MUTED': '#c8c800', 'ACCENT': '#ffcc00',
        'GREEN': '#00ff00', 'RED': '#ff0000', 'AMBER': '#ffff00',
        'TITLE_BG': '#000000',
    },
    'Default': {
        'BG': '#0d0d0f', 'SURFACE': '#16161a', 'BORDER': '#2a2a32',
        'FG': '#e2e2e8', 'MUTED': '#9e9eab', 'ACCENT': '#ff6b7a',
        'GREEN': '#4ade80', 'RED': '#ff6b6b', 'AMBER': '#facc15',
        'TITLE_BG': '#080808',
    },
    'Cobalt': {
        'BG': '#090e1a', 'SURFACE': '#111827', 'BORDER': '#1e3a5f',
        'FG': '#dbeafe', 'MUTED': '#6b8fbd', 'ACCENT': '#38bdf8',
        'GREEN': '#34d399', 'RED': '#f87171', 'AMBER': '#fbbf24',
        'TITLE_BG': '#060a12',
    },
    'Obsidian': {
        'BG': '#08080a', 'SURFACE': '#111113', 'BORDER': '#1e2a1e',
        'FG': '#d4f4d4', 'MUTED': '#6a8f6a', 'ACCENT': '#22c55e',
        'GREEN': '#22c55e', 'RED': '#ef4444', 'AMBER': '#f59e0b',
        'TITLE_BG': '#050505',
    },
    # Neumorphic-inspired dark theme — soft contrast, muted blue accent.
    'Neumorphic': {
        'BG': '#0f1419', 'SURFACE': '#161c23', 'BORDER': '#1f2730',
        'FG': '#cfd8dc', 'MUTED': '#7f8c8d', 'ACCENT': '#4f7cff',
        'GREEN': '#5dd39e', 'RED': '#f06b7e', 'AMBER': '#f3b95f',
        'TITLE_BG': '#0a0e12',
    },
}
FONT_CHOICES = ['Consolas', 'Segoe UI', 'Courier New', 'Fixedsys']

def _load_active_theme():
    global BG, SURFACE, BORDER, FG, MUTED, ACCENT, GREEN, RED, AMBER, TITLE_BG, FONT_UI, FONT_HDR
    theme_name = 'Neumorphic'
    font_name = 'Segoe UI'
    if os.path.exists('config.json'):
        try:
            with open('config.json', 'r') as f:
                cfg = json.load(f)
            theme_name = cfg.get('theme', 'Neumorphic')
            font_name = cfg.get('font', 'Segoe UI')
        except Exception:
            pass
    t = THEMES.get(theme_name, THEMES.get('Neumorphic', THEMES['Default']))
    BG       = t['BG']
    SURFACE  = t['SURFACE']
    BORDER   = t['BORDER']
    FG       = t['FG']
    MUTED    = t['MUTED']
    ACCENT   = t['ACCENT']
    GREEN    = t['GREEN']
    RED      = t['RED']
    AMBER    = t['AMBER']
    TITLE_BG = t['TITLE_BG']
    if font_name not in FONT_CHOICES:
        font_name = 'Segoe UI'
    FONT_UI  = (font_name, 10)
    FONT_HDR = (font_name, 11, 'bold')

_load_active_theme()


def card(parent, **kw):
    # Two-tone frame for a subtle "raised" feel: BORDER outer ring + SURFACE
    # inner panel. Slightly thicker inner padding gives the card breathing room
    # so the neumorphic-style surface reads as elevated against the BG.
    outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
    inner_pad = kw.pop('padx', 0), kw.pop('pady', 0)
    inner = tk.Frame(outer, bg=SURFACE, padx=max(inner_pad[0], 6),
                     pady=max(inner_pad[1], 4), **kw)
    inner.pack(fill='both', expand=True)
    return outer, inner


def section_label(parent, text):
    tk.Label(parent, text=text.upper(), bg=SURFACE, fg=ACCENT,
             font=('Segoe UI', 10, 'bold'), pady=6).pack(anchor='w', padx=10)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill='x', padx=8, pady=(0, 8))


class Toggle(tk.Canvas):
    """Pill-style iOS toggle switch backed by a BooleanVar."""

    W, H, R = 36, 18, 9  # pill width, height, circle radius

    def __init__(self, parent, variable, bg=None, **kw):
        bg = bg or SURFACE
        super().__init__(parent, width=self.W, height=self.H,
                         bg=bg, highlightthickness=0, cursor='hand2', **kw)
        self._var = variable
        self._disabled = False
        self._draw()
        self.bind('<Button-1>', self._toggle)
        variable.trace_add('write', lambda *_: self._draw())

    def _draw(self):
        self.delete('all')
        on = self._var.get()
        if self._disabled:
            track = '#3a3a3a'
            knob  = '#5a5a5a'
        else:
            track = GREEN if on else BORDER
            knob  = '#ffffff'
        # Track pill
        r = self.H // 2
        self.create_oval(0, 0, self.H, self.H, fill=track, outline='')
        self.create_oval(self.W - self.H, 0, self.W, self.H, fill=track, outline='')
        self.create_rectangle(r, 0, self.W - r, self.H, fill=track, outline='')
        # Knob
        pad = 2
        kx = self.W - self.H + pad if on else pad
        self.create_oval(kx, pad, kx + self.H - 2*pad, self.H - pad,
                         fill=knob, outline='')

    def _toggle(self, _=None):
        if self._disabled:
            return
        self._var.set(not self._var.get())

    def set_disabled(self, disabled: bool):
        self._disabled = disabled
        self.configure(cursor='arrow' if disabled else 'hand2')
        self._draw()


def toggle_row(parent, text, variable, bg=None):
    """Helper: renders  [Toggle]  Label  in a horizontal row."""
    bg = bg or SURFACE
    row = tk.Frame(parent, bg=bg)
    Toggle(row, variable, bg=bg).pack(side='left', padx=(0, 8))
    tk.Label(row, text=text, bg=bg, fg=FG,
             font=FONT_UI, anchor='w').pack(side='left', fill='x', expand=True)
    return row


class MiningBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title('Bot V2.5')
        self.root.geometry('640x560')
        self.root.minsize(500, 460)
        self.root.configure(bg=BG)
        self.root.protocol('WM_DELETE_WINDOW', self.on_closing)

        # Window icon (pickaxe)
        _icons_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icons')
        try:
            _ico_img = Image.open(os.path.join(_icons_dir, 'Rune_Pickaxe.png'))
            self._app_icon = ImageTk.PhotoImage(_ico_img)
            self.root.iconphoto(True, self._app_icon)
        except Exception:
            pass

        self.bot = None
        self.bot_thread = None
        self.running = False
        self.obtain_count = 0
        self.ore_count = 0
        self._stat_rx_offset    = 0    # cumulative red-X clicks — never reset until program closes
        self._stat_banks_offset = 0    # cumulative bank trips — never reset until program closes
        self._pause_started_at  = None # wall time when pause began
        self._total_paused_secs = 0.0  # total seconds paused this run (for runtime clock)
        self._runtime_saved_secs = self._load_saved_runtime()
        self._overlay_win = None
        self._overlay_label = None
        # Cache for live label text — skip tkinter redraws when text unchanged.
        self._live_label_cache: dict = {}
        self._overlay_canvas = None
        self._overlay_canvas_item = None
        self._overlay_photo = None
        self._det_seen_at = {}  # smoothing: key -> (det, timestamp)

        self.load_config()
        self._build_styles()
        self._build_ui()

        self.start_hotkey_listener()

    # ── Config ────────────────────────────────────────────────────────────────

    def load_config(self):
        if os.path.exists('config.json'):
            with open('config.json', 'r') as f:
                self.config = json.load(f)
        else:
            self.config = {
                'window_title': 'RScrevolution',
                'ore_checkboxes': {},
                'show_empty_ore': False,
                'priority_order': [],
                'break_settings': {},
                'mouse_settings': {},
                'model_settings': {'use_main_model': True, 'use_adamantite_model': False},
                'detection_settings': {
                    'confidence_threshold': 0.75,
                    'update_interval_ms': 200,
                    'no_ore_retry_delay_ms': 500,
                },
                'powermine_enabled': False,
                'fatigue_detection_enabled': True,
            }

    def save_config(self):
        self.config['window_title'] = self._title_from_display(self.window_var.get())
        self.config['show_empty_ore'] = self.show_empty_var.get()
        for ore, var in self.checkbox_vars.items():
            self.config['ore_checkboxes'][ore] = var.get()
        # Priority is always highest-tier-first: Adamantite > Mithril > Coal > Iron > Copper > Tin.
        # Enabled ores come first in tier order; disabled ores trail at the end.
        _TIER_ORDER = ['adamantite_rock', 'mithril_rock', 'coal_rock', 'iron_rock', 'copper_rock', 'tin_rock']
        self.config['priority_order'] = (
            [o for o in _TIER_ORDER if self.config['ore_checkboxes'].get(o, False)]
            + [o for o in _TIER_ORDER if not self.config['ore_checkboxes'].get(o, False)]
        )
        self.config['break_settings'] = {
            'breaks_enabled':              self.breaks_enabled_var.get(),
            'min_seconds_between_breaks':  int(self.min_break_interval_var.get()) * 60,
            'max_seconds_between_breaks':  int(self.max_break_interval_var.get()) * 60,
            'min_break_duration_seconds':  int(self.min_break_duration_var.get()) * 60,
            'max_break_duration_seconds':  int(self.max_break_duration_var.get()) * 60,
        }
        try:
            self.config['mouse_settings'] = {
                'min_delay_ms':         int(self.min_delay_var.get()),
                'max_delay_ms':         int(self.max_delay_var.get()),
                'human_curve_strength': float(self.human_curve_var.get()),
                'mouse_seed':           int(self.mouse_seed_var.get()) if hasattr(self, 'mouse_seed_var') else None,
                'mouse_movement_mode':  self.mouse_movement_mode_var.get() if hasattr(self, 'mouse_movement_mode_var') else 'teleport',
            }
        except Exception:
            pass
        self.config['model_settings'] = {
            'use_main_model':       self.main_model_var.get(),
            'use_adamantite_model': False,
        }
        try:
            det = self.config.get('detection_settings', {}) or {}
            det['confidence_threshold'] = float(self.confidence_var.get())
            self.config['detection_settings'] = det
        except Exception:
            pass
        self.config['overlay_box_thickness'] = self.overlay_thickness_var.get()
        self.config['antiban_master_enabled'] = (
            self.antiban_master_var.get() if hasattr(self, 'antiban_master_var') else True)
        self.config['antiban_failsafe_enabled'] = (
            self.antiban_failsafe_var.get() if hasattr(self, 'antiban_failsafe_var') else True)
        self.config['powermine_enabled'] = self.powermine_var.get()
        self.config['fatigue_detection_enabled'] = self.fatigue_detection_var.get()
        if hasattr(self, 'teleport_detect_var'):
            self.config['teleport_detection_enabled'] = self.teleport_detect_var.get()
            try:
                self.config['teleport_threshold'] = int(self.teleport_thresh_var.get())
            except (ValueError, tk.TclError, AttributeError):
                pass
        if hasattr(self, 'teleport_reactions_var'):
            self.config['teleport_reactions_text'] = self.teleport_reactions_var.get()
        if hasattr(self, 'teleport_pick_random_var'):
            self.config['teleport_pick_random'] = bool(self.teleport_pick_random_var.get())
        self.config['verbose_debug'] = self.verbose_debug_var.get()
        _spd = self.mining_speed_var.get()
        self.config['speed_mode'] = _spd
        self.config['fast_mining_enabled'] = (_spd == 'fast')
        self.config['lazy_idle_pause_enabled'] = self.lazy_idle_pause_var.get()
        self.config['hover_mode_enabled'] = self.hover_mode_var.get()
        self.config['camera_rotation_enabled'] = self.camera_rotation_var.get()
        self.config['fixed_ore_spots'] = self._fixed_spots
        if hasattr(self, 'fixed_spot_mode_var'):
            self.config['fixed_ore_spots_enabled'] = self.fixed_spot_mode_var.get()
            self.config['direct_ore_preposition'] = self.direct_ore_var.get()
        if hasattr(self, 'quick_turn_var'):
            self.config['quick_turn_no_ore_enabled'] = self.quick_turn_var.get()
        self.config['stop_on_full_inventory'] = self.stop_on_full_var.get()
        if hasattr(self, 'banking_enabled_var'):
            self.config['banking_enabled'] = self.banking_enabled_var.get()
        if hasattr(self, 'bank_clicks_min_var'):
            try:
                v = self.bank_clicks_min_var.get().strip()
                self.config['bank_clicks_min'] = int(v) if v else None
            except (ValueError, AttributeError):
                self.config['bank_clicks_min'] = None
        if hasattr(self, 'bank_clicks_max_var'):
            try:
                v = self.bank_clicks_max_var.get().strip()
                self.config['bank_clicks_max'] = int(v) if v else None
            except (ValueError, AttributeError):
                self.config['bank_clicks_max'] = None
        if hasattr(self, 'pause_on_user_input_var'):
            self.config['pause_on_user_input'] = self.pause_on_user_input_var.get()
        self.config['overlay_mode'] = self.overlay_mode_var.get()
        self.config['mouse_outside_window'] = self.mouse_outside_var.get()
        self.config['window_brightness'] = self._brightness_var.get() if hasattr(self, '_brightness_var') else 100
        if hasattr(self, 'autologin_var'):
            self.config['autologin_enabled'] = self.autologin_var.get()
        if hasattr(self, 'mod_crown_var'):
            self.config['mod_crown_detection_enabled'] = self.mod_crown_var.get()
        if hasattr(self, 'camera_rotate_only_var'):
            self.config['camera_rotate_only'] = self.camera_rotate_only_var.get()
        if hasattr(self, 'chat_text_stop_var'):
            self.config['chat_text_stop_enabled'] = self.chat_text_stop_var.get()
            raw = self.chat_text_phrases_var.get() if hasattr(self, 'chat_text_phrases_var') else ''
            phrases = [p.strip().lower() for p in raw.split(',') if p.strip()]
            self.config['chat_text_stop_phrases'] = phrases
        if hasattr(self, 'walkto_enabled_var'):
            self.config['walkto_enabled'] = self.walkto_enabled_var.get()
        if hasattr(self, 'walkto_min_var'):
            try:
                self.config['walkto_min_clicks'] = int(self.walkto_min_var.get())
            except Exception:
                pass
        if hasattr(self, 'walkto_max_var'):
            try:
                self.config['walkto_max_clicks'] = int(self.walkto_max_var.get())
            except Exception:
                pass
        if hasattr(self, 'walkto_dest_var'):
            self.config['walkto_destination'] = self.walkto_dest_var.get().strip()
        if hasattr(self, 'multi_client_var'):
            self.config['multi_client_mode'] = self.multi_client_var.get()
        if hasattr(self, 'theme_var'):
            self.config['theme'] = self.theme_var.get()
        if hasattr(self, 'font_var'):
            self.config['font'] = self.font_var.get()
        if hasattr(self, 'tm_master_var'):
            self.config['template_match_enabled'] = self.tm_master_var.get()
        if hasattr(self, 'tm_sleep_var'):
            self.config['tm_sleep_enabled'] = self.tm_sleep_var.get()
            try:
                self.config['tm_sleep_fatigue_threshold'] = int(self.tm_sleep_threshold_var.get())
            except Exception:
                pass
        if hasattr(self, 'tm_auto_close_var'):
            self.config['tm_auto_close_enabled'] = self.tm_auto_close_var.get()
        if hasattr(self, 'tm_threshold_var'):
            try:
                self.config['tm_threshold'] = round(float(self.tm_threshold_var.get()), 2)
            except Exception:
                pass
        # Atomic write: dump to temp then replace, so Google Drive sync / concurrent
        # writers can't leave a half-written config.json on disk.
        import os, tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(prefix='config_', suffix='.json', dir='.')
        try:
            with os.fdopen(tmp_fd, 'w') as f:
                json.dump(self.config, f, indent=4)
            os.replace(tmp_path, 'config.json')
        except Exception:
            try: os.unlink(tmp_path)
            except Exception: pass
            raise

    def get_java_windows(self):
        """Return list of display strings for Java windows; populates self._window_info_map."""
        self._window_info_map = {}  # display_str -> dict(title, pid, hwnd, pos_label)
        entries = []
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        def _pos_label(x, y, w, h):
            cx, cy = x + w // 2, y + h // 2
            vert  = 'Top'    if cy < sh * 0.4 else ('Bottom' if cy > sh * 0.6 else 'Center')
            horiz = 'Left'   if cx < sw * 0.4 else ('Right'  if cx > sw * 0.6 else '')
            return (vert + horiz).strip() or 'Center'

        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if proc.info['name'] not in ('javaw.exe', 'java.exe'):
                        continue
                    pid = proc.info['pid']
                    hwnd_list = []

                    def _enum(hwnd, _ctx, _pid=pid):
                        if win32gui.IsWindowVisible(hwnd):
                            try:
                                dpid = ctypes.wintypes.DWORD()
                                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(dpid))
                                if dpid.value == _pid:
                                    hwnd_list.append(hwnd)
                            except Exception:
                                pass
                        return True

                    win32gui.EnumWindows(_enum, None)
                    for hwnd in hwnd_list:
                        title = win32gui.GetWindowText(hwnd)
                        if not title:
                            continue
                        # Detect minimized: IsIconic + the (-32000,-32000) sentinel.
                        try:
                            minimized = bool(win32gui.IsIconic(hwnd))
                        except Exception:
                            minimized = False
                        try:
                            rect = win32gui.GetWindowRect(hwnd)
                            x, y, x2, y2 = rect
                            w, h = x2 - x, y2 - y
                            if x <= -30000 or y <= -30000:
                                minimized = True
                            if minimized:
                                pos = 'Minimized'
                                sz = '—'
                            else:
                                pos = _pos_label(x, y, w, h)
                                sz = f'{w}×{h}'
                        except Exception:
                            pos, sz = ('Minimized' if minimized else '?'), '—'
                        display = f'{title}  |  PID {pid}  |  {pos}  |  {sz}'
                        if display not in self._window_info_map:
                            self._window_info_map[display] = {
                                'title': title, 'pid': pid, 'hwnd': hwnd,
                                'pos': pos, 'size': sz, 'minimized': minimized,
                            }
                            entries.append(display)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            print(f'[WIN] Error scanning windows: {e}')

        if not entries:
            fallback = 'RScrevolution  |  PID ?  |  ?  |  ?'
            self._window_info_map[fallback] = {'title': 'RScrevolution', 'pid': None,
                                               'hwnd': None, 'pos': '?', 'size': '?'}
            entries = [fallback]
        return entries

    def _title_from_display(self, display_str):
        """Extract window title from a display string (or return it verbatim as fallback)."""
        info = self._window_info_map.get(display_str)
        return info['title'] if info else display_str.split('  |  ')[0]

    # ── Style ─────────────────────────────────────────────────────────────────

    def _build_styles(self):
        s = ttk.Style()
        s.theme_use('clam')
        s.configure('TFrame',      background=BG)
        s.configure('TLabel',      background=SURFACE, foreground=FG, font=FONT_UI)
        # Toggle-style checkbuttons: rounded look, teal when selected
        s.configure('TCheckbutton',
                    background=SURFACE, foreground=FG, font=FONT_UI,
                    indicatorcolor=BORDER, indicatorrelief='flat',
                    indicatormargin=4, selectcolor=GREEN)
        s.map('TCheckbutton',
              background=[('active', SURFACE)],
              foreground=[('active', FG)],
              indicatorcolor=[('selected', GREEN), ('!selected', BORDER)])
        s.configure('TEntry',
                    fieldbackground=TITLE_BG, foreground=FG,
                    insertcolor=FG, font=FONT_UI, padding=3, relief='flat')
        s.configure('TScale', background=SURFACE, troughcolor=BORDER, slidercolor=ACCENT)
        s.configure('TRadiobutton', background=SURFACE, foreground=FG, font=FONT_UI,
                    indicatorcolor=BORDER, selectcolor=GREEN)
        s.map('TRadiobutton',
              background=[('active', SURFACE)],
              indicatorcolor=[('selected', GREEN)])
        s.configure('Start.TButton',
                    font=('Segoe UI', 9, 'bold'),
                    background=GREEN, foreground='#0f131a',
                    padding=(18, 7), relief='flat')
        s.map('Start.TButton',
              background=[('active', '#4dd4b6'), ('disabled', BORDER)],
              foreground=[('disabled', MUTED)])
        s.configure('Stop.TButton',
                    font=('Segoe UI', 9, 'bold'),
                    background=RED, foreground='#0f131a',
                    padding=(18, 7), relief='flat')
        s.map('Stop.TButton',
              background=[('active', '#e05555'), ('disabled', BORDER)],
              foreground=[('disabled', MUTED)])
        s.configure('Util.TButton',
                    font=FONT_UI,
                    background=BORDER, foreground=FG,
                    padding=(10, 5), relief='flat')
        s.map('Util.TButton', background=[('active', '#3a4458')])
        s.configure('TNotebook', background=BG, borderwidth=0)
        s.configure('TNotebook.Tab', background=BORDER, foreground=MUTED,
                    font=('Segoe UI', 9, 'bold'), padding=(14, 6))
        s.map('TNotebook.Tab',
              background=[('selected', SURFACE)],
              foreground=[('selected', FG)])

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        _icons_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icons')
        self._title_icons = []  # prevent GC

        # Window geometry — sensible starting size, enforced minimum so
        # START/STOP footer is always visible.
        self.root.geometry('960x720')
        self.root.minsize(760, 600)

        # Titlebar (two rows: top = brand+counters, bottom = live stats)
        bar_wrap = tk.Frame(self.root, bg=TITLE_BG)
        bar_wrap.pack(fill='x')
        bar = tk.Frame(bar_wrap, bg=TITLE_BG, height=38)
        bar.pack(fill='x')
        bar.pack_propagate(False)

        # Pickaxe icon + title text
        try:
            pick_img = Image.open(os.path.join(_icons_dir, 'Rune_Pickaxe.png')).resize((24, 24), Image.LANCZOS)
            pick_photo = ImageTk.PhotoImage(pick_img)
            self._title_icons.append(pick_photo)
            tk.Label(bar, image=pick_photo, bg=TITLE_BG).pack(side='left', padx=(14, 4), pady=10)
        except Exception:
            pass
        tk.Label(bar, text='BOT  V2.5', bg=TITLE_BG, fg=FG,
                 font=('Segoe UI', 11, 'bold')).pack(side='left', pady=12)

        # Ore icons in order: Copper, Coal, Iron, Mithril, Adamantite, Tin
        ore_files = ['Copper_ore.png', 'Coal.png', 'Iron_ore.png',
                     'Mithril_ore.png', 'Adamantite_ore.png', 'Tin_ore.png']
        for fname in ore_files:
            try:
                ore_img = Image.open(os.path.join(_icons_dir, fname)).resize((20, 20), Image.LANCZOS)
                ore_photo = ImageTk.PhotoImage(ore_img)
                self._title_icons.append(ore_photo)
                tk.Label(bar, image=ore_photo, bg=TITLE_BG).pack(side='left', padx=1, pady=10)
            except Exception:
                pass
        
        self.status_dot = tk.Label(bar, text='● IDLE', bg=TITLE_BG, fg=MUTED,
                                   font=('Segoe UI', 8, 'bold'))
        self.status_dot.pack(side='right', padx=14)

        # Break countdown — active break timer + next-break timer
        self.break_countdown_label = tk.Label(bar, text='', bg=TITLE_BG, fg='#ffb347',
                                              font=('Consolas', 10, 'bold'))
        self.break_countdown_label.pack(side='right', padx=8)
        self.next_break_label = tk.Label(bar, text='', bg=TITLE_BG, fg=MUTED,
                                         font=('Consolas', 8))
        self.next_break_label.pack(side='right', padx=(0, 2))

        # Clicked-rocks counter (top bar)
        self.click_count = 0
        self.click_count_label = tk.Label(bar, text='⛏ 0',
                                          bg=TITLE_BG, fg=GREEN,
                                          font=('Consolas', 10, 'bold'))
        self.click_count_label.pack(side='right', padx=8)

        # Walkto countdown (top bar) — only visible when walkto is enabled
        self._walkto_bar_label = tk.Label(bar, text='',
                                          bg=TITLE_BG, fg=AMBER,
                                          font=('Consolas', 9, 'bold'))
        self._walkto_bar_label.pack(side='right', padx=8)

        # Runtime, mouse coords + last click moved into the stats box below.
        # Keep hidden stub labels so update_live_stats() doesn't crash.
        self.live_runtime_label = tk.Label(bar_wrap)   # hidden
        self.mouse_coord_label  = tk.Label(bar_wrap)   # hidden
        self.live_last_click_label = tk.Label(bar_wrap)  # hidden
        self.live_mouse_label = None

        # Top-row inventory + fatigue boxes removed. Replaced with a single
        # "Total ores est" counter — sum of _mine_count across every active
        # bot (each click that passed YOLO + red-X verification).
        stats_row = tk.Frame(bar_wrap, bg=TITLE_BG)
        stats_row.pack(fill='x', padx=8, pady=(0, 6))
        self.live_inventory_label = tk.Label(stats_row)  # unpacked anchor

        # ── Session info box (far right): Runtime / Mouse / Last Click ─────────
        # Packed FIRST with side='right' so it lands rightmost.
        _si_lbl = ('Consolas', 7, 'bold')
        _si_val = ('Consolas', 8)
        info_outer = tk.Frame(stats_row, bg=BORDER, padx=1, pady=1)
        info_outer.pack(side='right', padx=(0, 8))
        info_box = tk.Frame(info_outer, bg=SURFACE, padx=8, pady=4)
        info_box.pack()
        tk.Label(info_box, text='RUNTIME', bg=SURFACE, fg=MUTED,
                 font=_si_lbl).grid(row=0, column=0, sticky='e', padx=(0, 4))
        self.live_runtime_box_label = tk.Label(info_box, text='00:00', bg=SURFACE, fg=GREEN,
                                               font=_si_val)
        self.live_runtime_box_label.grid(row=0, column=1, sticky='w')
        tk.Label(info_box, text='MOUSE', bg=SURFACE, fg=MUTED,
                 font=_si_lbl).grid(row=1, column=0, sticky='e', padx=(0, 4))
        self.live_mouse_box_label = tk.Label(info_box, text='----, ----', bg=SURFACE, fg=MUTED,
                                             font=_si_val)
        self.live_mouse_box_label.grid(row=1, column=1, sticky='w')
        tk.Label(info_box, text='LAST CLK', bg=SURFACE, fg=MUTED,
                 font=_si_lbl).grid(row=2, column=0, sticky='e', padx=(0, 4))
        self.live_click_ms_box_label = tk.Label(info_box, text='----ms', bg=SURFACE, fg=MUTED,
                                                font=_si_val)
        self.live_click_ms_box_label.grid(row=2, column=1, sticky='w')

        # ── Ore counts box (middle-right): Red X / Banked Ore / Inv's Banked ─
        ores_outer = tk.Frame(stats_row, bg=BORDER, padx=1, pady=1)
        ores_outer.pack(side='right', padx=(0, 8))
        ores_box = tk.Frame(ores_outer, bg=SURFACE, padx=12, pady=6)
        ores_box.pack()
        tk.Label(ores_box, text='Red X Clicks:', bg=SURFACE, fg=MUTED,
                 font=('Consolas', 9, 'bold')).grid(row=0, column=0, sticky='e', padx=(0, 6))
        self.live_total_ores_label = tk.Label(ores_box, text='0', bg=SURFACE, fg=GREEN,
                                              font=('Consolas', 16, 'bold'))
        self.live_total_ores_label.grid(row=0, column=1, sticky='w')
        tk.Label(ores_box, text='Banked Ore:', bg=SURFACE, fg=MUTED,
                 font=('Consolas', 9, 'bold')).grid(row=1, column=0, sticky='e', padx=(0, 6))
        self.live_banked_ore_label = tk.Label(ores_box, text='0',
                                              bg=SURFACE, fg=AMBER,
                                              font=('Consolas', 12, 'bold'))
        self.live_banked_ore_label.grid(row=1, column=1, sticky='w')
        tk.Label(ores_box, text="Inv's Banked:", bg=SURFACE, fg=MUTED,
                 font=('Consolas', 9, 'bold')).grid(row=2, column=0, sticky='e', padx=(0, 6))
        self.live_invs_banked_label = tk.Label(ores_box, text='0',
                                               bg=SURFACE, fg=MUTED,
                                               font=('Consolas', 12, 'bold'))
        self.live_invs_banked_label.grid(row=2, column=1, sticky='w')

        # ── Compact multi-bot status panel (top-right) ───────────────────────
        mini_outer = tk.Frame(stats_row, bg=BORDER, padx=1, pady=1)
        mini_outer.pack(side='right', padx=(0, 12))
        mini_f = tk.Frame(mini_outer, bg=SURFACE, padx=8, pady=4)
        mini_f.pack()

        _BOT_LABELS = ['Master', 'Bot 2', 'Bot 3', 'Bot 4', 'Bot 5']
        _HDR_FG     = [ACCENT,   MUTED,   MUTED,   MUTED,   MUTED]
        _hdr_font   = ('Consolas', 7, 'bold')
        _val_font   = ('Consolas', 8)
        _val_bold   = ('Consolas', 8, 'bold')

        # Header row \u2014 name | clk | state | bank-btn | train-btn
        # name | clk | state | Banker misclicks | bank-btn | train-btn
        for col, (txt, w) in enumerate([('', 7), ('CLK↓', 6), ('STATE', 9), ('MISS', 4), ('🏦', 3), ('💪', 3)]):
            tk.Label(mini_f, text=txt, bg=SURFACE, fg=MUTED,
                     font=('Segoe UI Emoji', 9) if col >= 4 else _hdr_font, width=w,
                     anchor='center').grid(row=0, column=col, padx=(0, 2))

        def _force_bank(idx):
            bots = getattr(self, 'bots', [])
            if idx < len(bots) and bots[idx] and getattr(bots[idx], 'running', False):
                bots[idx]._banking_request = True
                self.log_debug(f'\U0001f3e6 Force bank → Bot{idx+1}')

        def _force_train(idx):
            bots = getattr(self, 'bots', [])
            if idx < len(bots) and bots[idx] and getattr(bots[idx], 'running', False):
                b = bots[idx]
                try:
                    dest = b._pick_walkto_train_destination()
                    if dest:
                        b._type_ingame_message(f'::walkto {dest}')
                        b._walkto_sent_at = time.time()  # arm 30s dead zone — don't rotate/click this window
                        self.log_debug(f'\U0001f6b6 Force train → Bot{idx+1}: ::walkto {dest}')
                except Exception as _e:
                    self.log_debug(f'Force train error Bot{idx+1}: {_e}')

        self._mini_status_rows = []
        for i, (name, hfg) in enumerate(zip(_BOT_LABELS, _HDR_FG)):
            r = i + 1
            name_lbl = tk.Label(mini_f, text=name, bg=SURFACE, fg=hfg,
                                font=_hdr_font, width=7, anchor='w')
            name_lbl.grid(row=r, column=0, padx=(0, 2), pady=1)
            wk_lbl = tk.Label(mini_f, text='—', bg=SURFACE, fg=MUTED,
                              font=_val_font, width=6, anchor='center')
            wk_lbl.grid(row=r, column=1, padx=(0, 2))
            state_lbl = tk.Label(mini_f, text='idle', bg=SURFACE, fg=MUTED,
                                 font=_val_font, width=9, anchor='w')
            state_lbl.grid(row=r, column=2, padx=(0, 2))
            miss_lbl = tk.Label(mini_f, text='—', bg=SURFACE, fg=MUTED,
                                font=_val_font, width=4, anchor='center')
            miss_lbl.grid(row=r, column=3, padx=(0, 2))
            bank_btn = tk.Button(mini_f, text='🏦', bg='#1a2a1a', fg='#55cc55',
                                 font=('Segoe UI Emoji', 9), width=2, pady=0, padx=0,
                                 relief='flat', cursor='hand2',
                                 command=lambda _i=i: _force_bank(_i))
            bank_btn.grid(row=r, column=4, padx=(2, 1))
            train_btn = tk.Button(mini_f, text='💪', bg='#1a1a2a', fg='#7aa8ff',
                                  font=('Segoe UI Emoji', 9), width=2, pady=0, padx=0,
                                  relief='flat', cursor='hand2',
                                  command=lambda _i=i: _force_train(_i))
            train_btn.grid(row=r, column=5, padx=(1, 0))
            self._mini_status_rows.append({
                'wk': wk_lbl, 'state': state_lbl, 'miss': miss_lbl,
            })

        # ── Notebook with two tabs ───────────────────────────────────────────
        # NOTE: notebook.pack() is called AFTER the footer is packed (below)
        # so the footer always gets its space first — see end of _build_ui.
        notebook = ttk.Notebook(self.root)

        # ── Shared multi-client state (must be init'd before any bot tab) ────
        self._clients_config = self.config.get('clients', [])
        while len(self._clients_config) < 5:
            self._clients_config.append({'autologin_enabled': True})
        for _s in self._clients_config:
            _s.setdefault('autologin_enabled', True)
        self._client_window_combos = []
        self._client_enable_vars = [None] * 5
        self._client_ore_vars    = [{} for _ in range(5)]
        self._client_task_vars   = [None] * 5
        self._client_status_rows = {}

        # ── Mining (top-level, with nested sub-tabs) ─────────────────────────
        mining_tab = tk.Frame(notebook, bg=BG)
        notebook.add(mining_tab, text='  Mining (Master)  ')
        mining_sub = ttk.Notebook(mining_tab)
        mining_sub.pack(fill='both', expand=True)

        sub_bot = tk.Frame(mining_sub, bg=BG)
        mining_sub.add(sub_bot, text='  Bot  ')
        self._build_bot_tab(sub_bot)

        sub_settings = tk.Frame(mining_sub, bg=BG)
        mining_sub.add(sub_settings, text='  Settings  ')
        self._build_settings_tab(sub_settings)

        sub_antiban = tk.Frame(mining_sub, bg=BG)
        mining_sub.add(sub_antiban, text='  Anti-Ban  ')
        self._build_antiban_tab(sub_antiban)

        sub_breaks = tk.Frame(mining_sub, bg=BG)
        mining_sub.add(sub_breaks, text='  Breaks  ')
        self._build_breaks_tab(sub_breaks)

        sub_exp = tk.Frame(mining_sub, bg=BG)
        mining_sub.add(sub_exp, text='  Experimental  ')
        self._build_experimental_tab(sub_exp)

        sub_tm = tk.Frame(mining_sub, bg=BG)
        mining_sub.add(sub_tm, text='  Template Match  ')
        self._build_template_match_tab(sub_tm)

        # ── Bot2 / Bot3 / Bot4 tabs ──────────────────────────────────────────
        for _slot_idx in range(1, 5):
            _bt = tk.Frame(notebook, bg=BG)
            notebook.add(_bt, text=f'  Bot{_slot_idx + 1}  ')
            self._build_bot_slave_tab(_bt, _slot_idx)

        # Start the live-status refresh for all bot tabs
        self._schedule_clients_status_update()

        # Footer — packed BEFORE the notebook so Tkinter always reserves its
        # space first. If notebook is packed first it claims all remaining
        # height and the footer gets pushed off-screen on small/high-DPI monitors.
        footer = tk.Frame(self.root, bg=TITLE_BG, height=44)
        footer.pack(fill='x', side='bottom')
        footer.pack_propagate(False)
        tk.Frame(footer, bg=BORDER, height=1).pack(fill='x', side='top')
        btn_row = tk.Frame(footer, bg=TITLE_BG)
        btn_row.pack(expand=True)
        self.btn_start = ttk.Button(btn_row, text='▶  START', command=self.start_bot,
                                    style='Start.TButton')
        self.btn_start.pack(side='left', padx=6, pady=6)
        self.btn_stop = ttk.Button(btn_row, text='■  STOP', command=self.stop_bot,
                                   state='disabled', style='Stop.TButton')
        self.btn_stop.pack(side='left', padx=2)
        self.btn_pause = ttk.Button(btn_row, text='⏸ PAUSE', command=self.pause_bots,
                                    state='disabled', style='Util.TButton')
        self.btn_pause.pack(side='left', padx=2)
        ttk.Button(btn_row, text='SAVE', command=self.save_config,
                   style='Util.TButton').pack(side='left', padx=6)
        ttk.Button(btn_row, text='HUD', command=self._open_mini_hud,
                   style='Util.TButton').pack(side='left', padx=2)

        # Overlay mode toggle — always visible in footer
        sep = tk.Frame(btn_row, bg=BORDER, width=1, height=24)
        sep.pack(side='left', padx=8, fill='y')
        tk.Label(btn_row, text='OVERLAY:', bg=TITLE_BG, fg=MUTED,
                 font=(FONT_UI[0], 7, 'bold')).pack(side='left')
        self.overlay_mode_var = tk.StringVar(value=self.config.get('overlay_mode', 'none'))
        ttk.Radiobutton(btn_row, text='In-Game',
                        variable=self.overlay_mode_var, value='ingame').pack(side='left', padx=2)
        ttk.Radiobutton(btn_row, text='Pop-Out',
                        variable=self.overlay_mode_var, value='popout').pack(side='left', padx=2)
        ttk.Radiobutton(btn_row, text='None',
                        variable=self.overlay_mode_var, value='none').pack(side='left', padx=2)
        # Rebuild overlay when mode switches so the old window is torn down
        self.overlay_mode_var.trace_add('write', lambda *_: self._on_overlay_mode_change())

        tk.Label(btn_row, text='F6 = toggle', bg=TITLE_BG, fg=MUTED,
                 font=(FONT_UI[0], 7)).pack(side='left', padx=10)

        # Notebook — packed AFTER footer so it only fills remaining space
        notebook.pack(fill='both', expand=True, padx=6, pady=(4, 0))

    # ── Bot Tab (main working view) ──────────────────────────────────────────

    def _build_bot_tab(self, tab):
        # Debug log — fixed strip at the very bottom (not in scroll area)
        log_strip = tk.Frame(tab, bg=BG)
        log_strip.pack(side='bottom', fill='x', padx=6, pady=(0, 4))
        log_co, log_c = card(log_strip, padx=0, pady=2)
        log_co.pack(fill='x')
        # Header row with label + resize hint
        _log_hdr = tk.Frame(log_c, bg=SURFACE)
        _log_hdr.pack(fill='x', padx=6, pady=(2, 0))
        section_label(_log_hdr, 'Debug Log')
        tk.Label(_log_hdr, text='drag ↕', bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 7)).pack(side='right', padx=4)
        # Resizable debug log — user drags the top edge of log_strip to resize.
        self.debug_text = scrolledtext.ScrolledText(
            log_c, height=5,
            bg=TITLE_BG, fg=GREEN,
            insertbackground=GREEN,
            font=(FONT_UI[0], 9),
            relief='flat', bd=0,
            selectbackground=BORDER)
        self.debug_text.pack(fill='x', padx=6, pady=(0, 2))
        self.debug_text.config(state='disabled')
        # Drag-to-resize: dragging the top border of log_strip changes height.
        _drag_bar = tk.Frame(log_strip, bg=BORDER, height=4, cursor='sb_v_double_arrow')
        _drag_bar.pack(fill='x', side='top', before=log_co)
        _drag_state = {'y': 0, 'h0': 0}
        def _drag_start(e):
            _drag_state['y'] = e.y_root
            _drag_state['h0'] = self.debug_text.winfo_height()
        def _drag_move(e):
            delta = _drag_state['y'] - e.y_root  # dragging up = bigger
            line_h = self.debug_text.winfo_reqheight() // max(self.debug_text.cget('height'), 1)
            new_h = max(3, min(20, _drag_state['h0'] + delta) // max(line_h, 14))
            self.debug_text.config(height=int(new_h))
        _drag_bar.bind('<ButtonPress-1>', _drag_start)
        _drag_bar.bind('<B1-Motion>', _drag_move)
        self.log_debug('Console ready')

        # Scrollable upper area
        vscroll = tk.Scrollbar(tab, orient='vertical',
                               bg=BG, troughcolor=BG, width=18, highlightthickness=0, bd=0)
        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0, bd=0,
                           yscrollcommand=vscroll.set)
        vscroll.config(command=canvas.yview)
        vscroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)

        wrapper = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=wrapper, anchor='nw')

        def _on_wrapper_configure(e=None):
            canvas.configure(scrollregion=canvas.bbox('all'))
        def _on_canvas_configure(event):
            canvas.itemconfig(win_id, width=event.width)

        wrapper.bind('<Configure>', _on_wrapper_configure)
        canvas.bind('<Configure>', _on_canvas_configure)
        # Scope mouse wheel to this canvas only — bind_all caused Settings-tab
        # canvas to steal wheel events from the Bot tab.
        def _wheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), 'units')
        canvas.bind('<Enter>', lambda _: canvas.bind_all('<MouseWheel>', _wheel))
        canvas.bind('<Leave>', lambda _: canvas.unbind_all('<MouseWheel>'))

        left  = tk.Frame(wrapper, bg=BG)
        right = tk.Frame(wrapper, bg=BG)
        left.grid(row=0, column=0, sticky='new', padx=(0, 3))
        right.grid(row=0, column=1, sticky='new', padx=(3, 0))
        wrapper.columnconfigure(0, weight=1)
        wrapper.columnconfigure(1, weight=1)

        self._build_left(left)
        self._build_right(right)
        wrapper.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox('all'))

    def _build_left(self, p):
        # ── Game Window (TOP — pick window first, then configure mining) ───
        co_gw, c_gw = card(p, padx=0, pady=6)
        co_gw.pack(fill='x', pady=(0, 6))
        section_label(c_gw, 'Game Window')

        java_windows = self.get_java_windows()
        saved_title = self.config.get('window_title', '')
        matching = next((d for d, info in self._window_info_map.items()
                         if info['title'] == saved_title), java_windows[0] if java_windows else '')
        self.window_var = tk.StringVar(value=matching)

        self._window_combo = ttk.Combobox(c_gw, textvariable=self.window_var,
                                          values=java_windows, state='readonly')
        self._window_combo.pack(fill='x', padx=6, pady=(0, 2))
        self._window_combo.bind('<<ComboboxSelected>>', self.on_window_selected)
        self._window_combo.bind('<MouseWheel>', lambda e: 'break')

        self._win_info_label = tk.Label(c_gw, text='', bg=TITLE_BG, fg=MUTED,
                                        font=(FONT_UI[0], 8), anchor='w', padx=6)
        self._win_info_label.pack(fill='x', padx=6, pady=(0, 2))
        self._update_win_info_label()

        btn_row = tk.Frame(c_gw, bg=SURFACE)
        btn_row.pack(fill='x', padx=6, pady=(0, 2))
        ttk.Button(btn_row, text='Refresh',  command=self.refresh_windows,
                   style='Util.TButton').pack(side='left', padx=(0, 4))
        ttk.Button(btn_row, text='Bring to front',
                   command=self._bring_selected_to_front,
                   style='Util.TButton').pack(side='left', padx=(0, 4))

        self.autologin_var = tk.BooleanVar(value=self.config.get('autologin_enabled', True))
        toggle_row(c_gw, 'Auto Login', self.autologin_var).pack(anchor='w', padx=6, pady=(4, 4))

        # ── Mining Mode ──────────────────────────────────────────────────────
        co, c = card(p, padx=0, pady=6)
        co.pack(fill='x', pady=(0, 6))
        section_label(c, 'Mining Mode')

        self.powermine_var = tk.BooleanVar(value=self.config.get('powermine_enabled', False))
        self.pm_no_fatigue_var = tk.BooleanVar(value=self.config.get('powermine_disable_fatigue', False))
        def _on_pm_nf(*_):
            self.config['powermine_disable_fatigue'] = bool(self.pm_no_fatigue_var.get())
            try: self.save_config()
            except Exception: pass
        self.pm_no_fatigue_var.trace_add('write', _on_pm_nf)


        self.multi_client_var = tk.BooleanVar(value=self.config.get('multi_client_mode', False))

        _pm_row = tk.Frame(c, bg=SURFACE)
        _pm_row.pack(anchor='w', padx=8, pady=(0, 2))
        self._powermine_toggle = Toggle(_pm_row, self.powermine_var, bg=SURFACE)
        self._powermine_toggle.pack(side='left', padx=(0, 6))
        tk.Label(_pm_row, text='Powermine (indefinitely)', bg=SURFACE, fg=FG,
                 font=FONT_UI, anchor='w').pack(side='left')
        # Disable fatigue — inline mini toggle to the right of powermine
        tk.Frame(_pm_row, bg=SURFACE, width=10).pack(side='left')
        Toggle(_pm_row, self.pm_no_fatigue_var, bg=SURFACE).pack(side='left', padx=(0, 4))
        tk.Label(_pm_row, text='No fatigue', bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 8), anchor='w').pack(side='left')

        # Multi-client toggle row (already present)
        _mc_row = tk.Frame(c, bg=SURFACE)
        _mc_row.pack(anchor='w', padx=8, pady=(4, 2))
        Toggle(_mc_row, self.multi_client_var, bg=SURFACE).pack(side='left', padx=(0, 8))
        tk.Label(_mc_row, text='Multi-Client  (1-5 clients)', bg=SURFACE, fg=FG,
                 font=FONT_UI, anchor='w').pack(side='left')
        tk.Label(c, text='Enable Bot2/3/4/5 tabs and assign windows. Disables park-mouse & hover.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=440, justify='left').pack(anchor='w', padx=22, pady=(0, 4))

        # Mouse movement mode — controls how cursor travels between windows in multi-client
        ms = self.config.get('mouse_settings', {})
        _mmm_saved = ms.get('mouse_movement_mode', 'teleport')
        self.mouse_movement_mode_var = tk.StringVar(value=_mmm_saved)
        mmm_row = tk.Frame(c, bg=SURFACE)
        mmm_row.pack(fill='x', padx=8, pady=(2, 2))
        tk.Label(mmm_row, text='Window hop', bg=SURFACE, fg=MUTED,
                 font=FONT_UI, width=10, anchor='w').pack(side='left')
        for _mmv, _mml in [('teleport', 'Teleport (instant)'), ('human', 'Travel (human move)')]:
            ttk.Radiobutton(mmm_row, text=_mml,
                            variable=self.mouse_movement_mode_var,
                            value=_mmv).pack(side='left', padx=(0, 10))
        tk.Label(c, text='Teleport = instant cursor hop between windows  |  Travel = mouse physically moves across screen',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=420, justify='left').pack(anchor='w', padx=22, pady=(0, 6))

        # (Speed mode buttons moved to 🖱 Mouse Settings section below.)
        # Var init happens there; stub it here so downstream interlocks don't crash.
        if not hasattr(self, 'mining_speed_var'):
            _saved_mode = self.config.get('speed_mode')
            if _saved_mode not in ('ultra_fast', 'super_fast', 'fast', 'lazy', 'super_lazy'):
                _saved_mode = 'fast' if self.config.get('fast_mining_enabled', True) else 'lazy'
            self.config['speed_mode'] = _saved_mode
            self.config['fast_mining_enabled'] = (_saved_mode == 'fast')
            self.mining_speed_var = tk.StringVar(value=_saved_mode)

        # Mouse-behavior toggles (Lazy idle, Park outside, Hover, Direct-to-ore)
        # moved to dedicated Mouse Settings section below Mining Mode.
        # stop_on_full_var init — widget lives in Experimental tab.
        self.stop_on_full_var = tk.BooleanVar(value=False)
        def _stop_bank_interlock(*_):
            if self.banking_enabled_var.get() and self.stop_on_full_var.get():
                self.stop_on_full_var.set(False)
                try: self.log_debug('⚠ Banking ON → Stop-when-full forced OFF')
                except Exception: pass
        self.stop_on_full_var.trace_add('write', _stop_bank_interlock)

        self.pause_on_user_input_var = tk.BooleanVar(
            value=bool(self.config.get('pause_on_user_input', True)))
        toggle_row(c, '⏸ Pause bot while user input detected (resumes 2s after last input)',
                   self.pause_on_user_input_var).pack(anchor='w', padx=8, pady=(2, 2))
        tk.Label(c,
                 text='Pauses the bot when you move the mouse or press a key. '
                      'Resumes automatically once you stop interacting for 2 seconds. '
                      'Distinguishes your input from the bot\'s own clicks via tick comparison.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=560, justify='left'
                 ).pack(anchor='w', padx=14, pady=(0, 4))

        # (Banking section moved below Mouse Settings — see card(p, ...) further down.)
        # Var init here so interlocks wired below don't crash on first reference.
        self.banking_enabled_var = tk.BooleanVar(value=self.config.get('banking_enabled', False))
        # Interlocks wired here; banking UI card is built after Mouse Settings (scroll down).
        def _pm_bank_interlock_pm(*_):
            if self.powermine_var.get() and self.banking_enabled_var.get():
                self.banking_enabled_var.set(False)
                try: self.log_debug('⚠ Powermine ON → Banking forced OFF (incompatible)')
                except Exception: pass
        def _pm_bank_interlock_bk(*_):
            if self.banking_enabled_var.get() and self.powermine_var.get():
                self.powermine_var.set(False)
                try: self.log_debug('⚠ Banking ON → Powermine forced OFF (incompatible)')
                except Exception: pass
            if self.banking_enabled_var.get() and self.stop_on_full_var.get():
                self.stop_on_full_var.set(False)
                try: self.log_debug('⚠ Banking ON → Stop-when-full forced OFF')
                except Exception: pass
        self.powermine_var.trace_add('write', _pm_bank_interlock_pm)
        self.banking_enabled_var.trace_add('write', _pm_bank_interlock_bk)
        # (Banking UI widgets are built after Mouse Settings below.)

        # ── Mouse Settings (NEW dedicated section) ──────────────────────────
        co_ms, c_ms = card(p, padx=0, pady=6)
        co_ms.pack(fill='x', pady=(0, 6))
        section_label(c_ms, '🖱 Mouse Settings')

        # Speed mode buttons
        _saved_mode = self.config.get('speed_mode')
        if _saved_mode not in ('ultra_fast', 'super_fast', 'fast', 'lazy', 'super_lazy'):
            _saved_mode = 'fast' if self.config.get('fast_mining_enabled', True) else 'lazy'
        self.config['speed_mode'] = _saved_mode
        self.config['fast_mining_enabled'] = (_saved_mode == 'fast')
        self.mining_speed_var = tk.StringVar(value=_saved_mode)
        _speed_btns = {}
        _speed_defs = [
            ('ultra_fast', 'Ultra-Fast', '0.05-0.25ms'),
            ('super_fast', 'Super-Fast', '50-300 ms'),
            ('fast',       'Fast',       '800-1200 ms'),
            ('lazy',       'Lazy',       '1.2-2.4 s'),
            ('super_lazy', 'Super Lazy', '10-30 s'),
        ]
        def _refresh_speed_btns(*_):
            active = self.mining_speed_var.get()
            for val, btn in _speed_btns.items():
                on = (val == active)
                btn.config(bg=GREEN if on else BORDER, fg=BG if on else MUTED, relief='flat')
        def _pick_speed(val):
            self.mining_speed_var.set(val)
            _refresh_speed_btns()
            self._on_speed_change()
        _sr1 = tk.Frame(c_ms, bg=SURFACE)
        _sr1.pack(anchor='w', padx=8, pady=(4, 2))
        for val, label, detail in _speed_defs[:2]:
            btn = tk.Label(_sr1, text=f'{label}\n{detail}', bg=BORDER, fg=MUTED,
                           font=('Consolas', 8, 'bold'), padx=10, pady=4,
                           cursor='hand2', relief='flat', anchor='center', justify='center', width=13)
            btn.pack(side='left', padx=(0, 6))
            btn.bind('<Button-1>', lambda _e, v=val: _pick_speed(v))
            _speed_btns[val] = btn
        _sr2 = tk.Frame(c_ms, bg=SURFACE)
        _sr2.pack(anchor='w', padx=8, pady=(0, 6))
        for val, label, detail in _speed_defs[2:]:
            btn = tk.Label(_sr2, text=f'{label}\n{detail}', bg=BORDER, fg=MUTED,
                           font=('Consolas', 8, 'bold'), padx=10, pady=4,
                           cursor='hand2', relief='flat', anchor='center', justify='center', width=13)
            btn.pack(side='left', padx=(0, 6))
            btn.bind('<Button-1>', lambda _e, v=val: _pick_speed(v))
            _speed_btns[val] = btn
        _refresh_speed_btns()
        self.mining_speed_var.trace_add('write', _refresh_speed_btns)
        tk.Frame(c_ms, bg=BORDER, height=1).pack(fill='x', padx=6, pady=(0, 6))

        # Lazy idle pause
        self.lazy_idle_pause_var = tk.BooleanVar(value=self.config.get('lazy_idle_pause_enabled', False))
        toggle_row(c_ms, 'Lazy idle pause (every 5–25 clicks, park mouse 5–20s)',
                   self.lazy_idle_pause_var).pack(anchor='w', padx=8, pady=(0, 2))

        # Instant mouse movement — disable bezier curves / overshoot / hesitation
        self.instant_movement_var = tk.BooleanVar(value=self.config.get('instant_movement', False))
        self.instant_movement_var.trace_add('write',
            lambda *_: self.config.update({'instant_movement': self.instant_movement_var.get()}))
        toggle_row(c_ms, 'Instant mouse movement (no curves/hesitation; click timing stays randomized)',
                   self.instant_movement_var).pack(anchor='w', padx=8, pady=(0, 2))

        # Park mouse outside — only usable in Lazy mode
        self.mouse_outside_var = tk.BooleanVar(value=self.config.get('mouse_outside_window', False))
        self.mouse_outside_var.trace_add('write', lambda *_: self._on_mouse_outside_change())
        _park_row = tk.Frame(c_ms, bg=SURFACE)
        _park_row.pack(anchor='w', padx=8, pady=(0, 2))
        self._mouse_outside_toggle = Toggle(_park_row, self.mouse_outside_var, bg=SURFACE)
        self._mouse_outside_toggle.pack(side='left', padx=(0, 8))
        tk.Label(_park_row, text='Park mouse outside window after click  (Lazy only)',
                 bg=SURFACE, fg=FG, font=FONT_UI, anchor='w').pack(side='left', fill='x', expand=True)
        if self.config.get('speed_mode', 'fast') in ('ultra_fast', 'fast', 'super_fast') or self.config.get('fast_mining_enabled', True):
            self._mouse_outside_toggle.set_disabled(True)

        # Hover mouse on next Ore
        self.config['hover_mode_enabled'] = False
        self.hover_mode_var = tk.BooleanVar(value=False)
        self.hover_mode_var.trace_add('write', self._on_hover_mode_change)
        toggle_row(c_ms, 'Hover mouse on next Ore',
                   self.hover_mode_var).pack(anchor='w', padx=8, pady=(4, 0))
        tk.Label(c_ms, text='After clicking ore A, glide mouse to ore B and click the instant A depletes.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=400, justify='left').pack(anchor='w', padx=22, pady=(0, 4))

        # Direct-to-Ore (Multi-Client)
        self.direct_ore_var = tk.BooleanVar(
            value=self.config.get('direct_ore_preposition', False))
        toggle_row(c_ms, '🎯 Direct-to-Ore  (Multi-Client window hop)',
                   self.direct_ore_var).pack(anchor='w', padx=8, pady=(0, 0))
        tk.Label(c_ms, text='Pre-position mouse on the exact detected ore in the next window '
                          'instead of window centre ±50px.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=400, justify='left').pack(anchor='w', padx=22, pady=(0, 6))

        # Quick-Turn on Empty Ores (Multi-Client)
        self.quick_turn_var = tk.BooleanVar(
            value=self.config.get('quick_turn_no_ore_enabled', False))
        toggle_row(c_ms, '⚡ Quick-Turn on Empty Ores  (Multi-Client)',
                   self.quick_turn_var).pack(anchor='w', padx=8, pady=(0, 0))
        tk.Label(c_ms, text='When ores are empty, hands off this client\'s turn after a random '
                          '1.5–3.5 s (re-rolled each visit) instead of waiting up to 30 s. '
                          'No blocking penalty — the bot re-enters rotation immediately. '
                          'Applies to all bot clients.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=400, justify='left').pack(anchor='w', padx=22, pady=(0, 6))

        # ── Banking (bottom of left column) ────────────────────────────────────
        co_bk, c_bk = card(p, padx=0, pady=6)
        co_bk.pack(fill='x', pady=(0, 6))
        section_label(c_bk, '🏦 Banking')
        toggle_row(c_bk, 'When inventory full',
                   self.banking_enabled_var).pack(anchor='w', padx=8, pady=(2, 2))
        tk.Label(c_bk,
                 text='When inventory hits 30/30: ::walkto bank → click banker (NPCS_TEST1) → '
                      'click "mine" preset → random ESC or close-X → ::walkto train. '
                      'Banker detection runs WITHOUT camera rotation.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=560, justify='left'
                 ).pack(anchor='w', padx=14, pady=(0, 4))
        _clicks_row = tk.Frame(c_bk, bg=SURFACE)
        _clicks_row.pack(anchor='w', padx=14, pady=(0, 6))
        tk.Label(_clicks_row, text='Clicks until bank:', bg=SURFACE, fg=FG,
                 font=FONT_UI).pack(side='left')
        tk.Label(_clicks_row, text='Min', bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 8)).pack(side='left', padx=(8, 2))
        self.bank_clicks_min_var = tk.StringVar(
            value=str(self.config.get('bank_clicks_min', ''))
        )
        ttk.Entry(_clicks_row, textvariable=self.bank_clicks_min_var, width=5).pack(side='left')
        tk.Label(_clicks_row, text='Max', bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 8)).pack(side='left', padx=(8, 2))
        self.bank_clicks_max_var = tk.StringVar(
            value=str(self.config.get('bank_clicks_max', ''))
        )
        ttk.Entry(_clicks_row, textvariable=self.bank_clicks_max_var, width=5).pack(side='left')
        tk.Label(_clicks_row, text='(blank = default 32–38)', bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 8, 'italic')).pack(side='left', padx=(8, 0))
        # Loadout 1 slot
        _mine_row = tk.Frame(c_bk, bg=SURFACE)
        _mine_row.pack(fill='x', padx=14, pady=(0, 6))
        tk.Label(_mine_row, text='Loadout 1:', bg=SURFACE, fg=FG, font=FONT_UI).pack(side='left')
        def _fmt_xy(xy):
            if not xy: return '— not set —'
            return f'X={int(xy[0])}  Y={int(xy[1])}  (rel to window)'
        _saved_bk = (self.config.get('bank_mine_slot_xy_rel') or self.config.get('bank_mine_slot_xy'))
        self._mine_slot_xy_label = tk.Label(_mine_row, text=_fmt_xy(_saved_bk),
            bg=BORDER, fg=ACCENT, font=('Consolas', 9, 'bold'), padx=8)
        self._mine_slot_xy_label.pack(side='left', padx=(8, 8))
        def _save_mine_slot(x, y):
            rel_x, rel_y = int(x), int(y)
            try:
                title = (self.config.get('window_title') or '').strip()
                if title:
                    hwnd = win32gui.FindWindow(None, title)
                    if hwnd:
                        cl_left, cl_top = win32gui.ClientToScreen(hwnd, (0, 0))
                        rel_x = int(x) - cl_left
                        rel_y = int(y) - cl_top
            except Exception:
                pass
            self.config['bank_mine_slot_xy_rel'] = [rel_x, rel_y]
            self.config.pop('bank_mine_slot_xy', None)
            self._mine_slot_xy_label.config(text=_fmt_xy([rel_x, rel_y]))
            try: self.save_config()
            except Exception: pass
        def _clear_mine_slot():
            self.config['bank_mine_slot_xy_rel'] = None
            self.config.pop('bank_mine_slot_xy', None)
            self._mine_slot_xy_label.config(text='— not set —')
            try: self.save_config()
            except Exception: pass
        ttk.Button(_mine_row, text='Set position',
                   command=lambda: self._capture_screen_click(_save_mine_slot)
                   ).pack(side='left', padx=(0, 4))
        ttk.Button(_mine_row, text='Clear', command=_clear_mine_slot).pack(side='left')
        tk.Label(c_bk,
                 text='💡 Click "Set position" then click the Loadout 1 button in the bank window. '
                      'The bot will use these exact coords (±7px jitter) — no template matching needed.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=560, justify='left'
                 ).pack(anchor='w', padx=14, pady=(0, 6))
        _M_BANK_SHORT = [
            '', 'None', 'Varrock East', 'Varrock West', 'Falador East', 'Falador West',
            'Edgeville', 'Draynor', 'Al Kharid', 'Catherby', 'Seers',
            'Ardougne North', 'Ardougne South',
        ]
        _M_BANK_FULL = [
            '', 'None', 'Bank (Varrock East)', 'Bank (Varrock West)',
            'Bank (Falador East)', 'Bank (Falador West)',
            'Bank (Edgeville)', 'Bank (Draynor)', 'Bank (Al Kharid)',
            'Bank (Catherby)', 'Bank (Seers)',
            'Bank (Ardougne North)', 'Bank (Ardougne South)',
        ]
        def _bank_dest_row(parent, label, key_prefix, slots):
            row = tk.Frame(parent, bg=SURFACE)
            row.pack(fill='x', padx=8, pady=(2, 2))
            tk.Label(row, text=label, bg=SURFACE, fg=FG, font=FONT_UI,
                     width=14, anchor='w').pack(side='left')
            grid = tk.Frame(row, bg=SURFACE)
            grid.pack(side='left', fill='x', expand=True)
            vars_out = {}
            for i, (suffix, ph, presets) in enumerate(slots):
                ck = f'{key_prefix}_{suffix}'
                v = tk.StringVar(value=self.config.get(ck, ''))
                if presets:
                    ent = ttk.Combobox(grid, textvariable=v, values=presets,
                                       state='normal', width=20)
                    # Block mousewheel so accidental scrolling never changes the value.
                    ent.bind('<MouseWheel>', lambda e: 'break')
                    ent.bind('<Button-4>',   lambda e: 'break')
                    ent.bind('<Button-5>',   lambda e: 'break')
                else:
                    ent = ttk.Entry(grid, textvariable=v, style='TEntry', width=22)
                ent.grid(row=i // 2, column=i % 2, sticky='ew', padx=2, pady=1)
                grid.columnconfigure(i % 2, weight=1)
                def _on_change(*_a, _k=ck, _v=v):
                    self.config[_k] = _v.get()
                    try: self.save_config()
                    except Exception: pass
                v.trace_add('write', _on_change)
                vars_out[suffix] = v
                ttk.Label(grid, text=ph, background=SURFACE, foreground=MUTED,
                          font=(FONT_UI[0], 7, 'italic')).grid(
                          row=i // 2, column=(i % 2) + 2, sticky='w', padx=(2, 6))
            return vars_out
        _MASTER_BANK_SLOTS = [
            ('a', 'short (city)', _M_BANK_SHORT),
            ('b', 'full (Bank (...))', _M_BANK_FULL),
            ('user', 'user-set string', None),
            ('xy', 'X Y coords  e.g. 1024 1003', None),
        ]
        _MASTER_TRAIN_SLOTS = [
            ('user', 'user-set string', None),
            ('xy', 'X Y coords  e.g. 1024 1003', None),
        ]
        self._banking_dest_vars  = _bank_dest_row(c_bk, 'Bank destination', 'walkto_dest1',  _MASTER_BANK_SLOTS)
        self._banking_train_vars = _bank_dest_row(c_bk, 'Training area',    'walkto_train1', _MASTER_TRAIN_SLOTS)
        tk.Label(c_bk,
                  text='Master destinations use the first non-blank entry in order. '
                      'Slave bots with Mimic Master ON follow that same resolved Bank/Training choice. '
                      'Turn Mimic Master OFF on a slave to use its own custom entries.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=560, justify='left'
                 ).pack(anchor='w', padx=14, pady=(2, 4))

        # (Game Window section moved to TOP of this column.)

        # Ores + Priority — combined drag-to-reorder panel
        co, c = card(p, padx=0, pady=6)
        co.pack(fill='x', pady=(0, 6))
        # Section header with "show empty" toggle on the same line
        hdr_row = tk.Frame(c, bg=SURFACE)
        hdr_row.pack(fill='x', padx=8, pady=(4, 2))
        tk.Label(hdr_row, text='ORE SELECTION & PRIORITY', bg=SURFACE, fg=ACCENT,
                 font=('Segoe UI', 9, 'bold')).pack(side='left')
        self.show_empty_var = tk.BooleanVar(value=self.config.get('show_empty_ore', False))
        self.show_empty_var.trace_add('write', lambda *_: self.config.update({'show_empty_ore': self.show_empty_var.get()}))
        se_row = tk.Frame(hdr_row, bg=SURFACE)
        se_row.pack(side='right')
        Toggle(se_row, self.show_empty_var, bg=SURFACE).pack(side='left', padx=(0, 4))
        tk.Label(se_row, text='Show Empty Rocks', bg=SURFACE, fg=FG,
                 font=(FONT_UI[0], 8)).pack(side='left')
        tk.Frame(c, bg=BORDER, height=1).pack(fill='x', padx=6, pady=(0, 6))
        tk.Label(c, text='Higher tier ores are always prioritised automatically.',
                 bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 8, 'italic')).pack(anchor='w', padx=10, pady=(0, 4))

        self.checkbox_vars = {}
        # Tier order low→high: Tin, Copper, Iron, Coal, Mithril, Adamantite
        # Priority is automatic (adamantite > mithril > coal > iron > copper > tin) — no drag needed.
        _ORE_LIST_MASTER = ['tin_rock', 'copper_rock', 'iron_rock', 'coal_rock', 'mithril_rock', 'adamantite_rock']
        _ORE_LABELS_MASTER = {
            'tin_rock': 'Tin', 'copper_rock': 'Copper', 'iron_rock': 'Iron',
            'coal_rock': 'Coal',
            'mithril_rock': 'Mithril', 'adamantite_rock': 'Addy',
        }
        for ore in _ORE_LIST_MASTER:
            self.checkbox_vars[ore] = tk.BooleanVar(
                value=self.config['ore_checkboxes'].get(ore, True))
        ore_check_row = tk.Frame(c, bg=SURFACE)
        ore_check_row.pack(fill='x', padx=8, pady=(0, 6))
        for ore in _ORE_LIST_MASTER:
            tk.Checkbutton(ore_check_row, text=_ORE_LABELS_MASTER[ore],
                           variable=self.checkbox_vars[ore],
                           bg=SURFACE, fg=FG, selectcolor=BORDER,
                           activebackground=SURFACE, activeforeground=FG,
                           font=FONT_UI).pack(side='left', padx=4)

        # Detection confidence — lives here so it's next to ore selection
        tk.Frame(c, bg=BORDER, height=1).pack(fill='x', padx=6, pady=(0, 4))
        self.confidence_var = tk.DoubleVar(
            value=self.config.get('detection_settings', {}).get('confidence_threshold', 0.75))
        crow = tk.Frame(c, bg=SURFACE)
        crow.pack(fill='x', padx=8, pady=(0, 6))
        tk.Label(crow, text='Confidence', bg=SURFACE, fg=MUTED,
                 font=FONT_UI, width=11, anchor='w').pack(side='left')
        self.confidence_value_label = tk.Label(
            crow, text=f'{self.confidence_var.get():.2f}',
            bg=BORDER, fg=ACCENT, font=('Consolas', 8, 'bold'), width=5)
        self.confidence_value_label.pack(side='right', padx=4)
        ttk.Scale(crow, from_=0.05, to=1.0, orient='horizontal',
                  variable=self.confidence_var,
                  command=self.on_confidence_change).pack(side='left', fill='x', expand=True)

        # overlay_mode_var is created in the footer (always visible)
        # just make sure the variable exists before the footer is built
        if not hasattr(self, 'overlay_mode_var'):
            self.overlay_mode_var = tk.StringVar(value=self.config.get('overlay_mode', 'none'))

    def _build_right(self, p):
        # Camera Rotation — top-right
        co, c = card(p, padx=0, pady=6)
        co.pack(fill='x', pady=(0, 6))
        section_label(c, 'Camera Rotation')
        self.camera_rotation_var = tk.BooleanVar(value=self.config.get('camera_rotation_enabled', True))
        _cam_row = tk.Frame(c, bg=SURFACE)
        _cam_row.pack(anchor='w', padx=8, pady=(0, 2))
        self._cam_rot_toggle = Toggle(_cam_row, self.camera_rotation_var, bg=SURFACE)
        self._cam_rot_toggle.pack(side='left', padx=(0, 8))
        tk.Label(_cam_row, text='Auto-rotate/zoom camera when no ores found',
                 bg=SURFACE, fg=FG, font=FONT_UI, anchor='w').pack(side='left', fill='x', expand=True)

        self.camera_rotate_only_var = tk.BooleanVar(value=self.config.get('camera_rotate_only', False))
        _cam_row2 = tk.Frame(c, bg=SURFACE)
        _cam_row2.pack(anchor='w', padx=8, pady=(0, 6))
        self._cam_rot_only_toggle = Toggle(_cam_row2, self.camera_rotate_only_var, bg=SURFACE)
        self._cam_rot_only_toggle.pack(side='left', padx=(0, 8))
        tk.Label(_cam_row2, text='Rotate camera only  (left/right, no zoom)',
                 bg=SURFACE, fg=FG, font=FONT_UI, anchor='w').pack(side='left', fill='x', expand=True)

        # Mutual exclusion: enabling rotate-only forces auto-rotate/zoom off
        # and disables its toggle (they describe conflicting behaviours).
        # Enabling auto-rotate/zoom clears rotate-only.
        def _on_rotate_only_changed(*_):
            if self.camera_rotate_only_var.get():
                self.camera_rotation_var.set(False)
                self._cam_rot_toggle.set_disabled(True)
            else:
                # Re-enable auto-rotate toggle unless fixed spots mode is locking it.
                if not getattr(self, 'fixed_spot_mode_var', tk.BooleanVar()).get():
                    self._cam_rot_toggle.set_disabled(False)

        def _on_auto_rotate_changed(*_):
            if self.camera_rotation_var.get():
                self.camera_rotate_only_var.set(False)

        self.camera_rotate_only_var.trace_add('write', _on_rotate_only_changed)
        self.camera_rotation_var.trace_add('write', _on_auto_rotate_changed)
        # Apply initial state so UI reflects config on load.
        _on_rotate_only_changed()

        # Fixed Ore Spots — top-right
        co, c = card(p, padx=0, pady=6)
        co.pack(fill='x', pady=(0, 6))
        section_label(c, 'Fixed Ore Spots')
        tk.Label(c, text='Disable camera rotation + select up to 3 spots to lock the bot in place.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=260, justify='left').pack(anchor='w', padx=10, pady=(0, 6))
        self._fixed_spots = list(self.config.get('fixed_ore_spots', []))
        spot_row = tk.Frame(c, bg=SURFACE)
        spot_row.pack(fill='x', padx=8, pady=(0, 2))
        self.spot_btn_label = tk.StringVar(value=self._spot_btn_text())
        ttk.Button(spot_row, textvariable=self.spot_btn_label,
                   command=self._open_spot_selector,
                   style='Util.TButton').pack(anchor='w')
        ttk.Button(spot_row, text='Clear spots',
                   command=self._clear_fixed_spots,
                   style='Util.TButton').pack(anchor='w', pady=(3, 4))

        # Fixed Spots Mode toggle — disables camera rotation when on.
        # Only auto-enable if fixed_ore_spots_enabled was explicitly saved True
        # in config. Stale spot coordinates with no enabled flag must NOT
        # lock camera rotation off on reload.
        _has_spots = bool(self._fixed_spots) and self.config.get('fixed_ore_spots_enabled', False)
        _cam_off = not self.config.get('camera_rotation_enabled', True)
        self.fixed_spot_mode_var = tk.BooleanVar(value=(_has_spots and _cam_off))
        toggle_row(c, 'Fixed Spots Mode  (locks rotation off)',
                   self.fixed_spot_mode_var).pack(anchor='w', padx=8, pady=(4, 6))

        def _on_fixed_spot_mode(*_):
            if self.fixed_spot_mode_var.get():
                self.camera_rotation_var.set(False)
                self._cam_rot_toggle.set_disabled(True)
            else:
                self._cam_rot_toggle.set_disabled(False)
        self.fixed_spot_mode_var.trace_add('write', _on_fixed_spot_mode)
        # Apply initial state
        _on_fixed_spot_mode()

    # ── Settings Tab ─────────────────────────────────────────────────────────

    def _build_settings_tab(self, tab):
        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0, bd=0)
        vscroll = tk.Scrollbar(tab, orient='vertical', command=canvas.yview,
                               bg=BG, troughcolor=BG, width=18, highlightthickness=0, bd=0)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)

        body = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=body, anchor='nw')

        def _resize(e=None):
            canvas.configure(scrollregion=canvas.bbox('all'))
            canvas.itemconfig(win_id, width=canvas.winfo_width())
        body.bind('<Configure>', _resize)
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(win_id, width=e.width))
        def _wheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), 'units')
        canvas.bind('<Enter>', lambda _: canvas.bind_all('<MouseWheel>', _wheel))
        canvas.bind('<Leave>', lambda _: canvas.unbind_all('<MouseWheel>'))

        # Profiles (named config snapshots — top of Settings)
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(6, 6))
        section_label(c, 'Profiles')
        tk.Label(c, text='Save and recall named configs '
                         '(e.g. "powerminetincopper", "faladorironbank").',
                 bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 8, 'italic')).pack(anchor='w', padx=8, pady=(0, 4))
        prow = tk.Frame(c, bg=SURFACE)
        prow.pack(fill='x', padx=8, pady=(0, 6))
        self._profiles_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          'profiles')
        os.makedirs(self._profiles_dir, exist_ok=True)
        self.profile_var = tk.StringVar(value='')
        self._profile_combo = ttk.Combobox(prow, textvariable=self.profile_var,
                                           values=self._list_profiles(),
                                           state='normal', width=24)
        self._profile_combo.pack(side='left', padx=(0, 4))
        self._profile_combo.bind('<MouseWheel>', lambda e: 'break')
        ttk.Button(prow, text='Save as',
                   command=self._profile_save,
                   style='Util.TButton').pack(side='left', padx=(0, 4))
        ttk.Button(prow, text='Load',
                   command=self._profile_load,
                   style='Util.TButton').pack(side='left', padx=(0, 4))
        ttk.Button(prow, text='Delete',
                   command=self._profile_delete,
                   style='Util.TButton').pack(side='left')

        self.overlay_thickness_var = tk.IntVar(value=1)  # fixed at 1, no UI

        # Mouse — simplified: only Profile Seed is user-facing.
        # Min/max delays and curve strength are kept as hidden StringVars
        # so save_config / mouse profile randomization still work, but no UI.
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(0, 6))
        section_label(c, 'Mouse Profile')
        ms = self.config.get('mouse_settings', {})
        self.min_delay_var   = tk.StringVar(value=str(ms.get('min_delay_ms', 50)))
        self.max_delay_var   = tk.StringVar(value=str(ms.get('max_delay_ms', 250)))
        self.human_curve_var = tk.StringVar(value=str(ms.get('human_curve_strength', 0.7)))

        seed_val = ms.get('mouse_seed', None)
        self.mouse_seed_var = tk.IntVar(value=seed_val if seed_val is not None else random.randint(0, 9999))
        sr = tk.Frame(c, bg=SURFACE)
        sr.pack(fill='x', padx=8, pady=(4, 4))
        tk.Label(sr, text='Profile Seed:', bg=SURFACE, fg=MUTED,
                 font=FONT_UI).pack(side='left')
        self.seed_label = tk.Label(sr, textvariable=self.mouse_seed_var,
                                   bg=BORDER, fg=ACCENT, font=('Consolas', 11, 'bold'),
                                   width=6, padx=6, pady=2)
        self.seed_label.pack(side='left', padx=8)
        ttk.Button(sr, text='🎲 Random',
                   command=lambda: self.mouse_seed_var.set(random.randint(0, 9999))
                   ).pack(side='left')
        tk.Label(c,
                 text='Each random seed = a unique mouse personality (overshoot, jitter, '
                      'click-hold timing, hesitations). Click Random to roll a new one.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=440, justify='left'
                 ).pack(anchor='w', padx=8, pady=(0, 6))

        # Click Verification toggle (red-X marker check after every click).
        self.click_verify_var = tk.BooleanVar(
            value=bool(self.config.get('click_verify_enabled', False)))
        toggle_row(c, 'Verify clicks via red-X marker (re-click if missing)',
                   self.click_verify_var).pack(anchor='w', padx=8, pady=(4, 2))
        tk.Label(c,
                 text='Polls the click area for the RSC red-X marker after each click. '
                      'If not seen, re-clicks up to 2 times. Adds ~50-400ms per click.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=440, justify='left'
                 ).pack(anchor='w', padx=8, pady=(0, 6))

        def _save_cv(*_):
            self.config['click_verify_enabled'] = bool(self.click_verify_var.get())
            try: self.save_config()
            except Exception: pass
        self.click_verify_var.trace_add('write', _save_cv)

        # (Mouse movement mode now lives in Bot tab)

        # Verbose debug toggle — moved up since anti-ban section now lives in its own tab
        self.verbose_debug_var = tk.BooleanVar(value=self.config.get('verbose_debug', False))
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(0, 6))
        section_label(c, 'Debug')
        toggle_row(c, 'Verbose debug logging',
                   self.verbose_debug_var).pack(anchor='w', padx=8, pady=(2, 4))
        tk.Label(c, text='→ Anti-Ban Features are in their own tab.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic')
                 ).pack(anchor='w', padx=8, pady=(0, 6))

        # YOLO Models — at the bottom of Settings
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(0, 6))
        section_label(c, 'YOLO Models')
        _mf = tk.Frame(c, bg=SURFACE)
        _mf.pack(anchor='w', padx=8, pady=(0, 6))
        for _pt in ('best.pt', 'NPCS_TEST1.pt'):
            tk.Label(_mf, text=f'● {_pt}', bg=SURFACE, fg=MUTED,
                     font=('Consolas', 8)).pack(anchor='w', pady=1)
        self.main_model_var = tk.BooleanVar(value=True)  # kept for compat

        # Theme — at the bottom of Settings; changing it restarts the GUI.
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(0, 6))
        section_label(c, 'Theme')
        tk.Label(c, text='⚠ Changing theme will restart the bot GUI',
                 bg=SURFACE, fg=AMBER,
                 font=(FONT_UI[0], 8, 'bold')).pack(anchor='w', padx=8, pady=(0, 4))
        tr = tk.Frame(c, bg=SURFACE)
        tr.pack(fill='x', padx=8, pady=2)
        tk.Label(tr, text='Preset', bg=SURFACE, fg=MUTED,
                 font=FONT_UI, width=10, anchor='w').pack(side='left')
        self.theme_var = tk.StringVar(value=self.config.get('theme', 'Cobalt'))
        theme_combo = ttk.Combobox(tr, textvariable=self.theme_var,
                                   values=list(THEMES.keys()), state='readonly', width=20)
        theme_combo.pack(side='left', padx=4)
        theme_combo.bind('<<ComboboxSelected>>', self._on_theme_change)
        theme_combo.bind('<MouseWheel>', lambda e: 'break')
        fr = tk.Frame(c, bg=SURFACE)
        fr.pack(fill='x', padx=8, pady=(2, 6))
        tk.Label(fr, text='Font', bg=SURFACE, fg=MUTED,
                 font=FONT_UI, width=10, anchor='w').pack(side='left')
        self.font_var = tk.StringVar(value=self.config.get('font', FONT_UI[0]))
        font_combo = ttk.Combobox(fr, textvariable=self.font_var,
                                  values=FONT_CHOICES, state='readonly', width=20)
        font_combo.pack(side='left', padx=4)
        font_combo.bind('<<ComboboxSelected>>', self._on_theme_change)
        font_combo.bind('<MouseWheel>', lambda e: 'break')

    def _build_breaks_tab(self, tab):
        """Long Breaks tab — configure session length and break duration."""
        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0, bd=0)
        vscroll = tk.Scrollbar(tab, orient='vertical', command=canvas.yview,
                               bg=BG, troughcolor=BG, width=18, highlightthickness=0, bd=0)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        body = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=body, anchor='nw')
        def _resize(e=None):
            canvas.configure(scrollregion=canvas.bbox('all'))
            canvas.itemconfig(win_id, width=canvas.winfo_width())
        body.bind('<Configure>', _resize)
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(win_id, width=e.width))
        def _wheel(e): canvas.yview_scroll(int(-1*(e.delta/120)), 'units')
        canvas.bind('<Enter>', lambda _: canvas.bind_all('<MouseWheel>', _wheel))
        canvas.bind('<Leave>', lambda _: canvas.unbind_all('<MouseWheel>'))

        bs = self.config.get('break_settings', {})
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(8, 6))
        section_label(c, 'Long Breaks')
        tk.Label(c,
                 text='After running for a random time in the session interval,\n'
                      'the bot pauses for a random duration in the break range.',
                 bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 8, 'italic'), justify='left'
                 ).pack(anchor='w', padx=8, pady=(0, 6))

        if not hasattr(self, 'breaks_enabled_var'):
            self.breaks_enabled_var = tk.BooleanVar(value=bs.get('breaks_enabled', True))
        toggle_row(c, 'Enable long breaks', self.breaks_enabled_var).pack(anchor='w', padx=8, pady=(0, 8))

        self.min_break_interval_var = tk.StringVar(
            value=str(max(1, int(bs.get('min_seconds_between_breaks', 600)) // 60)))
        self.max_break_interval_var = tk.StringVar(
            value=str(max(1, int(bs.get('max_seconds_between_breaks', 3600)) // 60)))
        self.min_break_duration_var = tk.StringVar(
            value=str(max(1, int(bs.get('min_break_duration_seconds', 60)) // 60)))
        self.max_break_duration_var = tk.StringVar(
            value=str(max(1, int(bs.get('max_break_duration_seconds', 1200)) // 60)))

        for lbl, v1, v2 in [
            ('Session length', self.min_break_interval_var, self.max_break_interval_var),
            ('Break duration', self.min_break_duration_var, self.max_break_duration_var),
        ]:
            r = tk.Frame(c, bg=SURFACE)
            r.pack(fill='x', padx=8, pady=4)
            tk.Label(r, text=lbl, bg=SURFACE, fg=MUTED,
                     font=FONT_UI, width=14, anchor='w').pack(side='left')
            ttk.Entry(r, textvariable=v1, width=5).pack(side='left', padx=2)
            tk.Label(r, text='–', bg=SURFACE, fg=MUTED, font=FONT_UI).pack(side='left', padx=2)
            ttk.Entry(r, textvariable=v2, width=5).pack(side='left', padx=2)
            tk.Label(r, text='min', bg=SURFACE, fg=MUTED, font=FONT_UI).pack(side='left', padx=4)
        tk.Frame(c, bg=SURFACE).pack(pady=(0, 4))

    def _build_antiban_tab(self, tab):
        """Anti-Ban Features as a standalone tab with its own scroll container."""
        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0, bd=0)
        vscroll = tk.Scrollbar(tab, orient='vertical', command=canvas.yview,
                               bg=BG, troughcolor=BG, width=18, highlightthickness=0, bd=0)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        body = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=body, anchor='nw')
        def _resize(e=None):
            canvas.configure(scrollregion=canvas.bbox('all'))
            canvas.itemconfig(win_id, width=canvas.winfo_width())
        body.bind('<Configure>', _resize)
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(win_id, width=e.width))
        def _wheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), 'units')
        canvas.bind('<Enter>', lambda _: canvas.bind_all('<MouseWheel>', _wheel))
        canvas.bind('<Leave>', lambda _: canvas.unbind_all('<MouseWheel>'))

        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(6, 6))
        section_label(c, 'Anti-Ban Features')

        # Master switch
        self.antiban_master_var = tk.BooleanVar(
            value=self.config.get('antiban_master_enabled', True))
        toggle_row(c, '★ Master: Anti-Ban Suite  (disables all below if off)',
                   self.antiban_master_var).pack(anchor='w', padx=8, pady=(0, 4))
        tk.Frame(c, bg=BORDER, height=1).pack(fill='x', padx=6, pady=(0, 4))

        # Track sub-widgets so master toggle can disable/enable them visually.
        self._antiban_sub_frame = c
        self._antiban_master_anchor_count = len(c.winfo_children())
        self.antiban_master_var.trace_add('write', lambda *_: self._apply_antiban_master_state())

        def _ab_label(parent, tag):
            """Small tag next to toggle: [DEFAULT ON] or [OPT-IN]."""
            color = GREEN if tag == 'DEFAULT ON' else AMBER
            tk.Label(parent, text=f'[{tag}]', bg=SURFACE, fg=color,
                     font=(FONT_UI[0], 7, 'bold')).pack(side='left', padx=(4, 0))

        # 1. Failsafe: 30 empty rotations (always on — no toggle).
        info_row = tk.Frame(c, bg=SURFACE)
        info_row.pack(fill='x', padx=8, pady=(4, 0))
        tk.Label(info_row, text='✓',
                 bg=SURFACE, fg=GREEN, font=(FONT_UI[0], 9, 'bold')).pack(side='left', padx=(0, 6))
        tk.Label(info_row, text='Stop after 30 empty camera rotations',
                 bg=SURFACE, fg=FG, font=FONT_UI).pack(side='left')
        tk.Label(info_row, text='[ALWAYS ON]', bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 7, 'bold')).pack(side='left', padx=4)

        # 2. Fatigue detection (OCR % stop) — REMOVED. The 'too tired to mine'
        # bottom-chat OCR and the fatigue-100% template still trigger stops.
        # Hidden var kept so save_config remains compatible with old configs.
        # Defaults True so fatigue OCR always runs unless explicitly disabled.
        self.fatigue_detection_var = tk.BooleanVar(value=self.config.get('fatigue_detection_enabled', True))

        # Long breaks var kept for config compat — see Breaks tab.
        bs = self.config.get('break_settings', {})
        if not hasattr(self, 'breaks_enabled_var'):
            self.breaks_enabled_var = tk.BooleanVar(
                value=bs.get('breaks_enabled', True))

        # 5. Teleport detector — moved to Experimental tab (still default-on).
        tk.Frame(c, bg=BORDER, height=1).pack(fill='x', padx=6, pady=(2, 4))

        # 6. Randomized mouse personality (informational — always on)
        info_row = tk.Frame(c, bg=SURFACE)
        info_row.pack(fill='x', padx=8, pady=(4, 0))
        tk.Label(info_row, text='✓',
                 bg=SURFACE, fg=GREEN, font=(FONT_UI[0], 9, 'bold')).pack(side='left', padx=(0, 6))
        tk.Label(info_row, text='Randomized mouse personality per session (seeded)',
                 bg=SURFACE, fg=FG, font=FONT_UI).pack(side='left')
        tk.Label(info_row, text='[ALWAYS ON]', bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 7, 'bold')).pack(side='left', padx=4)

        info_row = tk.Frame(c, bg=SURFACE)
        info_row.pack(fill='x', padx=8, pady=(2, 6))
        tk.Label(info_row, text='✓',
                 bg=SURFACE, fg=GREEN, font=(FONT_UI[0], 9, 'bold')).pack(side='left', padx=(0, 6))
        tk.Label(info_row, text='Watchdog: alerts if loop stalls > 10s',
                 bg=SURFACE, fg=FG, font=FONT_UI).pack(side='left')
        tk.Label(info_row, text='[ALWAYS ON]', bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 7, 'bold')).pack(side='left', padx=4)

        tk.Frame(c, bg=BORDER, height=1).pack(fill='x', padx=6, pady=(4, 4))

        # 8. Mod crown detector — watches bottom-left chat for gold/silver crown pixels
        self.mod_crown_var = tk.BooleanVar(
            value=self.config.get('mod_crown_detection_enabled', False))
        row = toggle_row(c, 'Mod crown detector (stop if mod/admin speaks in chat)',
                         self.mod_crown_var)
        row.pack(anchor='w', padx=8, pady=(4, 0))
        _ab_label(row, 'OPT-IN')
        tk.Label(c, text='Watches chat bottom-left for gold/silver crown icons. '
                         '(Currently uses pixel-color detection, not template matching — '
                         'template-based detection is on the roadmap.)',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic')
                 ).pack(anchor='w', padx=30, pady=(0, 6))

        # Stop-on-chat-text — OCR chat for user-specified phrases
        self.chat_text_stop_var = tk.BooleanVar(
            value=self.config.get('chat_text_stop_enabled', True))
        row = toggle_row(c, 'Read chat for names — stop on match (e.g. Terror, Kleio)',
                         self.chat_text_stop_var)
        row.pack(anchor='w', padx=8, pady=(4, 0))
        _ab_label(row, 'DEFAULT ON')
        tk.Label(c, text='Names to watch for, separated by commas (case-insensitive):',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic')
                 ).pack(anchor='w', padx=30, pady=(0, 2))
        self.chat_text_phrases_var = tk.StringVar(
            value=','.join(self.config.get('chat_text_stop_phrases',
                                           ['Terror', 'Kleio'])))
        ttk.Entry(c, textvariable=self.chat_text_phrases_var
                  ).pack(fill='x', padx=30, pady=(0, 6))

        # ── Active Protections — informational list ───────────────────────
        tk.Frame(c, bg=BORDER, height=1).pack(fill='x', padx=6, pady=(6, 4))
        tk.Label(c, text='Active Protections  (implemented & tested)',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'bold')
                 ).pack(anchor='w', padx=8, pady=(0, 4))
        _PROTECTIONS = [
            'Stop after 30 empty camera rotations',
            'Watchdog: alerts + logs if main loop stalls > 10s',
            'Randomized mouse personality per session (seeded Bezier curves)',
            'Welcome banner auto-dismiss (ESC on login/welcome screen)',
            '"Too tired to mine" bottom-chat OCR — stops bot immediately',
            'Fatigue 100% template match (fatigue100red.png) — backup stop',
            'Jittered clickback timing (A → pause → B, randomized interval)',
            'Camera-settle wait: no clicks while camera is still moving',
            'Park mouse outside game window between actions (toggleable)',
            'Lazy / super-lazy idle pause between mine clicks (toggleable)',
            'Teleport / environment-change detector (in Experimental tab)',
            'Mod crown detector: stops if mod/admin crown seen in chat',
        ]
        for txt in _PROTECTIONS:
            _pr = tk.Frame(c, bg=SURFACE)
            _pr.pack(fill='x', padx=8, pady=1)
            tk.Label(_pr, text='●', bg=SURFACE, fg=GREEN,
                     font=(FONT_UI[0], 7, 'bold')).pack(side='left', padx=(0, 6))
            tk.Label(_pr, text=txt, bg=SURFACE, fg=MUTED,
                     font=('Consolas', 8)).pack(side='left', anchor='w')

        # Apply initial master state now that all sub-widgets exist
        self._apply_antiban_master_state()

    def _build_skill_placeholder(self, tab, name, blurb):
        """Stub tab for skills not yet implemented."""
        wrap = tk.Frame(tab, bg=BG)
        wrap.pack(fill='both', expand=True, padx=20, pady=20)
        tk.Label(wrap, text=name, bg=BG, fg=FG,
                 font=('Segoe UI', 16, 'bold')).pack(anchor='w', pady=(0, 6))
        tk.Label(wrap, text='Coming soon — built off the mining loop.',
                 bg=BG, fg=AMBER,
                 font=(FONT_UI[0], 10, 'italic')).pack(anchor='w', pady=(0, 10))
        tk.Label(wrap, text=blurb, bg=BG, fg=MUTED,
                 font=FONT_UI, wraplength=500, justify='left').pack(anchor='w')
        if name.startswith('Fighter'):
            sub = tk.Frame(wrap, bg=BG)
            sub.pack(anchor='w', pady=(20, 0))
            tk.Label(sub, text='Fight Loot:', bg=BG, fg=MUTED,
                     font=FONT_UI).pack(side='left', padx=(0, 8))
            cb = tk.Checkbutton(sub, text='Auto-loot drops', state='disabled',
                                bg=BG, fg=MUTED, selectcolor=BORDER,
                                font=FONT_UI)
            cb.pack(side='left')

    def _build_bot_slave_tab(self, tab, slot_idx):
        """Inline per-bot config tab for Bot2/3/4/5.
        Enable toggle at top grays out all content when off."""
        bot_name = f'Bot{slot_idx + 1}'
        slot = self._clients_config[slot_idx]
        # Tier order: Tin → Copper → Iron → Coal → Mithril → Adamantite
        ORE_LIST = ('tin_rock', 'copper_rock', 'iron_rock', 'coal_rock', 'mithril_rock', 'adamantite_rock')
        ORE_LABELS = {
            'tin_rock': 'Tin', 'copper_rock': 'Cop', 'iron_rock': 'Iron',
            'coal_rock': 'Coal',
            'mithril_rock': 'Mith', 'adamantite_rock': 'Addy',
        }

        # Scrollable body
        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0, bd=0)
        vscroll = tk.Scrollbar(tab, orient='vertical', command=canvas.yview,
                               bg=BG, troughcolor=BG, width=18, highlightthickness=0, bd=0)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        body = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>',
                  lambda _: (canvas.configure(scrollregion=canvas.bbox('all')),
                             canvas.itemconfig(win_id, width=canvas.winfo_width())))
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(win_id, width=e.width))
        def _wheel(e): canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        canvas.bind('<Enter>', lambda _: canvas.bind_all('<MouseWheel>', _wheel))
        canvas.bind('<Leave>', lambda _: canvas.unbind_all('<MouseWheel>'))

        # ── Enable row ────────────────────────────────────────────────────────
        en_var = tk.BooleanVar(value=bool(slot.get('enabled', False)))
        self._client_enable_vars[slot_idx] = en_var

        en_co, en_c = card(body, padx=0, pady=4)
        en_co.pack(fill='x', padx=8, pady=(8, 4))
        en_row = tk.Frame(en_c, bg=SURFACE)
        en_row.pack(fill='x', padx=8, pady=6)
        tk.Label(en_row, text=bot_name, bg=SURFACE, fg=ACCENT,
                 font=('Segoe UI', 12, 'bold')).pack(side='left')
        Toggle(en_row, en_var, bg=SURFACE).pack(side='left', padx=(10, 0))
        en_status_lbl = tk.Label(en_row, text='', bg=SURFACE, fg=MUTED, font=FONT_UI)
        en_status_lbl.pack(side='left', padx=(8, 0))

        # Live status (dot + label + pause btn) shown inline on enable row
        pause_btn = ttk.Button(en_row, text='Pause',
                               command=lambda: self._toggle_pause_client(slot_idx),
                               style='Util.TButton')
        pause_btn.pack(side='right')
        status_lbl = tk.Label(en_row, text='not started', bg=SURFACE, fg=MUTED,
                              font=(FONT_UI[0], 8, 'italic'))
        status_lbl.pack(side='right', padx=(0, 6), fill='x', expand=True)
        dot_lbl = tk.Label(en_row, text='●', bg=SURFACE, fg=MUTED,
                           font=('Segoe UI', 10, 'bold'))
        dot_lbl.pack(side='right', padx=(0, 2))
        self._client_status_rows[slot_idx] = {
            'dot': dot_lbl, 'label': status_lbl, 'btn': pause_btn}

        # ── Window picker ─────────────────────────────────────────────────────
        win_co, win_c = card(body, padx=0, pady=4)
        win_co.pack(fill='x', padx=8, pady=(0, 4))
        win_row = tk.Frame(win_c, bg=SURFACE)
        win_row.pack(fill='x', padx=8, pady=6)
        tk.Label(win_row, text='Window:', bg=SURFACE, fg=FG,
                 font=FONT_UI, width=8, anchor='w').pack(side='left')
        saved_title = slot.get('window_title', '')
        cur = next((d for d, info in self._window_info_map.items()
                    if info['title'] == saved_title), '')
        wvar = tk.StringVar(value=cur)
        win_cb = ttk.Combobox(win_row, textvariable=wvar,
                              values=self._slave_window_choices(exclude_idx=slot_idx),
                              state='readonly', width=38)
        win_cb.pack(side='left', padx=(2, 4))
        def _on_win_selected(_e=None):
            display = wvar.get()
            info = self._window_info_map.get(display, {})
            slot['window_title'] = info.get('title', display)
            slot['_win_display'] = display  # in-memory: for direct hwnd lookup
            self._save_clients_config()
            self._refresh_clients_windows()
        win_cb.bind('<<ComboboxSelected>>', _on_win_selected)
        win_cb.bind('<MouseWheel>', lambda e: 'break')
        ttk.Button(win_row, text='Refresh', style='Util.TButton',
                   command=lambda cb=win_cb, si=slot_idx: (
                       cb.configure(values=self._slave_window_choices(exclude_idx=si))
                   )).pack(side='left', padx=(0, 4))
        self._client_window_combos.append((slot_idx, en_var, wvar, win_cb))

        # Auto Login toggle — directly below window picker
        al_var = tk.BooleanVar(value=bool(slot.get('autologin_enabled', True)))
        al_row = tk.Frame(win_c, bg=SURFACE)
        al_row.pack(anchor='w', padx=8, pady=(0, 6))
        Toggle(al_row, al_var, bg=SURFACE).pack(side='left', padx=(0, 8))
        tk.Label(al_row, text='Auto Login', bg=SURFACE, fg=FG, font=FONT_UI).pack(side='left')
        def _save_al(*_, _v=al_var, _s=slot):
            _s['autologin_enabled'] = bool(_v.get())
            self._save_clients_config()
        al_var.trace_add('write', _save_al)

        # ── Content (grayed when disabled) ────────────────────────────────────
        content = tk.Frame(body, bg=BG)
        content.pack(fill='both', expand=True)

        # Ores
        ore_co, ore_c = card(content, padx=0, pady=4)
        ore_co.pack(fill='x', padx=8, pady=(0, 4))
        section_label(ore_c, 'Ores')
        ore_row = tk.Frame(ore_c, bg=SURFACE)
        ore_row.pack(fill='x', padx=8, pady=(0, 2))
        saved_ores = slot.get('ore_checkboxes', {})
        ore_vars = {ore: tk.BooleanVar(value=bool(saved_ores.get(ore, False)))
                    for ore in ORE_LIST}
        self._client_ore_vars[slot_idx] = ore_vars
        for ore in ORE_LIST:
            tk.Checkbutton(ore_row, text=ORE_LABELS.get(ore, ore),
                           variable=ore_vars[ore],
                           bg=SURFACE, fg=FG, selectcolor=BORDER,
                           activebackground=SURFACE, activeforeground=FG,
                           font=FONT_UI).pack(side='left', padx=4)
        tk.Label(ore_c, text='Unchecked = inherit master ores',
                 bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 8, 'italic')).pack(anchor='w', padx=8, pady=(0, 4))

        # Mining Mode
        mm_co, mm_c = card(content, padx=0, pady=4)
        mm_co.pack(fill='x', padx=8, pady=(0, 4))
        section_label(mm_c, 'Mining Mode')
        pm_var = tk.BooleanVar(value=bool(slot.get('powermine_enabled', False)))
        pm_row = tk.Frame(mm_c, bg=SURFACE)
        pm_row.pack(anchor='w', padx=8, pady=(0, 4))
        Toggle(pm_row, pm_var, bg=SURFACE).pack(side='left', padx=(0, 8))
        tk.Label(pm_row, text='Powermine (indefinitely)',
                 bg=SURFACE, fg=FG, font=FONT_UI).pack(side='left')
        tk.Label(mm_c, text='Speed mirrors master bot setting.',
                 bg=SURFACE, fg=MUTED,
                 font=(FONT_UI[0], 8, 'italic')).pack(anchor='w', padx=8, pady=(0, 6))
        def _save_mode(*_):
            slot['powermine_enabled'] = bool(pm_var.get())
            self._save_clients_config()
        pm_var.trace_add('write', _save_mode)

        spots_co, spots_c = card(content, padx=0, pady=4)
        spots_co.pack(fill='x', padx=8, pady=(0, 4))
        section_label(spots_c, 'Fixed Ore Spots')

        # Enable / disable fixed spots for this bot
        fixed_spots_enabled_var = tk.BooleanVar(
            value=bool(slot.get('fixed_ore_spots_enabled', False)))
        def _on_fixed_spots_toggle(*_):
            slot['fixed_ore_spots_enabled'] = bool(fixed_spots_enabled_var.get())
            self._save_clients_config()
        fixed_spots_enabled_var.trace_add('write', _on_fixed_spots_toggle)
        toggle_row(spots_c, 'Use fixed ore spots for this bot',
                   fixed_spots_enabled_var).pack(anchor='w', padx=8, pady=(2, 4))

        srow = tk.Frame(spots_c, bg=SURFACE)
        srow.pack(fill='x', padx=8, pady=(0, 6))
        spots = slot.get('fixed_ore_spots', [])
        spots_lbl = tk.Label(srow, text=f'{len(spots)} spot(s) saved',
                             bg=SURFACE, fg=MUTED, font=FONT_UI)
        spots_lbl.pack(side='left')
        ttk.Button(srow, text='Set spots…', style='Util.TButton',
                   command=lambda: self._capture_fixed_spots_for_slot(
                       slot_idx, spots_lbl)).pack(side='left', padx=(8, 0))
        def _clear_spots(s=slot, lbl=spots_lbl, si=slot_idx):
            # Close any open overlay for this slot before clearing
            _prev = getattr(self, f'_spot_overlay_{si}', None)
            if _prev is not None:
                try:
                    if _prev.winfo_exists():
                        _prev.destroy()
                except Exception:
                    pass
                setattr(self, f'_spot_overlay_{si}', None)
            s['fixed_ore_spots'] = []
            self._save_clients_config()
            lbl.config(text='0 spot(s) saved')
        ttk.Button(srow, text='Clear', style='Util.TButton',
                   command=_clear_spots).pack(side='left', padx=(4, 0))

        # (Legacy "Enable walkto + clicks-before-walkto" UI removed — replaced
        # by the new per-bot WalkTo Destinations card below the Loadout 1 card.)

        # Task var (always Mining)
        t_var = tk.StringVar(value='Mining')
        self._client_task_vars[slot_idx] = t_var

        # Powermine → Walkto interlock: powermine ON forces walkto OFF
        def _pm_walkto_interlock(*_):
            if pm_var.get():
                _wt = slot.get('_walkto_var')
                if _wt is not None:
                    _wt.set(False)
                try:
                    wt_cb.config(state='disabled')
                except Exception:
                    pass
            else:
                try:
                    wt_cb.config(state='normal')
                except Exception:
                    pass
        pm_var.trace_add('write', _pm_walkto_interlock)
        # _pm_walkto_interlock() called below after wt_var and wt_cb are created

        # ── Enable / disable content graying ──────────────────────────────────
        _init_done = [False]
        # ── Banking — Loadout 1 slot per-bot ──────────────────────────────
        bk_co, bk_c = card(content, padx=0, pady=4)
        bk_co.pack(fill='x', padx=8, pady=(0, 4))
        section_label(bk_c, '🏦 Banking — Loadout 1')

        mimic_var = tk.BooleanVar(value=bool(slot.get('bank_mine_mimic_master', True)))
        slot.setdefault('bank_mine_mimic_master', True)

        def _fmt_xy(xy):
            if not xy:
                return '— not set —'
            return f'X={int(xy[0])}  Y={int(xy[1])}  (rel to window)'

        toggle_row(bk_c, 'Mimic master Loadout 1 click area  [DEFAULT ON]',
                   mimic_var).pack(anchor='w', padx=8, pady=(2, 2))
        tk.Label(bk_c,
                 text='When ON, this bot uses the master\'s saved Mine1 coords. Turn OFF to '
                      'capture a unique position for this bot (different bank window layout).',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=520, justify='left'
                 ).pack(anchor='w', padx=14, pady=(0, 4))

        own_row = tk.Frame(bk_c, bg=SURFACE)
        own_row.pack(fill='x', padx=14, pady=(0, 6))
        tk.Label(own_row, text='Own Loadout 1:',
                 bg=SURFACE, fg=FG, font=FONT_UI).pack(side='left')
        own_xy_label = tk.Label(
            own_row,
            text=_fmt_xy(slot.get('bank_mine_slot_xy_rel')),
            bg=BORDER, fg=ACCENT, font=('Consolas', 9, 'bold'), padx=8)
        own_xy_label.pack(side='left', padx=(8, 8))

        def _save_slot_mine(x, y):
            rel_x, rel_y = int(x), int(y)
            try:
                title = (slot.get('window_title') or '').strip()
                if title:
                    hwnd = win32gui.FindWindow(None, title)
                    if hwnd:
                        cl_left, cl_top = win32gui.ClientToScreen(hwnd, (0, 0))
                        rel_x = int(x) - cl_left
                        rel_y = int(y) - cl_top
            except Exception:
                pass
            slot['bank_mine_slot_xy_rel'] = [rel_x, rel_y]
            own_xy_label.config(text=_fmt_xy([rel_x, rel_y]))
            self._save_clients_config()

        set_btn = ttk.Button(own_row, text='Set position',
                             command=lambda: self._capture_screen_click(_save_slot_mine))
        set_btn.pack(side='left', padx=(0, 4))

        def _clear_slot_mine():
            slot['bank_mine_slot_xy_rel'] = None
            own_xy_label.config(text='— not set —')
            self._save_clients_config()
        clr_btn = ttk.Button(own_row, text='Clear', command=_clear_slot_mine)
        clr_btn.pack(side='left')

        def _on_mimic_change(*_):
            slot['bank_mine_mimic_master'] = bool(mimic_var.get())
            # Disable own-coord controls when mimicking master.
            new_state = 'disabled' if mimic_var.get() else 'normal'
            try:
                set_btn.configure(state=new_state)
                clr_btn.configure(state=new_state)
                own_xy_label.config(fg=MUTED if mimic_var.get() else ACCENT)
            except Exception:
                pass
            self._save_clients_config()
        mimic_var.trace_add('write', _on_mimic_change)
        _on_mimic_change()  # apply initial enable/disable

        # ── WalkTo Destinations (per-bot, with mimic master option) ──────────
        wt_co, wt_c = card(content, padx=0, pady=4)
        wt_co.pack(fill='x', padx=8, pady=(0, 4))
        section_label(wt_c, '🚶 WalkTo Destinations  (Bank + Train)')

        wt_mimic_var = tk.BooleanVar(value=bool(slot.get('walkto_mimic_master', True)))
        slot.setdefault('walkto_mimic_master', True)
        toggle_row(wt_c, 'Mimic master Bank + Train destinations  [DEFAULT ON]',
                   wt_mimic_var).pack(anchor='w', padx=8, pady=(2, 2))
        tk.Label(wt_c,
                 text='When ON, this bot uses the master\'s walkto Bank + Train slots. '
                      'Turn OFF to set unique destinations for this bot.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=520, justify='left'
                 ).pack(anchor='w', padx=14, pady=(0, 4))

        # City preset lists (kept consistent with master's WalkTo presets).
        _BANK_SHORT_CITIES = [
            '', 'None', 'Varrock East', 'Varrock West', 'Falador East', 'Falador West',
            'Edgeville', 'Draynor', 'Al Kharid', 'Catherby', 'Seers',
            'Ardougne North', 'Ardougne South',
        ]
        _BANK_FULL_CITIES = [
            '', 'None', 'Bank (Varrock East)', 'Bank (Varrock West)',
            'Bank (Falador East)', 'Bank (Falador West)',
            'Bank (Edgeville)', 'Bank (Draynor)', 'Bank (Al Kharid)',
            'Bank (Catherby)', 'Bank (Seers)',
            'Bank (Ardougne North)', 'Bank (Ardougne South)',
        ]

        # Helper: build a row of entries/comboboxes bound to slot config keys.
        # Each slot is (suffix, placeholder, preset_list_or_None).
        def _slot_dest_row(parent, label, key_prefix, slots):
            row = tk.Frame(parent, bg=SURFACE)
            row.pack(fill='x', padx=8, pady=(2, 2))
            tk.Label(row, text=label, bg=SURFACE, fg=FG, font=FONT_UI,
                     width=14, anchor='w').pack(side='left')
            grid = tk.Frame(row, bg=SURFACE)
            grid.pack(side='left', fill='x', expand=True)
            entries = []
            for i, (suffix, ph, presets) in enumerate(slots):
                ck = f'{key_prefix}_{suffix}'
                v = tk.StringVar(value=slot.get(ck, ''))
                if presets:
                    ent = ttk.Combobox(grid, textvariable=v, values=presets,
                                       state='normal', width=20)
                    # Block mousewheel so scrolling never changes the value.
                    ent.bind('<MouseWheel>', lambda e: 'break')
                    ent.bind('<Button-4>',   lambda e: 'break')
                    ent.bind('<Button-5>',   lambda e: 'break')
                else:
                    ent = ttk.Entry(grid, textvariable=v, style='TEntry', width=22)
                ent.grid(row=i // 2, column=i % 2, sticky='ew', padx=2, pady=1)
                grid.columnconfigure(i % 2, weight=1)
                def _on_change(*_a, _k=ck, _v=v):
                    slot[_k] = _v.get()
                    self._save_clients_config()
                v.trace_add('write', _on_change)
                entries.append(ent)
                ttk.Label(grid, text=ph,
                          background=SURFACE, foreground=MUTED,
                          font=(FONT_UI[0], 7, 'italic')).grid(
                          row=i // 2, column=(i % 2) + 2, sticky='w', padx=(2, 6))
            return entries

        BANK_SLOTS = [
            ('a',    'short (city)',     _BANK_SHORT_CITIES),
            ('b',    'full (Bank (...))',_BANK_FULL_CITIES),
            ('user', 'user-set string',  None),
            ('xy',   'X Y coords',       None),
        ]
        TRAIN_SLOTS = [
            ('user', 'user-set string',  None),
            ('xy',   'X Y coords',       None),
        ]
        bank_entries  = _slot_dest_row(wt_c, 'Bank dest',  'walkto_dest1',  BANK_SLOTS)
        train_entries = _slot_dest_row(wt_c, 'Train dest', 'walkto_train1', TRAIN_SLOTS)

        def _on_wt_mimic_change(*_):
            slot['walkto_mimic_master'] = bool(wt_mimic_var.get())
            new_state = 'disabled' if wt_mimic_var.get() else 'normal'
            for ent in (bank_entries + train_entries):
                try: ent.configure(state=new_state)
                except Exception: pass
            self._save_clients_config()
        wt_mimic_var.trace_add('write', _on_wt_mimic_change)
        _on_wt_mimic_change()

        def _apply_enable(*_):
            enabled = bool(en_var.get())
            en_status_lbl.config(
                text='Enabled' if enabled else 'Disabled',
                fg=GREEN if enabled else MUTED)
            new_state = 'normal' if enabled else 'disabled'
            def _walk(w):
                try:
                    cls = w.winfo_class()
                    if cls in ('TCheckbutton', 'Checkbutton', 'TEntry', 'Entry',
                               'Spinbox', 'TCombobox', 'TButton', 'Button'):
                        w.configure(state=new_state)
                except Exception:
                    pass
                for ch in w.winfo_children():
                    _walk(ch)
            _walk(content)
            if enabled:
                _pm_walkto_interlock()  # re-apply powermine→walkto interlock
            try:
                win_cb.configure(state='readonly' if enabled else 'disabled')
            except Exception:
                pass
            if _init_done[0]:
                slot['enabled'] = enabled
                self._save_clients_config()

        en_var.trace_add('write', _apply_enable)
        _apply_enable()   # set initial visual state without saving
        _init_done[0] = True

    def _build_clients_tab(self, tab):
        """Replaced by per-bot tabs (Bot2/Bot3/Bot4) built in _build_ui."""
        pass

    # ── Live Status (per-client) ────────────────────────────────────────────

    def _schedule_clients_status_update(self):
        """Refresh the Live Status rows ~3x/sec while the GUI is up."""
        try:
            self._refresh_clients_status()
        except Exception:
            pass
        try:
            self.root.after(350, self._schedule_clients_status_update)
        except Exception:
            pass

    def _refresh_clients_status(self):
        rows = getattr(self, '_client_status_rows', {})
        if not rows:
            return
        bots = list(getattr(self, 'bots', []) or [])
        en_vars = getattr(self, '_client_enable_vars', [None] * 5)
        for idx, ui in rows.items():
            # Master (idx 0) is always enabled.
            en_var = en_vars[idx] if idx < len(en_vars) else None
            enabled = True if idx == 0 else bool(en_var.get()) if en_var is not None else False
            sub = bots[idx] if idx < len(bots) else None

            if not enabled:
                # Greyed-out / inactive slot.
                self._cfg(ui['dot'],   fg=BORDER)
                self._lbl(ui['label'], '(disabled — enable on card to use)', BORDER)
                self._cfg(ui['btn'],   text='Pause', state='disabled')
                continue

            if sub is None:
                self._cfg(ui['dot'],   fg=MUTED)
                self._lbl(ui['label'], 'ready (not started)', MUTED)
                self._cfg(ui['btn'],   text='Pause', state='disabled')
                continue
            if not sub.running:
                self._cfg(ui['dot'],   fg=RED)
                reason = (sub.stop_reason or 'stopped')
                self._lbl(ui['label'], f'STOPPED — {reason}', MUTED)
                self._cfg(ui['btn'],   text='Pause', state='disabled')
            elif sub.paused:
                self._cfg(ui['dot'],   fg=AMBER)
                self._lbl(ui['label'], f'PAUSED — last: {sub.last_action}', AMBER)
                self._cfg(ui['btn'],   text='Resume', state='normal')
            else:
                self._cfg(ui['dot'],   fg=GREEN)
                age = max(0, time.time() - sub.last_action_ts)
                wt_suffix = ''
                if sub.config.get('walkto_enabled', False):
                    nxt = getattr(sub, '_mc_walkto_next_at', None)
                    if nxt is None:
                        nxt = getattr(sub, '_walkto_next_at', None)
                    cur = getattr(sub, '_mine_count', 0)
                    if nxt is not None:
                        wt_suffix = f'  |  walkto in {max(0, nxt - cur)} clicks'
                self._lbl(ui['label'], f'ACTIVE — {sub.last_action} '
                                       f'({age:.0f}s ago){wt_suffix}', FG)
                self._cfg(ui['btn'],   text='Pause', state='normal')

    def _toggle_pause_client(self, slot_idx):
        bots = list(getattr(self, 'bots', []) or [])
        if slot_idx >= len(bots):
            return
        sub = bots[slot_idx]
        if not sub.running:
            return
        bot_name = 'Bot' if slot_idx == 0 else f'Bot{slot_idx + 1}'
        if sub.paused:
            sub.resume()
            self.log_debug(f'{bot_name} resumed')
        else:
            sub.pause()
            self.log_debug(f'{bot_name} paused')

    # ── Per-client Profiles ─────────────────────────────────────────────────

    def _client_profiles_dir(self):
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'profiles', 'clients')
        os.makedirs(d, exist_ok=True)
        return d

    def _list_client_profiles(self):
        try:
            return sorted([f[:-5] for f in os.listdir(self._client_profiles_dir())
                           if f.endswith('.json')])
        except Exception:
            return []

    def _client_profile_path(self, name):
        safe = ''.join(ch for ch in name if ch.isalnum() or ch in ('_', '-')).strip('_-')
        return os.path.join(self._client_profiles_dir(), f'{safe or "unnamed"}.json')

    # Fields a per-client profile snapshot owns.
    _CLIENT_PROFILE_KEYS = (
        'task', 'ore_checkboxes',
        'walkto_enabled', 'walkto_min_clicks', 'walkto_max_clicks',
        'walkto_dest_a', 'walkto_dest_b', 'walkto_dest_user', 'walkto_dest_xy',
        'fixed_ore_spots',
    )

    def _save_client_profile(self, slot_idx, name):
        if not name.strip():
            messagebox.showwarning('Profiles', 'Type a profile name first.')
            return
        # Flush card-bound vars into slot first.
        self._save_clients_config()
        slot = self._clients_config[slot_idx]
        snap = {k: slot[k] for k in self._CLIENT_PROFILE_KEYS if k in slot}
        path = self._client_profile_path(name)
        if os.path.exists(path):
            if not messagebox.askyesno('Overwrite?',
                                       f'Profile "{name}" exists. Overwrite?'):
                return
        try:
            with open(path, 'w') as f:
                json.dump(snap, f, indent=2)
            self.log_debug(f'Client profile saved: {name}')
            # Refresh every card's dropdown.
            for s in self._clients_config:
                cb = s.get('_profile_combo')
                if cb is not None:
                    cb['values'] = self._list_client_profiles()
        except Exception as e:
            messagebox.showerror('Profile save error', str(e))

    def _apply_client_profile(self, slot_idx, name):
        path = self._client_profile_path(name)
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror('Profile load error', str(e))
            return
        slot = self._clients_config[slot_idx]
        for k in self._CLIENT_PROFILE_KEYS:
            if k in data:
                slot[k] = data[k]
        # Push loaded values into any card-bound vars.
        if 'task' in data:
            t_var = self._client_task_vars[slot_idx] if slot_idx < len(self._client_task_vars) else None
            if t_var is not None:
                t_var.set(data['task'])
        if 'ore_checkboxes' in data:
            ov = self._client_ore_vars[slot_idx] if slot_idx < len(self._client_ore_vars) else {}
            for k, v in ov.items():
                v.set(bool(data['ore_checkboxes'].get(k, False)))
        self._save_clients_config()
        self.log_debug(f'Client {slot_idx + 1} loaded profile: {name}')

    # ── Global Profiles ─────────────────────────────────────────────────────

    def _list_profiles(self):
        try:
            return sorted([f[:-5] for f in os.listdir(self._profiles_dir)
                           if f.endswith('.json')])
        except Exception:
            return []

    def _profile_path(self, name):
        safe = ''.join(ch for ch in name if ch.isalnum() or ch in ('_', '-')).strip('_-')
        return os.path.join(self._profiles_dir, f'{safe or "unnamed"}.json')

    def _profile_save(self):
        name = (self.profile_var.get() or '').strip()
        if not name:
            messagebox.showwarning('Profiles', 'Type a profile name first '
                                               '(e.g. "faladorironbank").')
            return
        # Persist current GUI state into self.config before snapshotting.
        try: self.save_config()
        except Exception: pass
        path = self._profile_path(name)
        if os.path.exists(path):
            if not messagebox.askyesno('Overwrite?',
                                       f'Profile "{name}" exists. Overwrite?'):
                return
        try:
            snap = {k: v for k, v in self.config.items() if not k.startswith('_')}
            with open(path, 'w') as f:
                json.dump(snap, f, indent=2)
            self.log_debug(f'Profile saved: {name}')
            self._profile_combo['values'] = self._list_profiles()
        except Exception as e:
            messagebox.showerror('Profile save error', str(e))

    def _profile_load(self):
        name = (self.profile_var.get() or '').strip()
        if not name:
            messagebox.showwarning('Profiles', 'Pick a profile to load.')
            return
        path = self._profile_path(name)
        if not os.path.exists(path):
            messagebox.showwarning('Profiles', f'Profile "{name}" not found.')
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror('Profile load error', str(e))
            return
        # Merge into the active config (don't lose unrelated runtime fields),
        # then write to config.json and trigger a GUI restart so all widgets
        # rebind to the new values.
        for k, v in data.items():
            self.config[k] = v
        try:
            with open('config.json', 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            messagebox.showerror('Profile load error', f'Saved but reload failed: {e}')
            return
        self._restart = True
        self.on_closing()

    def _profile_delete(self):
        name = (self.profile_var.get() or '').strip()
        if not name:
            return
        path = self._profile_path(name)
        if not os.path.exists(path):
            return
        if not messagebox.askyesno('Delete?', f'Delete profile "{name}"?'):
            return
        try:
            os.remove(path)
            self.log_debug(f'Profile deleted: {name}')
            self._profile_combo['values'] = self._list_profiles()
            self.profile_var.set('')
        except Exception as e:
            messagebox.showerror('Profile delete error', str(e))

    def _open_client_settings(self, slot_idx):
        """Per-bot settings popup. Covers ores, fixed spots, and walkto for Bot2/3/4."""
        t_var = self._client_task_vars[slot_idx] if slot_idx < len(self._client_task_vars) else None
        if t_var is None:
            return
        ore_vars = self._client_ore_vars[slot_idx] if slot_idx < len(self._client_ore_vars) else {}
        slot = self._clients_config[slot_idx]

        bot_name = f'Bot{slot_idx + 1}'
        win = tk.Toplevel(self.root)
        win.title(f'{bot_name} Settings')
        win.configure(bg=BG)
        win.transient(self.root)
        win.geometry('420x400')
        win.resizable(False, False)

        # Mining-only build: no mode picker; force task to "Mining".
        t_var.set('Mining')

        body = tk.Frame(win, bg=BG)
        body.pack(fill='both', expand=True, padx=12, pady=(12, 6))

        def _render_body(*_):
            for w in body.winfo_children():
                w.destroy()
            mode = t_var.get()
            if mode.startswith('Mining'):
                # Ores
                tk.Label(body, text='Ores', bg=BG, fg=FG,
                         font=FONT_HDR).pack(anchor='w', pady=(6, 2))
                row = tk.Frame(body, bg=BG)
                row.pack(fill='x', pady=(0, 6))
                for ore in ('copper', 'tin', 'iron', 'coal', 'mithril', 'adamantite'):
                    tk.Checkbutton(row, text=ore, variable=ore_vars[ore],
                                   bg=BG, fg=FG, selectcolor=BORDER,
                                   activebackground=BG, activeforeground=FG,
                                   font=FONT_UI).pack(side='left', padx=2)
                tk.Label(body, text='(unchecked = inherit Master / Mining tab)',
                         bg=BG, fg=MUTED,
                         font=(FONT_UI[0], 8, 'italic')).pack(anchor='w')

                # Fixed ore spots — per-bot capture + clear buttons.
                tk.Label(body, text='Fixed ore spots', bg=BG, fg=FG,
                         font=FONT_HDR).pack(anchor='w', pady=(10, 2))
                spots_row = tk.Frame(body, bg=BG)
                spots_row.pack(fill='x', pady=(0, 6))
                spots = slot.get('fixed_ore_spots', [])
                spots_lbl = tk.Label(spots_row,
                                     text=f'{len(spots)} spot(s) saved',
                                     bg=BG, fg=MUTED, font=FONT_UI)
                spots_lbl.pack(side='left')
                ttk.Button(spots_row, text='Set spots…',
                           style='Util.TButton',
                           command=lambda: self._capture_fixed_spots_for_slot(
                               slot_idx, spots_lbl)).pack(side='left', padx=(8, 0))
                def _clear_spots(s=slot, lbl=spots_lbl):
                    s['fixed_ore_spots'] = []
                    self._save_clients_config()
                    lbl.config(text='0 spot(s) saved')
                ttk.Button(spots_row, text='Clear',
                           style='Util.TButton',
                           command=_clear_spots).pack(side='left', padx=(4, 0))

                # Walkto enable + min/max — destinations live on Master Mining tab.
                tk.Label(body, text='Walkto', bg=BG, fg=FG,
                         font=FONT_HDR).pack(anchor='w', pady=(10, 2))
                wt_row = tk.Frame(body, bg=BG)
                wt_row.pack(fill='x', pady=(0, 2))
                wt_var = tk.BooleanVar(value=bool(slot.get('walkto_enabled', True)))
                wt_cb = tk.Checkbutton(wt_row, text='Enable walkto for this client',
                               variable=wt_var,
                               bg=BG, fg=FG, selectcolor=BORDER,
                               activebackground=BG, activeforeground=FG,
                               font=FONT_UI)
                wt_cb.pack(side='left')
                slot['_walkto_var'] = wt_var
                _pm_walkto_interlock()  # apply initial state now that wt_var + wt_cb exist
                rng_row = tk.Frame(body, bg=BG)
                rng_row.pack(fill='x', pady=(0, 2))
                tk.Label(rng_row, text='Clicks before walkto:',
                         bg=BG, fg=FG, font=FONT_UI).pack(side='left')
                wt_min = tk.StringVar(value=str(slot.get('walkto_min_clicks', 35)))
                wt_max = tk.StringVar(value=str(slot.get('walkto_max_clicks', 50)))
                tk.Spinbox(rng_row, from_=1, to=999, width=4,
                           textvariable=wt_min,
                           bg=SURFACE, fg=FG, relief='flat',
                           font=FONT_UI).pack(side='left', padx=(6, 2))
                tk.Label(rng_row, text='–', bg=BG, fg=MUTED,
                         font=FONT_UI).pack(side='left')
                tk.Spinbox(rng_row, from_=1, to=999, width=4,
                           textvariable=wt_max,
                           bg=SURFACE, fg=FG, relief='flat',
                           font=FONT_UI).pack(side='left', padx=(2, 0))
                slot['_wt_min'] = wt_min
                slot['_wt_max'] = wt_max

                # Per-client walkto destinations.
                BANK_SHORT = ['None', 'Varrock East', 'Varrock West',
                              'Falador East', 'Falador West', 'Edgeville',
                              'Draynor', 'Al Kharid', 'Catherby', 'Seers',
                              'Ardougne North', 'Ardougne South']
                BANK_FULL = ['None', 'Bank (Varrock East)', 'Bank (Varrock West)',
                             'Bank (Falador East)', 'Bank (Falador West)',
                             'Bank (Edgeville)', 'Bank (Draynor)',
                             'Bank (Al Kharid)', 'Bank (Catherby)',
                             'Bank (Seers)', 'Bank (Ardougne North)',
                             'Bank (Ardougne South)']
                tk.Label(body, text='Bank destinations (random pick from non-blank):',
                         bg=BG, fg=MUTED,
                         font=(FONT_UI[0], 8, 'italic')).pack(anchor='w', pady=(4, 2))
                d_row = tk.Frame(body, bg=BG)
                d_row.pack(fill='x', pady=(0, 2))
                a_var = tk.StringVar(value=slot.get('walkto_dest_a', 'Varrock East'))
                b_var = tk.StringVar(value=slot.get('walkto_dest_b', 'Bank (Varrock East)'))
                u_var = tk.StringVar(value=slot.get('walkto_dest_user', ''))
                xy_var = tk.StringVar(value=slot.get('walkto_dest_xy', ''))
                ttk.Combobox(d_row, textvariable=a_var, values=BANK_SHORT,
                             state='normal', width=14).pack(side='left', padx=(0, 2))
                tk.Label(d_row, text='&', bg=BG, fg=MUTED,
                         font=FONT_UI).pack(side='left', padx=2)
                ttk.Combobox(d_row, textvariable=b_var, values=BANK_FULL,
                             state='normal', width=18).pack(side='left', padx=(0, 4))
                d_row2 = tk.Frame(body, bg=BG)
                d_row2.pack(fill='x', pady=(0, 4))
                tk.Label(d_row2, text='User Set:', bg=BG, fg=MUTED,
                         font=FONT_UI).pack(side='left')
                tk.Entry(d_row2, textvariable=u_var, bg=SURFACE, fg=FG,
                         insertbackground=FG, relief='flat',
                         font=('Consolas', 9), width=18).pack(side='left', padx=(4, 8))
                tk.Label(d_row2, text='X,Y:', bg=BG, fg=MUTED,
                         font=FONT_UI).pack(side='left')
                tk.Entry(d_row2, textvariable=xy_var, bg=SURFACE, fg=FG,
                         insertbackground=FG, relief='flat',
                         font=('Consolas', 9), width=10).pack(side='left', padx=(4, 0))
                slot['_dest_a'] = a_var
                slot['_dest_b'] = b_var
                slot['_dest_user'] = u_var
                slot['_dest_xy'] = xy_var
            else:
                tk.Label(body,
                         text=f'{mode} settings — coming soon.\n'
                              'Once this mode is implemented, its options will appear here.',
                         bg=BG, fg=AMBER,
                         font=(FONT_UI[0], 10, 'italic'),
                         justify='left').pack(anchor='w', pady=20)

        t_var.trace_add('write', _render_body)
        _render_body()

        # Save-as-profile row (per-client snapshot).
        prof_row = tk.Frame(win, bg=BG)
        prof_row.pack(fill='x', padx=12, pady=(6, 0))
        tk.Label(prof_row, text='Save as profile:', bg=BG, fg=MUTED,
                 font=(FONT_UI[0], 8)).pack(side='left')
        save_name_var = tk.StringVar(value='')
        tk.Entry(prof_row, textvariable=save_name_var, bg=SURFACE, fg=FG,
                 insertbackground=FG, relief='flat',
                 font=('Consolas', 9), width=20).pack(side='left', padx=(4, 4))
        ttk.Button(prof_row, text='Save profile',
                   style='Util.TButton',
                   command=lambda: self._save_client_profile(slot_idx,
                                                             save_name_var.get())
                   ).pack(side='left')

        # Save / Close buttons
        btns = tk.Frame(win, bg=BG)
        btns.pack(fill='x', padx=12, pady=(0, 10))
        def _save_and_close():
            # Persist the per-client fields that the popup directly owns. Vars
            # bound to the card already persist via _save_clients_config.
            wt_var = slot.get('_walkto_var')
            wt_min_var = slot.get('_wt_min')
            wt_max_var = slot.get('_wt_max')
            if wt_var is not None:
                slot['walkto_enabled'] = bool(wt_var.get())
            for k, v in (('walkto_min_clicks', wt_min_var),
                         ('walkto_max_clicks', wt_max_var)):
                if v is not None:
                    try:
                        slot[k] = int(v.get())
                    except (ValueError, tk.TclError):
                        pass
            for k, var_key in (('walkto_dest_a', '_dest_a'),
                               ('walkto_dest_b', '_dest_b'),
                               ('walkto_dest_user', '_dest_user'),
                               ('walkto_dest_xy', '_dest_xy')):
                v = slot.get(var_key)
                if v is not None:
                    slot[k] = v.get()
            self._save_clients_config()
            win.destroy()
        ttk.Button(btns, text='Save', style='Util.TButton',
                   command=_save_and_close).pack(side='right', padx=(6, 0))
        ttk.Button(btns, text='Close', style='Util.TButton',
                   command=win.destroy).pack(side='right')

    def _capture_fixed_spots_for_slot(self, slot_idx, label_widget):
        """Open click-capture overlay and write relative spots into clients[slot_idx]."""
        # Destroy any previously-open overlay for this slot so clicks don't stack.
        prev = getattr(self, f'_spot_overlay_{slot_idx}', None)
        if prev is not None:
            try:
                if prev.winfo_exists():
                    prev.destroy()
            except Exception:
                pass
        setattr(self, f'_spot_overlay_{slot_idx}', None)

        slot = self._clients_config[slot_idx]
        title = slot.get('window_title', '')
        if not title:
            messagebox.showwarning('Fixed Spots',
                                   f'Bot{slot_idx + 1} has no window picked yet.')
            return
        # Case-insensitive search + partial fallback (handles RSCRevolution, RSCRevolution 2, etc.)
        # Try direct lookup via the stored display string — handles same-title windows
        hwnd = None
        cached_display = slot.get('_win_display', '')
        if cached_display and cached_display in self._window_info_map:
            hwnd = self._window_info_map[cached_display].get('hwnd')
        # Fall back to EnumWindows title search
        if not hwnd:
            exact_hits = []
            partial_hits = []
            def _enum_fixed(h, _):
                txt = win32gui.GetWindowText(h)
                if not txt:
                    return True
                if txt.lower() == title.lower():
                    exact_hits.append(h)
                elif title.lower() in txt.lower() or txt.lower() in title.lower():
                    partial_hits.append(h)
                return True
            win32gui.EnumWindows(_enum_fixed, None)
            hwnd = exact_hits[0] if exact_hits else (partial_hits[0] if partial_hits else None)
        if not hwnd:
            messagebox.showwarning('Fixed Spots',
                                   f'Could not find window "{title}".\n'
                                   'Make sure the game is running and a window is selected.')
            return
        try:
            rect = win32gui.GetClientRect(hwnd)
            pt = win32gui.ClientToScreen(hwnd, (0, 0))
            gx, gy, gw, gh = pt[0], pt[1], rect[2], rect[3]
        except Exception:
            messagebox.showerror('Fixed Spots', 'Could not read window position.')
            return

        sel = tk.Toplevel(self.root)
        setattr(self, f'_spot_overlay_{slot_idx}', sel)
        sel.title(f'Bot{slot_idx + 1} — pick up to 3 ore spots')
        sel.geometry(f'{gw}x{gh}+{gx}+{gy}')
        sel.attributes('-topmost', True)
        sel.attributes('-alpha', 0.35)
        sel.configure(bg='black')
        sel.overrideredirect(True)
        canvas = tk.Canvas(sel, bg='black', highlightthickness=0, cursor='crosshair')
        canvas.pack(fill='both', expand=True)
        instr = canvas.create_text(gw // 2, 22,
                           text=f'Bot{slot_idx + 1}  |  Click up to 3 spots  '
                                '|  Right-click to undo  |  Enter/Esc to confirm',
                           fill='white', font=('Consolas', 11, 'bold'))

        spots = list(slot.get('fixed_ore_spots', []))
        markers = []
        colors = ['#ff4444', '#ffaa00', '#44ddff']
        def _redraw():
            for m in markers:
                canvas.delete(m)
            markers.clear()
            for i, (rx, ry) in enumerate(spots):
                sx, sy = int(rx * gw), int(ry * gh)
                r = 18
                markers.append(canvas.create_oval(sx-r, sy-r, sx+r, sy+r,
                                                  outline=colors[i], width=3, fill=''))
                markers.append(canvas.create_text(sx, sy, text=str(i+1),
                                                  fill=colors[i],
                                                  font=('Consolas', 13, 'bold')))
            # Show confirm prompt once 3 spots chosen
            if len(spots) >= 3:
                canvas.itemconfig(instr,
                    text='3 spots selected — press Enter, click here, or Esc to confirm')
        _redraw()

        def _on_click(e):
            # If 3 spots already picked, treat any click as confirm
            if len(spots) >= 3:
                _confirm()
                return
            spots.append((e.x / gw, e.y / gh))
            _redraw()
        def _on_right(_e):
            if spots:
                spots.pop()
                _redraw()
        def _confirm(_e=None):
            if not sel.winfo_exists():
                return
            slot['fixed_ore_spots'] = list(spots)
            self._save_clients_config()
            try:
                label_widget.config(text=f'{len(spots)} spot(s) saved')
            except Exception:
                pass
            setattr(self, f'_spot_overlay_{slot_idx}', None)
            sel.destroy()

        canvas.bind('<Button-1>', _on_click)
        canvas.bind('<Button-3>', _on_right)
        # Bind keys to both canvas AND sel; overrideredirect windows can lose
        # keyboard focus — grab_set forces it.
        sel.bind('<Return>', _confirm)
        sel.bind('<Escape>', _confirm)
        canvas.bind('<Return>', _confirm)
        canvas.bind('<Escape>', _confirm)
        canvas.focus_set()
        sel.grab_set()
        sel.focus_force()

    def _jump_to_task_tab(self, task_name):
        """Switch the top-level notebook to the tab matching the given task."""
        nb = None
        for w in self.root.winfo_children():
            for ch in w.winfo_children() if hasattr(w, 'winfo_children') else []:
                if isinstance(ch, ttk.Notebook):
                    nb = ch
                    break
            if nb:
                break
        # Fallback: scan all descendants.
        if nb is None:
            stack = list(self.root.winfo_children())
            while stack:
                w = stack.pop()
                if isinstance(w, ttk.Notebook):
                    nb = w
                    break
                stack.extend(w.winfo_children())
        if nb is None:
            return
        # Map task name to tab text prefix.
        wanted = task_name.split(' (')[0].strip()
        for i in range(nb.index('end')):
            try:
                txt = nb.tab(i, 'text').strip()
            except Exception:
                continue
            if txt.startswith(wanted):
                nb.select(i)
                return

    def _slot_assignments(self):
        """Return dict {window_title: tag} for every window already chosen by
        any slot. Tag is 'bot' for Bot (master), 'bot N' for Bot2/3/4."""
        out = {}
        master = getattr(self, 'window_var', None)
        if master is not None:
            t = self._title_from_display(master.get())
            if t:
                out[t] = 'master'
        for entry in getattr(self, '_client_window_combos', []):
            idx, _en, wvar, _cb = entry
            display = wvar.get()
            if display.endswith('  (master)'):
                display = display[:-len('  (master)')]
            elif ')' in display and ' (client ' in display:
                display = display.rsplit('  (client ', 1)[0]
            t = self._window_info_map.get(display, {}).get('title')
            if t and t not in out:
                out[t] = f'client {idx + 1}'
        return out

    def _slave_window_choices(self, exclude_idx=None):
        """Return all detected Java windows — no filtering."""
        return self.get_java_windows()

    def _refresh_clients_windows(self):
        for entry in getattr(self, '_client_window_combos', []):
            idx, _en, _wvar, cb = entry
            cb['values'] = self._slave_window_choices(exclude_idx=idx)

    def _save_clients_config(self):
        """Persist Bot2/3/4/5 cards to config['clients'] (slot 0 = master = unchanged)."""
        clients = [{} for _ in range(5)]
        for (idx, en_var, wvar, _cb) in self._client_window_combos:
            display = wvar.get()
            if display.endswith('  (master)'):
                display = display[:-len('  (master)')]
            elif '  (client ' in display:
                display = display.rsplit('  (client ', 1)[0]
            elif '  (bot' in display.lower():
                display = display.rsplit('  (', 1)[0]
            info = self._window_info_map.get(display, {})
            # Index by slot (idx), not iteration order (i).
            ore_vars = self._client_ore_vars[idx] if idx < len(self._client_ore_vars) else {}
            task_var = self._client_task_vars[idx] if idx < len(self._client_task_vars) else None
            slot_in = self._clients_config[idx] if idx < len(self._clients_config) else {}
            ores = {k: v.get() for k, v in ore_vars.items()}
            # Prefer the title stored directly on slot (set immediately on selection)
            # over the _window_info_map lookup which may fail if the display string drifted.
            saved_title = slot_in.get('window_title', '') or info.get('title', '')
            entry = {
                'enabled': bool(en_var.get()),
                'window_title': saved_title,
            }
            if task_var:
                entry['task'] = task_var.get()
            if any(ores.values()):
                entry['ore_checkboxes'] = ores
            # Preserve fields owned directly by the slot dict.
            for k in ('walkto_enabled', 'walkto_min_clicks', 'walkto_max_clicks',
                      'walkto_dest_a', 'walkto_dest_b',
                      'walkto_dest_user', 'walkto_dest_xy',
                      'walkto_dest1_a', 'walkto_dest1_b',
                      'walkto_dest1_user', 'walkto_dest1_xy',
                      'walkto_train1_user', 'walkto_train1_xy',
                      'walkto_mimic_master',
                      'bank_mine_mimic_master', 'bank_mine_slot_xy_rel',
                      'fixed_ore_spots', 'powermine_enabled', 'speed_mode',
                      'fixed_ore_spots_enabled'):
                if k in slot_in:
                    entry[k] = slot_in[k]
            clients[idx] = entry
        self.config['clients'] = clients
        self.save_config()
        enabled_count = sum(1 for c in clients[1:] if c.get('enabled') and c.get('window_title'))
        self.log_debug(f'Saved bots config ({enabled_count} bot(s) enabled)')

    def _build_template_match_tab(self, tab):
        """Template Matching tab — sleeping bag, auto-close, autowalk beep, etc."""
        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0, bd=0)
        vscroll = tk.Scrollbar(tab, orient='vertical', command=canvas.yview,
                               bg=BG, troughcolor=BG, width=18, highlightthickness=0, bd=0)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        body = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=body, anchor='nw')
        def _resize(e=None):
            canvas.configure(scrollregion=canvas.bbox('all'))
            canvas.itemconfig(win_id, width=canvas.winfo_width())
        body.bind('<Configure>', _resize)
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(win_id, width=e.width))
        def _wheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), 'units')
        canvas.bind('<Enter>', lambda _: canvas.bind_all('<MouseWheel>', _wheel))
        canvas.bind('<Leave>', lambda _: canvas.unbind_all('<MouseWheel>'))

        # ── Master Switch ─────────────────────────────────────────────────────
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(6, 4))
        section_label(c, 'Template Matching  [Experimental]')
        tk.Label(c, text='Matches pixel-perfect icons against the live game window. '
                         'Faster and more reliable than OCR for fixed UI elements.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=420, justify='left').pack(anchor='w', padx=8, pady=(0, 4))
        self.tm_master_var = tk.BooleanVar(
            value=self.config.get('template_match_enabled', False))
        def _on_tm_master(*_):
            self.config['template_match_enabled'] = self.tm_master_var.get()
            try: self.save_config()
            except Exception: pass
        self.tm_master_var.trace_add('write', _on_tm_master)
        toggle_row(c, '★ Enable Template Matching  (master switch)',
                   self.tm_master_var).pack(anchor='w', padx=8, pady=(0, 4))
        tk.Label(c, text='Start/restart the bot after toggling this — the thread is '
                         'launched at bot start time.',
                 bg=SURFACE, fg=AMBER, font=(FONT_UI[0], 8, 'bold'),
                 wraplength=420, justify='left').pack(anchor='w', padx=8, pady=(0, 4))

        # Global match threshold slider
        thr_row = tk.Frame(c, bg=SURFACE)
        thr_row.pack(fill='x', padx=8, pady=(0, 6))
        tk.Label(thr_row, text='Match threshold:', bg=SURFACE, fg=FG,
                 font=FONT_UI, width=16, anchor='w').pack(side='left')
        self.tm_threshold_var = tk.DoubleVar(
            value=float(self.config.get('tm_threshold', 0.72)))
        _thr_lbl = tk.Label(thr_row,
                            text=f"{self.tm_threshold_var.get():.2f}",
                            bg=BORDER, fg=ACCENT,
                            font=('Consolas', 8, 'bold'), width=5)
        _thr_lbl.pack(side='right', padx=4)
        def _on_thr_slide(v):
            val = round(float(v), 2)
            self.tm_threshold_var.set(val)
            _thr_lbl.config(text=f'{val:.2f}')
            self.config['tm_threshold'] = val
            try: self.save_config()
            except Exception: pass
        ttk.Scale(thr_row, from_=0.50, to=0.95, orient='horizontal',
                  variable=self.tm_threshold_var,
                  command=_on_thr_slide).pack(side='left', fill='x', expand=True)
        tk.Label(c, text='0.72 recommended — lower if templates miss, raise if false positives occur.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 7, 'italic'),
                 wraplength=420, justify='left').pack(anchor='w', padx=8, pady=(0, 6))

        # ── Sleeping Bag — Auto-Sleep ─────────────────────────────────────────
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(0, 4))
        section_label(c, 'Sleeping Bag — Auto-Sleep')
        tk.Label(c, text='Detects the sleeping bag icon in your inventory. When fatigue '
                         'reaches the threshold the bot clicks it, OCRs the random '
                         'challenge word, types it, and confirms successful sleep.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=420, justify='left').pack(anchor='w', padx=8, pady=(0, 4))
        self.tm_sleep_var = tk.BooleanVar(
            value=self.config.get('tm_sleep_enabled', False))
        def _on_tm_sleep(*_):
            self.config['tm_sleep_enabled'] = self.tm_sleep_var.get()
            try: self.save_config()
            except Exception: pass
        self.tm_sleep_var.trace_add('write', _on_tm_sleep)
        toggle_row(c, 'Enable auto-sleep via sleeping bag',
                   self.tm_sleep_var).pack(anchor='w', padx=8, pady=(0, 4))
        thr_row = tk.Frame(c, bg=SURFACE)
        thr_row.pack(fill='x', padx=8, pady=(0, 4))
        tk.Label(thr_row, text='Fatigue threshold (%):', bg=SURFACE, fg=FG,
                 font=FONT_UI).pack(side='left')
        self.tm_sleep_threshold_var = tk.StringVar(
            value=str(self.config.get('tm_sleep_fatigue_threshold', 90)))
        def _on_thr(*_):
            try:
                self.config['tm_sleep_fatigue_threshold'] = int(self.tm_sleep_threshold_var.get())
                self.save_config()
            except Exception:
                pass
        self.tm_sleep_threshold_var.trace_add('write', _on_thr)
        tk.Spinbox(thr_row, from_=50, to=99, width=5,
                   textvariable=self.tm_sleep_threshold_var,
                   bg=SURFACE, fg=FG, buttonbackground=BORDER, relief='flat',
                   font=FONT_UI).pack(side='left', padx=(8, 0))
        tk.Label(thr_row, text='— sleeps when fatigue \u2265 this value',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8)).pack(side='left', padx=(6, 0))
        tk.Label(c, text='Templates: static_sleepingbag.png \u2192 click \u2192 OCR word \u2192 type \u2192 successful_sleep.png',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 7, 'italic'),
                 wraplength=420, justify='left').pack(anchor='w', padx=8, pady=(2, 2))
        tk.Label(c, text='\u25b6 Trigger: clicks sleeping bag \u2192 OCRs random word from sleep dialog \u2192 types it human-speed \u2192 confirms via successful_sleep.png \u2192 resets fatigue to 0%',
                 bg=SURFACE, fg=GREEN, font=(FONT_UI[0], 7, 'italic'),
                 wraplength=420, justify='left').pack(anchor='w', padx=8, pady=(0, 6))

        # ── Auto-Close Windows ────────────────────────────────────────────────
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(0, 4))
        section_label(c, 'Auto-Close Windows')
        tk.Label(c, text='Detects open bank / shop / client-settings windows and '
                         'automatically clicks their close button.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=420, justify='left').pack(anchor='w', padx=8, pady=(0, 4))
        self.tm_auto_close_var = tk.BooleanVar(
            value=self.config.get('tm_auto_close_enabled', False))
        def _on_tm_ac(*_):
            self.config['tm_auto_close_enabled'] = self.tm_auto_close_var.get()
            try: self.save_config()
            except Exception: pass
        self.tm_auto_close_var.trace_add('write', _on_tm_ac)
        toggle_row(c, 'Auto-close bank / shop / settings windows',
                   self.tm_auto_close_var).pack(anchor='w', padx=8, pady=(0, 4))
        tk.Label(c, text='Templates: close_window_bank1.png, close_windowshop.png, '
                         'client_settings_closewindow.png',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 7, 'italic'),
                 wraplength=420, justify='left').pack(anchor='w', padx=8, pady=(0, 2))
        tk.Label(c, text='\u25b6 Trigger: left-clicks the matched close button (3s cooldown between closes)',
                 bg=SURFACE, fg=GREEN, font=(FONT_UI[0], 7, 'italic'),
                 wraplength=420, justify='left').pack(anchor='w', padx=8, pady=(0, 6))

        # ── Template Reference ────────────────────────────────────────────────
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(0, 8))
        section_label(c, 'All Loaded Templates')
        # (fname, description, action_text, action_color)
        # GREEN = fully implemented, AMBER = partial, MUTED = None/WIP
        ref_lines = [
            ('30_30_fullinventory.png',
             'Full inventory indicator',
             'None: WIP', MUTED),
            ('autowalkheadingto.png',
             'Walk in progress (heading to)',
             'None: WIP', MUTED),
            ('autowalkarrived.png',
             'Walk arrived at destination',
             '\u25b6 Two-tone beep (1200+1500 Hz)', GREEN),
            ('bank_ui_bar.png',
             'Bank window open',
             'None: WIP', MUTED),
            ('client_settings_closewindow.png',
             'Settings popup close button',
             '\u25b6 Auto-clicks close button', GREEN),
            ('close_windowshop.png',
             'Shop window close button',
             '\u25b6 Auto-clicks close button', GREEN),
            ('close_window_bank1.png',
             'Bank window close button',
             '\u25b6 Auto-clicks close button', GREEN),
            ('fatgiue100red.png',
             'Fatigue bar at 100% (variant 1)',
             '\u25b6 Updates fatigue display to 100%  (partial)', AMBER),
            ('fatigue100red2.png',
             'Fatigue bar at 100% (variant 2)',
             '\u25b6 Updates fatigue display to 100%  (partial)', AMBER),
            ('goldcrown1.png',
             'Gold crown J-Mod in chat',
             '\u25b6 Stops bot  [controlled by Anti-Ban tab]', GREEN),
            ('silvercrown.png',
             'Silver crown mod in chat',
             '\u25b6 Stops bot  [controlled by Anti-Ban tab]', GREEN),
            ('loadout_fight1.png',
             'Fight loadout button (bank)',
             'None: WIP', MUTED),
            ('loadout_mining.png',
             'Mining loadout button (bank)',
             'None: WIP', MUTED),
            ('RSC_TemplateTopRight.png',
             'Window top-right anchor / calibration',
             'None: WIP', MUTED),
            ('Screenshot_1.png',
             'Window anchor (duplicate reference)',
             'None: WIP', MUTED),
            ('static_sleepingbag.png',
             'Sleeping bag in inventory',
             '\u25b6 Click \u2192 OCR word \u2192 type \u2192 confirm sleep \u2192 fatigue=0', GREEN),
            ('static_bones.png',
             'Bones icon in inventory',
             'None: WIP', MUTED),
            ('Static_icon.png',
             'Icon panel UI anchor',
             'None: WIP  (region calibration)', MUTED),
            ('static_inventory.png',
             'Inventory panel UI anchor',
             'None: WIP  (region calibration)', MUTED),
            ('static_map.png',
             'Map panel UI anchor',
             'None: WIP  (region calibration)', MUTED),
            ('static_friends.png',
             'Friends panel UI anchor',
             'None: WIP  (region calibration)', MUTED),
            ('static_spellbook.png',
             'Spellbook panel UI anchor',
             'None: WIP  (region calibration)', MUTED),
            ('static_stats.png',
             'Stats panel UI anchor',
             'None: WIP  (region calibration)', MUTED),
            ('successful_sleep.png',
             'Sleep success confirmation screen',
             '\u25b6 Confirms sleep OK \u2192 resets fatigue to 0%', GREEN),
            ('youhavebeenstandingherefor5minutes.png',
             'Anti-AFK "standing here" message',
             '\u25b6 Nudge mouse 1px + beep 1000 Hz', GREEN),
        ]
        for fname, desc, action, acolor in ref_lines:
            row = tk.Frame(c, bg=SURFACE)
            row.pack(fill='x', padx=8, pady=1)
            tk.Label(row, text=fname, bg=SURFACE, fg=ACCENT,
                     font=('Consolas', 8), anchor='w', width=36).pack(side='left')
            col = tk.Frame(row, bg=SURFACE)
            col.pack(side='left', padx=(4, 0), fill='x', expand=True)
            tk.Label(col, text=desc, bg=SURFACE, fg=FG,
                     font=(FONT_UI[0], 8), anchor='w').pack(anchor='w')
            tk.Label(col, text=action, bg=SURFACE, fg=acolor,
                     font=(FONT_UI[0], 7, 'italic'), anchor='w').pack(anchor='w')
        tk.Frame(c, bg=SURFACE).pack(pady=(0, 4))

    def _build_experimental_tab(self, tab):
        """Experimental features tab."""
        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0, bd=0)
        vscroll = tk.Scrollbar(tab, orient='vertical', command=canvas.yview,
                               bg=BG, troughcolor=BG, width=18, highlightthickness=0, bd=0)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        body = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=body, anchor='nw')
        def _resize(e=None):
            canvas.configure(scrollregion=canvas.bbox('all'))
            canvas.itemconfig(win_id, width=canvas.winfo_width())
        body.bind('<Configure>', _resize)
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(win_id, width=e.width))
        def _wheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), 'units')
        canvas.bind('<Enter>', lambda _: canvas.bind_all('<MouseWheel>', _wheel))
        canvas.bind('<Leave>', lambda _: canvas.unbind_all('<MouseWheel>'))

        # ── Teleport Detector (moved from Anti-Ban) ─────────────────────────
        co_tp, c_tp = card(body, padx=0, pady=6)
        co_tp.pack(fill='x', pady=(0, 6))
        section_label(c_tp, 'Teleport Detector  [Experimental]')

        self.teleport_detect_var = tk.BooleanVar(
            value=self.config.get('teleport_detection_enabled', True))
        toggle_row(c_tp, 'Stop if scenery changes drastically  [DEFAULT ON]',
                   self.teleport_detect_var).pack(anchor='w', padx=8, pady=(2, 2))

        self.teleport_thresh_var = tk.IntVar(
            value=int(self.config.get('teleport_threshold', 35)))
        tr = tk.Frame(c_tp, bg=SURFACE)
        tr.pack(fill='x', padx=8, pady=(0, 4))
        tk.Label(tr, text='Sensitivity', bg=SURFACE, fg=MUTED,
                 font=FONT_UI, width=10, anchor='w').pack(side='left')
        tp_lbl = tk.Label(tr, text=str(self.teleport_thresh_var.get()),
                          bg=BORDER, fg=ACCENT, font=('Consolas', 8, 'bold'), width=4)
        tp_lbl.pack(side='right', padx=4)
        ttk.Scale(tr, from_=15, to=80, orient='horizontal',
                  variable=self.teleport_thresh_var,
                  command=lambda v: (self.teleport_thresh_var.set(int(float(v))),
                                     tp_lbl.config(text=str(int(float(v)))))
                  ).pack(side='left', fill='x', expand=True)

        # On-trigger chat reactions: preset multi-select + custom + random pick.
        tk.Label(c_tp, text='On-trigger chat reactions:',
                 bg=SURFACE, fg=FG, font=FONT_UI).pack(anchor='w', padx=8, pady=(4, 2))

        self.teleport_pick_random_var = tk.BooleanVar(
            value=bool(self.config.get('teleport_pick_random', True)))
        tk.Checkbutton(c_tp, text='Let bot randomly pick from enabled reactions',
                       variable=self.teleport_pick_random_var,
                       bg=SURFACE, fg=FG, selectcolor=BORDER,
                       activebackground=SURFACE, activeforeground=FG,
                       font=FONT_UI).pack(anchor='w', padx=14, pady=(0, 2))

        TELEPORT_DEFAULT = ('wtf,waeaw,what,okay,hey,what thef,whatfhekfk,wut,'
                            'wowa,wow,hello??,admin?,what is there an admin here?,'
                            'who tp,why tp,what tpd me for')

        tk.Label(c_tp, text='Edit this if you want, separated by , commas, no spacing.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic')
                 ).pack(anchor='w', padx=14, pady=(2, 2))

        self.teleport_reactions_var = tk.StringVar(
            value=self.config.get('teleport_reactions_text', TELEPORT_DEFAULT))
        ent = ttk.Entry(c_tp, textvariable=self.teleport_reactions_var,
                        style='TEntry')
        ent.pack(fill='x', padx=14, pady=(0, 6))

        def _save_tp(*_):
            self.config['teleport_detection_enabled'] = bool(self.teleport_detect_var.get())
            try:
                self.config['teleport_threshold'] = int(self.teleport_thresh_var.get())
            except (ValueError, tk.TclError):
                pass
            self.config['teleport_reactions_text'] = self.teleport_reactions_var.get()
            self.config['teleport_pick_random'] = bool(self.teleport_pick_random_var.get())
            try: self.save_config()
            except Exception: pass
        self.teleport_reactions_var.trace_add('write', _save_tp)
        self.teleport_pick_random_var.trace_add('write', _save_tp)
        self.teleport_detect_var.trace_add('write', _save_tp)
        self.teleport_thresh_var.trace_add('write', _save_tp)

        # ── Stop When Inventory Full  [Experimental] ─────────────────────────
        co_sf, c_sf = card(body, padx=0, pady=6)
        co_sf.pack(fill='x', pady=(0, 6))
        section_label(c_sf, 'Stop When Inventory Full  [Experimental]')
        toggle_row(c_sf, 'Stop when inventory full (template-only check, 30/30)',
                   self.stop_on_full_var).pack(anchor='w', padx=8, pady=(4, 0))
        tk.Label(c_sf,
                 text='⚠ OFF by default. Has no effect when Banking is enabled (banking handles full inv).',
                 bg=SURFACE, fg=AMBER, font=(FONT_UI[0], 8, 'italic')
                 ).pack(anchor='w', padx=30, pady=(0, 6))

        # ── Anti-AFK (formerly Clickback) ───────────────────────────────────
        # (Click Verification moved out of Experimental — now lives in Settings → Mouse Profile.)
        co_cb, c_cb = card(body, padx=0, pady=6)
        co_cb.pack(fill='x', pady=(0, 6))
        section_label(c_cb, 'Anti-AFK  [Experimental]')

        # Standing here → click furthest ore toggle
        self.standing_far_ore_var = tk.BooleanVar(
            value=bool(self.config.get('standing_here_far_ore_enabled', True)))
        def _on_standing_far_ore(*_):
            self.config['standing_here_far_ore_enabled'] = bool(self.standing_far_ore_var.get())
            try: self.save_config()
            except Exception: pass
        self.standing_far_ore_var.trace_add('write', _on_standing_far_ore)
        toggle_row(c_cb, 'Click furthest ore on "Standing here" (walks character)',
                   self.standing_far_ore_var).pack(anchor='w', padx=8, pady=(4, 0))
        tk.Label(c_cb,
                 text='When detected, bot flags the furthest visible ore for its next click — walking the character to reset the AFK timer.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=380, justify='left').pack(anchor='w', padx=30, pady=(0, 6))

        self.clickback_var = tk.BooleanVar(value=self.config.get('clickback_enabled', False))
        self.clickback_var.trace_add('write', self._on_clickback_change)
        toggle_row(c_cb, 'Enable periodic Anti-AFK clicks',
                   self.clickback_var).pack(anchor='w', padx=8, pady=(4, 0))

        cb_row = tk.Frame(c_cb, bg=SURFACE)
        cb_row.pack(fill='x', padx=8, pady=(2, 2))
        tk.Label(cb_row, text='Min minutes:', bg=SURFACE, fg=FG,
                 font=FONT_UI).pack(side='left')
        self.clickback_min_var = tk.StringVar(
            value=str(self.config.get('clickback_min_min', 5)))
        tk.Spinbox(cb_row, from_=1, to=120, width=5,
                   textvariable=self.clickback_min_var,
                   bg=SURFACE, fg=FG, buttonbackground=BORDER, relief='flat',
                   font=FONT_UI).pack(side='left', padx=(4, 10))
        tk.Label(cb_row, text='Max minutes:', bg=SURFACE, fg=FG,
                 font=FONT_UI).pack(side='left')
        self.clickback_max_var = tk.StringVar(
            value=str(self.config.get('clickback_max_min', 15)))
        tk.Spinbox(cb_row, from_=1, to=120, width=5,
                   textvariable=self.clickback_max_var,
                   bg=SURFACE, fg=FG, buttonbackground=BORDER, relief='flat',
                   font=FONT_UI).pack(side='left', padx=(4, 0))

        tk.Label(c_cb, text='Range you set is jittered down internally so it never fires '
                            'on the round number — e.g. 5 min → 4:00–4:30, 15 min → 14:00–14:30.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=380, justify='left').pack(anchor='w', padx=8, pady=(0, 4))

        # Click A (clickback spot) and Click B (mining tile) capture
        ab_row = tk.Frame(c_cb, bg=SURFACE)
        ab_row.pack(fill='x', padx=8, pady=(2, 4))
        a = self.config.get('clickback_a')
        b = self.config.get('clickback_b')
        self._cb_a_label = tk.Label(ab_row,
                                    text=f"A: {a[0]},{a[1]}" if a else 'A: not set',
                                    bg=SURFACE, fg=FG, font=FONT_UI)
        self._cb_a_label.pack(side='left', padx=(0, 4))
        ttk.Button(ab_row, text='Set Click A',
                   command=lambda: self._capture_screen_click(self._save_clickback_a),
                   style='Util.TButton').pack(side='left', padx=(0, 12))
        self._cb_b_label = tk.Label(ab_row,
                                    text=f"B: {b[0]},{b[1]}" if b else 'B: not set',
                                    bg=SURFACE, fg=FG, font=FONT_UI)
        self._cb_b_label.pack(side='left', padx=(0, 4))
        ttk.Button(ab_row, text='Set Click B',
                   command=lambda: self._capture_screen_click(self._save_clickback_b),
                   style='Util.TButton').pack(side='left')

        tk.Label(c_cb, text='A = clickback spot (somewhere safe). B = mining tile to return to. '
                            'On each fire: click A, brief pause, click B.',
                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),
                 wraplength=380, justify='left').pack(anchor='w', padx=8, pady=(0, 6))

        def _save_clickback(*_):
            for k, v in (('clickback_min_min', self.clickback_min_var),
                         ('clickback_max_min', self.clickback_max_var)):
                try:
                    self.config[k] = int(v.get())
                except (ValueError, tk.TclError):
                    pass
        self.clickback_min_var.trace_add('write', _save_clickback)
        self.clickback_max_var.trace_add('write', _save_clickback)

        # WalkTo destinations were moved to Mining -> Banking.
        # Keep hidden compatibility vars/labels so save/update paths remain stable.
        self.walkto_enabled_var = tk.BooleanVar(value=bool(self.config.get('walkto_enabled', False)))
        self.walkto_min_var = tk.StringVar(value=str(self.config.get('walkto_min_clicks', 35)))
        self.walkto_max_var = tk.StringVar(value=str(self.config.get('walkto_max_clicks', 50)))
        self.walkto_beep1_enabled_var = tk.BooleanVar(
            value=bool(self.config.get('walkto_beep1_enabled', True)))
        self.walkto_beep1_var = tk.StringVar(
            value=str(self.config.get('walkto_beep1_secs', 40)))
        self._walkto_status_label = tk.Label(body)

        # ── Hotkeys ──────────────────────────────────────────────────────────
        co_hk, c_hk = card(body, padx=0, pady=6)
        co_hk.pack(fill='x', pady=(0, 6))
        section_label(c_hk, 'Hotkeys  [Master Bot Only]')
        hk_rows = [
            ('F6', 'Start / Stop bot'),
        ]
        for key, desc in hk_rows:
            row = tk.Frame(c_hk, bg=SURFACE)
            row.pack(fill='x', padx=8, pady=2)
            tk.Label(row, text=key, bg=BORDER, fg=ACCENT,
                     font=('Consolas', 9, 'bold'), width=4, relief='flat',
                     padx=4).pack(side='left', padx=(0, 8))
            tk.Label(row, text=desc, bg=SURFACE, fg=FG,
                     font=FONT_UI, anchor='w').pack(side='left', fill='x')

    def _apply_antiban_master_state(self):
        """Gray out / reactivate all sub-widgets under the anti-ban master toggle."""
        c = getattr(self, '_antiban_sub_frame', None)
        if c is None:
            return
        enabled = bool(self.antiban_master_var.get())
        state = 'normal' if enabled else 'disabled'
        children = c.winfo_children()
        skip = getattr(self, '_antiban_master_anchor_count', 0)
        def _walk(widget):
            try:
                cls = widget.winfo_class()
                if cls in ('TCheckbutton', 'Checkbutton', 'TEntry', 'Entry',
                           'TScale', 'Scale', 'TRadiobutton', 'Radiobutton',
                           'TCombobox', 'TButton', 'Button'):
                    widget.configure(state=state)
            except Exception:
                pass
            for ch in widget.winfo_children():
                _walk(ch)
        for w in children[skip:]:
            _walk(w)

    # ── Speed / antiban interlock ────────────────────────────────────────────

    def _on_speed_change(self):
        """When Fast/Super-Fast is selected, force-disable mouse-outside-window."""
        mode = self.mining_speed_var.get()
        if mode in ('ultra_fast', 'fast', 'super_fast'):
            self.mouse_outside_var.set(False)
            if hasattr(self, '_mouse_outside_toggle'):
                self._mouse_outside_toggle.set_disabled(True)
        else:
            if hasattr(self, '_mouse_outside_toggle'):
                self._mouse_outside_toggle.set_disabled(False)

    def _on_mouse_outside_change(self):
        """When mouse-outside is toggled on, force Lazy mode."""
        if self.mouse_outside_var.get():
            self.mining_speed_var.set('lazy')

    def _on_hover_mode_change(self, *_):
        """Hover Mode interlocks: disable mouse-outside and lazy-idle when enabled.
        Writes directly to the shared config so a running bot picks it up instantly."""
        enabled = bool(self.hover_mode_var.get())
        self.config['hover_mode_enabled'] = enabled
        if enabled:
            if hasattr(self, 'mouse_outside_var'):
                self.mouse_outside_var.set(False)
            if hasattr(self, 'lazy_idle_pause_var'):
                self.lazy_idle_pause_var.set(False)
            self.config['mouse_outside_window'] = False
            self.config['lazy_idle_pause_enabled'] = False
        try:
            self.save_config()
        except Exception:
            pass

    def _on_clickback_change(self, *_):
        """Clickback cannot coexist with camera auto-rotation (fixed spots require
        a known camera angle). When enabled, camera rotation is force-disabled."""
        if not hasattr(self, 'clickback_var'):
            return
        enabled = bool(self.clickback_var.get())
        if enabled:
            # Disable camera rotation — clickback clicks fixed coords so rotation
            # would invalidate the A/B positions.
            if hasattr(self, 'camera_rotation_var'):
                self.camera_rotation_var.set(False)
            self.config['camera_rotation_enabled'] = False
        self.config['clickback_enabled'] = enabled
        try:
            self.save_config()
        except Exception:
            pass

    def _capture_screen_click(self, on_click):
        """Open a fullscreen translucent overlay; capture one mouse click and
        pass its absolute screen coords to on_click(x, y)."""
        ov = tk.Toplevel(self.root)
        ov.attributes('-fullscreen', True)
        ov.attributes('-alpha', 0.25)
        ov.configure(bg='black', cursor='crosshair')
        ov.attributes('-topmost', True)
        tk.Label(ov, text='Click anywhere to set spot — Esc to cancel',
                 bg='black', fg='white',
                 font=('Segoe UI', 14, 'bold')).place(relx=0.5, rely=0.04, anchor='n')
        def _grab(e):
            x, y = e.x_root, e.y_root
            ov.destroy()
            try:
                on_click(x, y)
            except Exception as ex:
                self.log_debug(f'capture_click callback error: {ex}')
        ov.bind('<Button-1>', _grab)
        ov.bind('<Escape>', lambda e: ov.destroy())
        ov.focus_force()

    def _save_teleport_reactions(self, presets):
        """Persist teleport-detector settings (toggle, threshold, enabled presets,
        custom phrases, random-pick toggle) on any change."""
        try:
            sel = [presets[i] for i in self._teleport_listbox.curselection()]
        except Exception:
            sel = []
        self.config['teleport_detection_enabled'] = bool(self.teleport_detect_var.get())
        try:
            self.config['teleport_threshold'] = int(self.teleport_thresh_var.get())
        except (ValueError, tk.TclError):
            pass
        self.config['teleport_reactions_enabled'] = sel
        self.config['teleport_reactions_custom'] = self.teleport_custom_var.get()
        self.config['teleport_pick_random'] = bool(self.teleport_pick_random_var.get())
        try: self.save_config()
        except Exception: pass

    def _save_clickback_a(self, x, y):
        self.config['clickback_a'] = [int(x), int(y)]
        if hasattr(self, '_cb_a_label'):
            self._cb_a_label.config(text=f'A: {x},{y}')
        try: self.save_config()
        except Exception: pass

    def _save_clickback_b(self, x, y):
        self.config['clickback_b'] = [int(x), int(y)]
        if hasattr(self, '_cb_b_label'):
            self._cb_b_label.config(text=f'B: {x},{y}')
        try: self.save_config()
        except Exception: pass

    def _on_theme_change(self, event=None):
        """Save theme/font and restart the GUI."""
        theme = self.theme_var.get()
        if theme == 'RSC Classic':
            self.font_var.set('Courier New')
        self.config['theme'] = self.theme_var.get()
        self.config['font'] = self.font_var.get()
        self.save_config()
        self._restart = True
        self.on_closing()

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def update_inventory(self, cur, total):
        try:
            pct = cur / max(total, 1)
            color = RED if pct >= 0.90 else AMBER if pct >= 0.70 else GREEN
            self.live_inventory_label.config(text=f'{cur}/{total}', fg=color)
        except Exception:
            pass

    def on_confidence_change(self, value):
        try:
            self.confidence_value_label.config(text=f'{float(value):.2f}')
        except Exception:
            pass

    def increment_obtain_count(self):
        try:
            self.obtain_count += 1
            self.log_debug(f'Ore obtained  ({self.obtain_count} total)')
        except Exception:
            pass

    def reset_obtain_count(self):
        try:
            self.obtain_count = 0
        except Exception:
            pass

    def _lbl(self, widget, text, fg=None):
        """Set label text only if it changed — avoids unnecessary tkinter redraws."""
        key = id(widget)
        if self._live_label_cache.get(key) == (text, fg):
            return
        self._live_label_cache[key] = (text, fg)
        if fg is not None:
            widget.config(text=text, fg=fg)
        else:
            widget.config(text=text)

    def _cfg(self, widget, **kw):
        """Generic cache-checked widget.config(**kw) — skips redraw when unchanged."""
        key = id(widget)
        if self._live_label_cache.get(key) == kw:
            return
        self._live_label_cache[key] = kw
        widget.config(**kw)

    def update_live_stats(self, fatigue=None, last_click_ms=None, mouse_x=None, mouse_y=None, inventory_count=None, inventory_total=30):
        """Update live statistics display in real-time"""
        try:
            # Update runtime — only redraws when the second changes
            if hasattr(self, '_start_time') and self._start_time:
                elapsed = int(time.time() - self._start_time) + int(getattr(self, '_runtime_saved_secs', 0))
                hrs, rem = divmod(elapsed, 3600)
                mins, secs = divmod(rem, 60)
                if hrs > 0:
                    rt_str = f'{hrs}:{mins:02d}:{secs:02d}'
                else:
                    rt_str = f'{mins:02d}:{secs:02d}'
                # Stats box runtime
                try:
                    self._lbl(self.live_runtime_box_label, rt_str)
                except Exception:
                    pass
                # Keep status dot in sync with runtime
                try:
                    self._lbl(self.status_dot, f'● RUNNING  {rt_str}', fg=GREEN)
                except Exception:
                    pass

            # Update fatigue — color ramps green→amber→red as fatigue climbs
            if fatigue is not None:
                color = RED if fatigue >= 85 else AMBER if fatigue >= 60 else GREEN if fatigue >= 30 else MUTED
                self._lbl(self.live_fatigue_label, f'{int(fatigue)}%', fg=color)

            # Update inventory count (X/total)
            if inventory_count is not None:
                self.update_inventory(int(inventory_count), int(inventory_total))

            # Update mouse coords + last-click age in the stats box.
            coord_str = f'{int(mouse_x)}, {int(mouse_y)}' if (mouse_x is not None and mouse_y is not None) else '----, ----'
            if last_click_ms is None or last_click_ms == 0:
                click_str = '----ms'
            else:
                elapsed_ms = int(time.time() * 1000 - last_click_ms)
                elapsed_ms = (elapsed_ms // 250) * 250
                click_str = f'{elapsed_ms}ms'
            try:
                self._lbl(self.live_mouse_box_label, coord_str)
                self._lbl(self.live_click_ms_box_label, click_str)
            except Exception:
                pass
            # Keep hidden top-bar labels in sync (no-op since they're unpacked)
            self._lbl(self.mouse_coord_label, f'{coord_str}   {click_str}')

        except Exception as e:
            print(f"[GUI] Error updating live stats: {e}")

    def log_debug(self, msg):
        line = f'{time.strftime("%H:%M:%S")}  {msg}\n'
        try:
            self.debug_text.config(state='normal')
            self.debug_text.insert('end', line)
            lines = int(self.debug_text.index('end-1c').split('.')[0])
            if lines > 500:
                self.debug_text.delete('1.0', f'{lines - 500}.0')
            self.debug_text.see('end')
            self.debug_text.config(state='disabled')
        except Exception:
            pass
        # Mirror to HUD debug panel — always write even when panel is collapsed.
        try:
            hud_dbg = getattr(self, '_mini_hud_debug', None)
            if hud_dbg and hud_dbg.winfo_exists():
                hud_dbg.config(state='normal')
                hud_dbg.insert('end', line)
                hud_lines = int(hud_dbg.index('end-1c').split('.')[0])
                if hud_lines > 8:
                    hud_dbg.delete('1.0', f'{hud_lines - 8}.0')
                hud_dbg.see('end')
                hud_dbg.config(state='disabled')
        except Exception:
            pass
    def on_window_selected(self, event=None):
        self._update_win_info_label()
        self.flash_window(times=3)

    def _update_win_info_label(self):
        if not hasattr(self, '_win_info_label'):
            return
        display = self.window_var.get()
        info = self._window_info_map.get(display)
        if info:
            text = (f'PID {info["pid"]}   '
                    f'Position: {info["pos"]}   '
                    f'Size: {info["size"]}')
        else:
            text = display
        self._win_info_label.config(text=text)

    def refresh_windows(self):
        java_windows = self.get_java_windows()
        if hasattr(self, '_window_combo'):
            self._window_combo['values'] = java_windows
            if java_windows:
                self._window_combo.set(java_windows[0])
        self._update_win_info_label()
        self.log_debug(f'Refreshed: {len(java_windows)} Java window(s) found')

    def _bring_selected_to_front(self):
        """Bring the currently selected game window to the foreground."""
        title = self._title_from_display(self.window_var.get())
        if not title:
            return
        try:
            hwnd = win32gui.FindWindow(None, title)
            if not hwnd:
                return
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            except Exception:
                pass
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
        except Exception as e:
            self.log_debug(f'Bring-to-front failed: {e}')

    def flash_window(self, times=3):
        title = self._title_from_display(self.window_var.get())
        def _flash():
            hwnd_list = []
            win32gui.EnumWindows(
                lambda h, _: hwnd_list.append(h) or True
                if title.lower() in win32gui.GetWindowText(h).lower() else True,
                None)
            for hwnd in hwnd_list:
                for _ in range(times):
                    try:
                        win32gui.FlashWindow(hwnd, True); time.sleep(0.18)
                        win32gui.FlashWindow(hwnd, False); time.sleep(0.18)
                    except Exception:
                        pass
        threading.Thread(target=_flash, daemon=True).start()

    def _popup_window_selector(self):
        """Open a standalone Toplevel listing all detected Java windows with live info."""
        java_windows = self.get_java_windows()
        dlg = tk.Toplevel(self.root)
        dlg.title('Select Game Window')
        dlg.geometry('560x340')
        dlg.configure(bg=BG)
        dlg.grab_set()

        tk.Label(dlg, text='Detected Java Windows', bg=BG, fg=ACCENT,
                 font=(FONT_UI[0], 10, 'bold')).pack(pady=(10, 4))

        cols = ('Title', 'PID', 'Position', 'Size')
        tree = ttk.Treeview(dlg, columns=cols, show='headings', height=10)
        for col, w in zip(cols, (220, 70, 100, 90)):
            tree.heading(col, text=col)
            tree.column(col, width=w, anchor='w')

        for d in java_windows:
            info = self._window_info_map.get(d, {})
            tree.insert('', 'end', iid=d, values=(
                info.get('title', d),
                info.get('pid', '?'),
                info.get('pos', '?'),
                info.get('size', '?'),
            ))
        tree.pack(fill='both', expand=True, padx=8, pady=4)

        def _select():
            sel = tree.selection()
            if not sel:
                return
            self.window_var.set(sel[0])
            if hasattr(self, '_window_combo'):
                self._window_combo.set(sel[0])
            self._update_win_info_label()
            self.flash_window(times=3)
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(pady=6)
        ttk.Button(btn_row, text='Select', command=_select,
                   style='Start.TButton').pack(side='left', padx=6)
        ttk.Button(btn_row, text='Cancel', command=dlg.destroy,
                   style='Util.TButton').pack(side='left', padx=6)
        tree.bind('<Double-1>', lambda _: _select())

    def _apply_brightness(self):
        """Overlay a click-through tint on just the game window.
        <100% = darken (black tint), >100% = brighten (white tint), 100% = off."""
        import win32con
        title = self._title_from_display(self.window_var.get())
        pct   = self._brightness_var.get()   # 50-200
        self.config['window_brightness'] = pct

        hwnd = win32gui.FindWindow(None, title)
        if not hwnd:
            self.log_debug(f'Brightness: window "{title}" not found')
            return

        # Tear down any existing tint
        tint = getattr(self, '_brightness_tint', None)
        if tint is not None:
            try: tint.destroy()
            except Exception: pass
            self._brightness_tint = None
        if hasattr(self, '_brightness_job') and self._brightness_job:
            try: self.root.after_cancel(self._brightness_job)
            except Exception: pass
            self._brightness_job = None

        if pct == 100:
            self.log_debug('Brightness: tint cleared (100%)')
            return

        if pct >= 100:
            color = '#FFFFFF'
            alpha = min(0.55, (pct - 100) / 100.0 * 0.55)
        else:
            color = '#000000'
            alpha = min(0.55, (100 - pct) / 50.0 * 0.55)

        tint = tk.Toplevel(self.root)
        tint.overrideredirect(True)
        tint.configure(bg=color)
        tint.attributes('-topmost', True)
        tint.attributes('-alpha', alpha)
        self._brightness_tint = tint

        def reposition():
            try:
                if not win32gui.IsWindow(hwnd):
                    return
                rect = win32gui.GetClientRect(hwnd)
                pt = win32gui.ClientToScreen(hwnd, (0, 0))
                tint.geometry(f'{rect[2]}x{rect[3]}+{pt[0]}+{pt[1]}')
                # Make click-through via WS_EX_LAYERED | WS_EX_TRANSPARENT
                thwnd = int(tint.frame(), 16) if False else win32gui.FindWindow(None, tint.title())
                thwnd = tint.winfo_id()
                # Get the toplevel HWND
                parent = ctypes.windll.user32.GetParent(thwnd)
                while parent:
                    thwnd = parent
                    parent = ctypes.windll.user32.GetParent(thwnd)
                ex = win32gui.GetWindowLong(thwnd, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(thwnd, win32con.GWL_EXSTYLE,
                                       ex | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOOLWINDOW)
            except Exception as e:
                self.log_debug(f'Brightness reposition err: {e}')
            self._brightness_job = self.root.after(250, reposition)

        import ctypes
        reposition()
        self.log_debug(f'Brightness tint {pct}% ({color} a={alpha:.2f}) on "{title}"')

    def start_bot(self):
        if self.running:
            # If bots are paused, START acts as Resume.
            any_paused = any(getattr(b, 'paused', False) for b in getattr(self, 'bots', []))
            if any_paused:
                self.resume_bots()
            return
        # Persist whatever is currently shown in the Clients tab before reading it.
        try:
            self._save_clients_config()
        except Exception:
            pass
        self.save_config()
        if not any(v.get() for v in self.checkbox_vars.values()):
            messagebox.showwarning('Warning', 'No ores selected!')
            return
        if not self.main_model_var.get():
            messagebox.showwarning('Warning', 'At least one model must be enabled!')
            return
        # Roll current-run bot stats into persistent offsets before new bots are created.
        try:
            for _b in getattr(self, 'bots', []):
                if _b:
                    self._stat_rx_offset    += int(getattr(_b, '_mine_count', 0))
                    self._stat_banks_offset += int(getattr(_b, '_banks_completed', 0))
        except Exception:
            pass
        self._total_paused_secs = 0.0
        self._pause_started_at  = None
        self._runtime_saved_secs = 0.0  # always fresh each session
        self.running = True
        self._start_time = time.time()
        self.btn_start.config(state='disabled')
        self.btn_stop.config(state='normal')
        self.btn_pause.config(state='normal', text='⏸ PAUSE')
        self.status_dot.config(text='● RUNNING  00:00', fg=GREEN)
        self.reset_obtain_count()
        self.update_inventory(0, 30)
        self.click_count = 0
        try: self.click_count_label.config(text='⛏ 0')
        except Exception: pass
        seed = self.config.get('mouse_settings', {}).get('mouse_seed', 'auto')
        self.log_debug(f'Bot starting... (mouse seed: {seed})')

        # Multi-client: collect any enabled extra clients from Clients tab.
        clients_cfg = self.config.get('clients', [])
        # Skip slaves whose task isn't Mining for now — WIP modes warn instead.
        extra_clients = []
        for slot in clients_cfg[1:]:
            if not (slot.get('enabled') and slot.get('window_title')):
                continue
            task = slot.get('task', 'Mining')
            if not task.startswith('Mining'):
                self.log_debug(f'⚠ Bot with task "{task}" skipped — only Mining is wired.')
                continue
            extra_clients.append(slot)

        # Interlock: when 2+ bots are active, force-disable single-client-only modes.
        if extra_clients:
            self.config['hover_mode_enabled'] = False
            self.config['powermine_enabled'] = False
            self.config['mouse_outside_window'] = False
            if hasattr(self, 'hover_mode_var'): self.hover_mode_var.set(False)
            if hasattr(self, 'mouse_outside_var'): self.mouse_outside_var.set(False)
            mc_on = self.config.get('multi_client_mode', False)
            self.log_debug(f'Multi-bot active ({1 + len(extra_clients)} bots) — '
                           f'hover/powermine/park-outside disabled. '
                           f'Multi-Client mode: {"ON" if mc_on else "OFF (legacy turn-gate)"}')

        # Resolve hwnds from _window_info_map NOW (before tagging renames the windows).
        # find_window() in bot.py searches by title — but after _tag_window_by_title()
        # renames windows (e.g. "RSCRevolution2" → "RSCRevolution2 — Bot"), a
        # title-based search would fail or return the wrong hwnd.
        master_display = getattr(self, 'window_var', None)
        master_display = master_display.get() if master_display else ''
        master_hwnd = self._window_info_map.get(master_display, {}).get('hwnd')
        # Build window_title → hwnd from in-memory _clients_config which holds
        # _win_display (set on combobox selection).  This key is NOT persisted to
        # config.json, so we can't read it from extra_clients (which comes from
        # self.config['clients']).
        _title_to_hwnd = {}
        for _cs in self._clients_config:
            _disp = _cs.get('_win_display', '')
            _hwnd = self._window_info_map.get(_disp, {}).get('hwnd')
            _wt = _cs.get('window_title', '')
            if _hwnd and _wt:
                _title_to_hwnd[_wt] = _hwnd

        # Window tagging: rename each game window so "— Bot / — Bot2" shows in Alt-Tab.
        self._window_title_originals = {}
        master_title = self.config.get('window_title', '')
        if master_title:
            self._tag_window_by_title(master_title, 'Bot')
        for i, ec in enumerate(extra_clients, start=2):
            self._tag_window_by_title(ec['window_title'], f'Bot{i}')

        self.bot = MiningBot(self.config, self, client_id=0, hwnd=master_hwnd)
        self.bots = [self.bot]
        for i, ec in enumerate(extra_clients, start=1):
            sub_cfg = dict(self.config)
            sub_cfg['window_title'] = ec['window_title']
            if 'ore_checkboxes' in ec:
                # Slave tab now uses same YOLO class names as master — copy directly.
                sub_cfg['ore_checkboxes'] = dict(ec['ore_checkboxes'])
            # Speed always mirrors master — slaves do not override it.
            # Powermine can still be set per-client.
            if 'powermine_enabled' in ec:
                sub_cfg['powermine_enabled'] = ec['powermine_enabled']
            # Per-client top-level overrides.
            # Destination keys (walkto_dest1_*, walkto_train1_*, bank_mine_slot_xy_rel)
            # are intentionally NOT copied here — _walkto_source_dict reads them from
            # sub_cfg['clients'][client_id] when mimic is OFF, and from sub_cfg
            # top-level (= master's values) when mimic is ON.
            for k in ('walkto_enabled', 'walkto_min_clicks', 'walkto_max_clicks',
                      'fixed_ore_spots', 'fixed_ore_spots_enabled', 'autologin_enabled'):
                if k in ec:
                    sub_cfg[k] = ec[k]
            ec_hwnd = _title_to_hwnd.get(ec.get('window_title', ''))
            self.bots.append(MiningBot(sub_cfg, self, client_id=i,
                                       window_title=ec['window_title'],
                                       hwnd=ec_hwnd))
        # Startup auto-login: run TM-based login for every bot with the toggle on.
        # Runs synchronously before threads start so no mining actions interfere.
        self.log_debug(f'🔑 Startup autologin pool: {len(self.bots)} bot(s)')
        for _al_bot in self.bots:
            _al_enabled = _al_bot.config.get('autologin_enabled', True)
            _al_hwnd = getattr(_al_bot, 'hwnd', None)
            self.log_debug(f'  Bot{_al_bot.client_id + 1}: autologin={_al_enabled}  hwnd={_al_hwnd}')
            if not _al_enabled:
                self.log_debug(f'🔑 Auto-login Bot{_al_bot.client_id + 1}: toggle OFF — skipping')
                continue
            try:
                if not _al_bot.hwnd:
                    _al_bot.find_window()
                    self.log_debug(f'  Bot{_al_bot.client_id + 1}: hwnd resolved → {_al_bot.hwnd}')
                _wr = _al_bot._get_current_window_region()
                self.log_debug(f'  Bot{_al_bot.client_id + 1}: region={_wr}')
                if _wr:
                    self.log_debug(f'🔑 Startup auto-login: Bot{_al_bot.client_id + 1}')
                    _al_bot._autologin_running = True
                    try:
                        _al_bot._run_autologin_check(_wr)
                    finally:
                        _al_bot._autologin_running = False
                else:
                    self.log_debug(f'🔑 Auto-login Bot{_al_bot.client_id + 1}: window not found (hwnd={_al_hwnd})')
            except Exception as _ale:
                self.log_debug(f'Auto-login error Bot{_al_bot.client_id + 1}: {_ale}')
        # Multi-client mode: master's loop handles all windows; slaves only run detection.
        if self.config.get('multi_client_mode', False) and len(self.bots) > 1:
            self.bot._peer_bots = list(self.bots[1:])
            for sub in self.bots[1:]:
                sub._background_only = True
            # Disable the old turn-gate (not needed in multi-client mode)
            MiningBot._ACTIVE_CLIENT_IDS = []
            MiningBot._TURN_IDX[0] = 0
            MiningBot._TURN_SINCE[0] = time.time()
            for b in self.bots:
                print(f'[MC] Bot{b.client_id+1} hwnd={b.hwnd} title={b.config.get("window_title","?")}')
            self.log_debug(f'Multi-Client mode ON — master cycles {len(self.bots)} windows')
        else:
            # Initialise round-robin turn state BEFORE threads start so the gate
            # in bot.py sees the correct list from the very first iteration.
            MiningBot._ACTIVE_CLIENT_IDS = [b.client_id for b in self.bots]
            MiningBot._TURN_IDX[0] = 0
            MiningBot._TURN_SINCE[0] = time.time()
            self.log_debug(f'Turn order: {MiningBot._ACTIVE_CLIENT_IDS}')

        self.bot_thread = threading.Thread(target=self._run_bot, daemon=True)
        self.bot_thread.start()
        # Launch secondary bot threads.
        self._extra_threads = []
        for sub in self.bots[1:]:
            bot_name = f'Bot{sub.client_id + 1}'
            t = threading.Thread(target=lambda b=sub: self._run_extra_bot(b),
                                 daemon=True, name=f'bot-{sub.client_id}')
            t.start()
            self._extra_threads.append(t)
            self.log_debug(f'{bot_name} thread started → window: {sub.config.get("window_title", "?")}')
        self._schedule_live_update()
        self._start_overlay()

    def _schedule_live_update(self):
        """Periodically update live statistics from bot."""
        # Always get live cursor position regardless of bot state
        try:
            _mx, _my = win32api.GetCursorPos()
        except Exception:
            _mx, _my = None, None
        if self.running and self.bot:
            # Live walkto-counter in Experimental tab + top bar.
            try:
                nxt = getattr(self.bot, '_mc_walkto_next_at', None)
                if nxt is None:
                    nxt = getattr(self.bot, '_walkto_next_at', None)
                cur = getattr(self.bot, '_mine_count', 0)
                wt_enabled = self.config.get('walkto_enabled', False)
                lbl = getattr(self, '_walkto_status_label', None)
                bar_lbl = getattr(self, '_walkto_bar_label', None)
                if nxt is not None and wt_enabled:
                    remaining = max(0, nxt - cur)
                    if lbl is not None:
                        self._lbl(lbl, f'Clicks until walkto: {remaining}  (at {nxt}, current {cur})')
                    if bar_lbl is not None:
                        self._lbl(bar_lbl, f'🚶 {remaining}')
                else:
                    if lbl is not None:
                        self._lbl(lbl, 'Clicks until walkto: — (walkto disabled)')
                    if bar_lbl is not None:
                        self._lbl(bar_lbl, '')
            except Exception:
                pass
            try:
                self.update_live_stats(
                    fatigue=self.bot.current_fatigue,
                    last_click_ms=self.bot.last_click_time,
                    mouse_x=_mx,
                    mouse_y=_my,
                    # Inventory is intentionally omitted here — it is updated
                    # exclusively by the OCR callback in bot.py so the display
                    # only ever reflects the real #/30 read from the game.
                )
                # Clicked-rocks counter in top bar
                n = int(getattr(self.bot, '_mine_count', 0))
                self._lbl(self.click_count_label, f'⛏ {n}')
                # Break countdown / next-break countdown
                be = getattr(self.bot, 'break_end_time', 0) or 0
                remaining = int(be - time.time())
                breaks_on = self.config.get('break_settings', {}).get('breaks_enabled', False)
                if remaining > 0:
                    mm, ss = divmod(remaining, 60)
                    self._lbl(self.break_countdown_label, f'☕ BREAK {mm:02d}:{ss:02d}', '#ffb347')
                    self._lbl(self.next_break_label, '')
                elif breaks_on:
                    last = getattr(self.bot, 'last_break_time', None) or time.time()
                    nxt_interval = getattr(self.bot, 'next_break_interval', 0) or 0
                    secs_until = max(0, int(last + nxt_interval - time.time()))
                    mm2, ss2 = divmod(secs_until, 60)
                    hh2, mm2 = divmod(mm2, 60)
                    if hh2 > 0:
                        self._lbl(self.next_break_label, f'break in {hh2}h{mm2:02d}m', MUTED)
                    else:
                        self._lbl(self.next_break_label, f'break in {mm2}:{ss2:02d}', MUTED)
                    self._lbl(self.break_countdown_label, '')
                else:
                    self._lbl(self.break_countdown_label, '')
                    self._lbl(self.next_break_label, '')
            except Exception:
                pass
            # ── Mini 4-bot status panel update ──────────────────────────────
            try:
                bots      = list(getattr(self, 'bots', []) or [])
                en_vars   = getattr(self, '_client_enable_vars', [None] * 5)
                mini_rows = getattr(self, '_mini_status_rows', [])
                for idx, row in enumerate(mini_rows):
                    sub = bots[idx] if idx < len(bots) else None
                    en_var = en_vars[idx] if idx < len(en_vars) else None
                    enabled = True if idx == 0 else (
                        bool(en_var.get()) if en_var is not None else False)
                    if not enabled:
                        self._lbl(row['wk'],    '—',       BORDER)
                        self._lbl(row['state'], 'off',     BORDER)
                        if 'miss' in row: self._lbl(row['miss'], '—', BORDER)
                        continue
                    if sub is None or not getattr(sub, 'running', False):
                        self._lbl(row['wk'],    '—',       MUTED)
                        reason = getattr(sub, 'stop_reason', None) if sub else None
                        self._lbl(row['state'], reason[:8] if reason else 'stopped', RED if sub and not sub.running else MUTED)
                        if 'miss' in row: self._lbl(row['miss'], '—', MUTED)
                        continue
                    if getattr(sub, 'paused', False):
                        self._lbl(row['wk'],    '—',       AMBER)
                        self._lbl(row['state'], 'paused',  AMBER)
                        if 'miss' in row: self._lbl(row['miss'], '—', AMBER)
                        continue
                    # Running ─────────────────────────────────────────────
                    # Clicks-until-next-bank (replaces old walkto countdown).
                    # Shows _bank_at_clicks - clicks_since_last_bank.
                    cur_mc = int(getattr(sub, '_mine_count', 0))
                    bank_anchor = int(getattr(sub, '_mine_count_at_bank_done', 0))
                    bank_at = int(getattr(sub, '_bank_at_clicks', 0))
                    if bank_at > 0 and sub.config.get('banking_enabled', False):
                        remaining = max(0, bank_at - (cur_mc - bank_anchor))
                        clk_color = '#00ff00' if remaining >= 25 else '#ffaa00' if remaining >= 10 else '#ff1111'
                        self._lbl(row['wk'], str(remaining), clk_color)
                    else:
                        self._lbl(row['wk'], '—', MUTED)
                    # Task / state text
                    act = str(getattr(sub, 'last_action', 'mining') or 'mining')
                    self._lbl(row['state'], act[:9], GREEN)
                    # Banker misclicks counter
                    if 'miss' in row:
                        bm = int(getattr(sub, 'banker_miss_count', 0))
                        self._lbl(row['miss'], str(bm) if bm else '—',
                                  '#ff6666' if bm > 0 else MUTED)
                # Total ores estimate — sum _mine_count across every bot that
                # has been started this session (running or stopped).
                try:
                    total_ores = sum(int(getattr(b, '_mine_count', 0))
                                     for b in bots if b is not None)
                    if hasattr(self, 'live_total_ores_label'):
                        self.live_total_ores_label.config(text=str(total_ores))
                    # Banked ore estimate: sum of completed bank runs across
                    # all bots × 28 (avg ores per inventory).
                    invs = sum(int(getattr(b, '_banks_completed', 0))
                               for b in bots if b is not None)
                    if hasattr(self, 'live_banked_ore_label'):
                        self.live_banked_ore_label.config(text=str(invs * 28))
                    if hasattr(self, 'live_invs_banked_label'):
                        self.live_invs_banked_label.config(text=str(invs))
                except Exception:
                    pass
            except Exception:
                pass
        else:
            # Bot not running — still update mouse coords live
            try:
                coord_str = f'{_mx}, {_my}' if _mx is not None else '----, ----'
                self._lbl(self.live_mouse_box_label, coord_str)
            except Exception:
                pass
        self.root.after(250, self._schedule_live_update)  # 250ms — always reschedule

    # ── Fixed Spot Selector ──────────────────────────────────────────────────

    def _spot_btn_text(self):
        n = len(self._fixed_spots)
        return f'📍 Select ore spots ({n}/3)' if n < 3 else '📍 Spots set (3/3)'

    def _clear_fixed_spots(self):
        self._fixed_spots = []
        self.spot_btn_label.set(self._spot_btn_text())
        self.config['fixed_ore_spots'] = []

    def _open_spot_selector(self):
        """Overlay a click-capture window over the game window to pick ore spots."""
        hwnd = None
        title = self.config.get('window_title', '')
        try:
            hwnd = win32gui.FindWindow(None, title)
        except Exception:
            pass
        if not hwnd:
            messagebox.showwarning('Fixed Spots', 'Game window not found — launch the game first.')
            return

        try:
            rect = win32gui.GetClientRect(hwnd)
            pt = win32gui.ClientToScreen(hwnd, (0, 0))
            gx, gy, gw, gh = pt[0], pt[1], rect[2], rect[3]
        except Exception:
            messagebox.showerror('Fixed Spots', 'Could not read game window position.')
            return

        sel = tk.Toplevel(self.root)
        sel.title('Click up to 3 ore spots — then close')
        sel.geometry(f'{gw}x{gh}+{gx}+{gy}')
        sel.attributes('-topmost', True)
        sel.attributes('-alpha', 0.35)
        sel.configure(bg='black')
        sel.overrideredirect(True)

        canvas = tk.Canvas(sel, bg='black', highlightthickness=0, cursor='crosshair')
        canvas.pack(fill='both', expand=True)

        # Instruction banner
        canvas.create_text(gw // 2, 22, text='Click up to 3 ore spots  |  Right-click to undo  |  Press Enter/Escape to confirm',
                           fill='white', font=('Consolas', 11, 'bold'))

        spots = list(self._fixed_spots)  # copy existing spots in
        markers = []

        def _redraw():
            for m in markers:
                canvas.delete(m)
            markers.clear()
            colors = ['#ff4444', '#ffaa00', '#44ddff']
            for i, (rx, ry) in enumerate(spots):
                sx, sy = int(rx * gw), int(ry * gh)
                r = 18
                m1 = canvas.create_oval(sx-r, sy-r, sx+r, sy+r,
                                        outline=colors[i], width=3, fill='')
                m2 = canvas.create_text(sx, sy, text=str(i+1),
                                        fill=colors[i], font=('Consolas', 13, 'bold'))
                markers.extend([m1, m2])

        _redraw()

        def _on_click(e):
            if len(spots) >= 3:
                return
            spots.append((e.x / gw, e.y / gh))
            _redraw()
            if len(spots) == 3:
                canvas.create_text(gw // 2, 48,
                                   text='3 spots selected — close or press Enter',
                                   fill='#44ddff', font=('Consolas', 10))

        def _on_right(e):
            if spots:
                spots.pop()
                _redraw()

        def _confirm(e=None):
            self._fixed_spots = list(spots)
            self.config['fixed_ore_spots'] = self._fixed_spots
            self.spot_btn_label.set(self._spot_btn_text())
            sel.destroy()

        canvas.bind('<Button-1>', _on_click)
        canvas.bind('<Button-3>', _on_right)
        sel.bind('<Return>', _confirm)
        sel.bind('<Escape>', _confirm)
        canvas.bind('<Double-Button-1>', _confirm)

    # ────────────────────────────────────────────────────────────────────────────

    def _run_bot(self):
        try:
            self.bot.run()
        except Exception as e:
            try:
                import traceback as _traceback
                self.log_debug(f'[Bot1] crashed: {e}')
                self.log_debug(_traceback.format_exc().rstrip())
            except Exception:
                pass
            self.root.after(0, lambda: messagebox.showerror('Bot Error', str(e)))
            self.root.after(0, self.stop_bot)

    def _run_extra_bot(self, sub_bot):
        bot_name = f'Bot{sub_bot.client_id + 1}'
        try:
            if getattr(sub_bot, '_background_only', False):
                sub_bot.start_background_only()
            else:
                sub_bot.run()
        except Exception as e:
            try:
                import traceback as _traceback
                self.log_debug(f'[{bot_name}] crashed: {e}')
                self.log_debug(_traceback.format_exc().rstrip())
            except Exception:
                pass
            self.log_debug(f'[{bot_name}] stopped: {e}')

    def _tag_window_by_title(self, title, role_tag):
        """Append " — <role_tag>" to the matching game window's title bar.
        Stores original title in self._window_title_originals[hwnd] so we
        can restore on stop."""
        try:
            target = title
            hwnd_found = None
            def _enum(hwnd, _):
                nonlocal hwnd_found
                txt = win32gui.GetWindowText(hwnd)
                if txt == target:
                    hwnd_found = hwnd
                elif hwnd_found is None and target.lower() in (txt or '').lower():
                    hwnd_found = hwnd
                return True
            win32gui.EnumWindows(_enum, None)
            if hwnd_found is None:
                self.log_debug(f'Tag: window "{title}" not found')
                return
            original = win32gui.GetWindowText(hwnd_found)
            if ' — ' in original:
                # Already tagged; don't double-stack.
                return
            self._window_title_originals[hwnd_found] = original
            new_title = f'{original} — {role_tag}'
            win32gui.SetWindowText(hwnd_found, new_title)
            self.log_debug(f'Tagged hwnd {hwnd_found}: {role_tag}')
        except Exception as e:
            self.log_debug(f'Tag error: {e}')

    def _restore_window_titles(self):
        for hwnd, original in list(getattr(self, '_window_title_originals', {}).items()):
            try:
                if win32gui.IsWindow(hwnd):
                    win32gui.SetWindowText(hwnd, original)
            except Exception:
                pass
        self._window_title_originals = {}

    _RUNTIME_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runtime_save.json')

    def _load_saved_runtime(self):
        try:
            with open(self._RUNTIME_FILE, 'r') as f:
                return float(json.load(f).get('saved_secs', 0))
        except Exception:
            return 0.0

    def _save_runtime(self):
        try:
            elapsed = (time.time() - self._start_time) if self._start_time else 0.0
            total = self._runtime_saved_secs + elapsed
            with open(self._RUNTIME_FILE, 'w') as f:
                json.dump({'saved_secs': total}, f)
            self._runtime_saved_secs = total
        except Exception:
            pass

    def stop_bot(self):
        if not self.running:
            return
        self._save_runtime()
        self.running = False
        # Clear turn list so any lingering bot threads exit the turn-gate loop.
        MiningBot._ACTIVE_CLIENT_IDS = []
        if self.bot:
            self.bot.stop()
        for sub in getattr(self, 'bots', [])[1:]:
            try: sub.stop()
            except Exception: pass
        # Restore any window titles we tagged during start.
        try: self._restore_window_titles()
        except Exception: pass
        self._stop_overlay()
        self._start_time = None
        self.live_runtime_label.config(text='⏱ 00:00')
        self.btn_start.config(state='normal')
        self.btn_stop.config(state='disabled')
        self.btn_pause.config(state='disabled', text='⏸ PAUSE')
        reason = getattr(self.bot, 'stop_reason', '') if self.bot else ''
        label = f'● STOPPED — {reason}' if reason else '● STOPPED'
        self.status_dot.config(text=label, fg=RED)
        self.log_debug(f'Bot stopped. {reason}')

    def pause_bots(self):
        """Freeze all running bots in place without stopping them.
        Each bot retains its current state; pressing START resumes."""
        if not self.running:
            return
        paused_any = False
        for b in getattr(self, 'bots', []):
            try:
                if getattr(b, 'running', False) and not getattr(b, 'paused', False):
                    b.paused = True
                    paused_any = True
            except Exception:
                pass
        if paused_any:
            self._pause_started_at = time.time()
            self.btn_pause.config(text='▶ RESUME', command=self.resume_bots)
            self.status_dot.config(text='⏸ PAUSED', fg=AMBER)
            self.log_debug('All bots paused — press RESUME to continue.')

    def resume_bots(self):
        """Un-pause all bots, restoring their last state."""
        if getattr(self, '_pause_started_at', None):
            self._total_paused_secs = getattr(self, '_total_paused_secs', 0.0) + (time.time() - self._pause_started_at)
            self._pause_started_at = None
        for b in getattr(self, 'bots', []):
            try:
                b.paused = False
            except Exception:
                pass
        self.btn_pause.config(text='⏸ PAUSE', command=self.pause_bots)
        self.status_dot.config(text='● RUNNING', fg=GREEN)
        self.log_debug('All bots resumed.')

    def _open_mini_hud(self):
        """Sci-fi JARVIS-style HUD — resizable, transparent, animated."""
        if getattr(self, '_mini_hud', None):
            try:
                if self._mini_hud.winfo_exists():
                    self._mini_hud.lift()
                    return
            except Exception:
                pass

        import tkinter.scrolledtext as _st
        import math

        # ── Sci-fi palette ───────────────────────────────────────────────────
        H_BG    = '#0A0F1C'   # deep navy
        H_SURF  = '#0D1526'   # slightly lighter surface
        H_GRID  = '#0F1830'   # grid line colour
        C_ORG   = '#FF8C00'   # neon orange (master / primary)
        C_CYN   = '#00E5FF'   # cyan (headers / accents)
        C_GRN   = '#00FF88'   # green (running)
        C_RED   = '#FF2244'   # red (stopped / error)
        C_AMB   = '#FFA500'   # amber (paused / warning)
        C_TXT   = '#E0E6F0'   # main text
        C_DIM   = '#3A4A60'   # dimmed text
        C_SEP   = '#1A2840'   # separator lines

        hud = tk.Toplevel(self.root)
        hud.title('Bot V2.5 — HUD')
        hud.configure(bg=H_BG)
        hud.resizable(True, True)
        hud.minsize(270, 310)
        self._mini_hud      = hud
        self._mini_hud_debug = None

        _alpha   = [1.0]
        _arc_ang = [0]
        _pulse   = [0]
        hud.attributes('-alpha', _alpha[0])

        # ════════════════════════════════════════════════════════════════════
        # HEADER CANVAS — animated arc ring + title + status badge
        # ════════════════════════════════════════════════════════════════════
        HDR_H = 72
        hdr = tk.Canvas(hud, bg=H_BG, height=HDR_H, highlightthickness=0, bd=0)
        hdr.pack(fill='x')

        def _draw_hdr(W=None):
            if not hud.winfo_exists(): return
            hdr.delete('all')
            W = hdr.winfo_width() or 270
            H = HDR_H

            # subtle dot-grid background
            for gx in range(0, W, 18):
                for gy in range(0, H, 18):
                    hdr.create_oval(gx-1, gy-1, gx+1, gy+1, fill=H_GRID, outline='')

            # corner brackets (cyan)
            bl = 14
            for px, py, sx, sy in [(4,4,1,1),(W-4,4,-1,1),(4,H-4,1,-1),(W-4,H-4,-1,-1)]:
                hdr.create_line(px, py, px+sx*bl, py, fill=C_CYN, width=1)
                hdr.create_line(px, py, px, py+sy*bl, fill=C_CYN, width=1)

            # arc ring (left side, vertically centred)
            cx, cy, R = 44, H // 2, 24
            # outer dim ring
            hdr.create_oval(cx-R, cy-R, cx+R, cy+R, outline=C_SEP, width=2)
            # rotating orange arc
            a = _arc_ang[0]
            hdr.create_arc(cx-R, cy-R, cx+R, cy+R,
                           start=a, extent=210, style='arc', outline=C_ORG, width=2)
            # inner cyan arc (counter)
            ri = R - 7
            hdr.create_oval(cx-ri, cy-ri, cx+ri, cy+ri, outline=C_SEP, width=1)
            hdr.create_arc(cx-ri, cy-ri, cx+ri, cy+ri,
                           start=-a*1.5, extent=130, style='arc', outline=C_CYN, width=1)
            # pulsing centre dot
            pulse_r = 3 + int(1.5 * abs(math.sin(math.radians(_pulse[0]))))
            hdr.create_oval(cx-pulse_r, cy-pulse_r, cx+pulse_r, cy+pulse_r,
                            fill=C_ORG, outline='')

            # title text block
            tx = cx + R + 10
            hdr.create_text(tx, cy - 10, text='RSC MULTIMINER', anchor='w',
                            fill=C_ORG, font=('Consolas', 10, 'bold'))
            hdr.create_text(tx, cy + 6, text='CONTROL INTERFACE v2', anchor='w',
                            fill=C_DIM, font=('Consolas', 6))

            # status badge (right)
            is_run   = self.running
            any_paus = is_run and any(getattr(b, 'paused', False)
                                      for b in getattr(self, 'bots', []))
            if any_paus:
                badge_col, badge_txt = C_AMB, 'PAUSED'
            elif is_run:
                badge_col, badge_txt = C_GRN, 'ONLINE'
            else:
                badge_col, badge_txt = C_DIM, ' IDLE '
            bw = 52
            hdr.create_rectangle(W-bw-6, cy-10, W-6, cy+10,
                                  outline=badge_col, fill='', width=1)
            hdr.create_text(W-bw//2-6, cy, text=badge_txt,
                            fill=badge_col, font=('Consolas', 7, 'bold'))

            # bottom glow line
            hdr.create_line(0, H-2, W, H-2, fill=C_SEP, width=2)
            hdr.create_line(W//5, H-1, 4*W//5, H-1, fill=C_CYN, width=1)

        def _animate():
            if not hud.winfo_exists(): return
            _arc_ang[0] = (_arc_ang[0] + 3) % 360
            _pulse[0]   = (_pulse[0]   + 5) % 360
            _draw_hdr()
            hud.after(50, _animate)

        hdr.bind('<Configure>', lambda e: _draw_hdr())
        hud.after(80, _animate)

        # ════════════════════════════════════════════════════════════════════
        # RUNTIME BAR — large clock directly below header
        # ════════════════════════════════════════════════════════════════════
        rt_bar = tk.Frame(hud, bg='#070D1A')
        rt_bar.pack(fill='x')
        tk.Frame(rt_bar, bg=C_SEP, height=1).pack(fill='x')
        rt_inner = tk.Frame(rt_bar, bg='#070D1A', padx=10, pady=3)
        rt_inner.pack(fill='x')
        # Right: large runtime clock
        rt_col = tk.Frame(rt_inner, bg='#070D1A')
        rt_col.pack(side='right')
        tk.Label(rt_col, text='RUNTIME', bg='#070D1A', fg=C_DIM,
                 font=('Consolas', 6, 'bold')).pack(anchor='e')
        hud_rt = tk.Label(rt_col, text='——:——', bg='#070D1A', fg=C_ORG,
                          font=('Consolas', 20, 'bold'))
        hud_rt.pack(anchor='e')
        # Left: Red X clicks counter
        rx_col = tk.Frame(rt_inner, bg='#070D1A')
        rx_col.pack(side='left', anchor='center')
        tk.Label(rx_col, text='RED X', bg='#070D1A', fg=C_DIM,
                 font=('Consolas', 6, 'bold')).pack(anchor='w')
        hud_rx = tk.Label(rx_col, text='0', bg='#070D1A', fg='#FF3333',
                          font=('Consolas', 14, 'bold'))
        hud_rx.pack(anchor='w')

        # ════════════════════════════════════════════════════════════════════
        # BOT STATUS GRID
        # ════════════════════════════════════════════════════════════════════
        gf = tk.Frame(hud, bg=H_BG)
        gf.pack(fill='x', padx=8, pady=(6, 0))

        _HF = ('Consolas', 7, 'bold')
        _VF = ('Consolas', 8)

        # column headers
        hdr_f = tk.Frame(gf, bg=H_BG)
        hdr_f.pack(fill='x')
        tk.Label(hdr_f, text='SYS', bg=H_BG, fg=C_CYN, font=_HF, width=6, anchor='w').pack(side='left')
        tk.Label(hdr_f, text='CLK', bg=H_BG, fg=C_CYN, font=_HF, width=4, anchor='center').pack(side='left')
        tk.Label(hdr_f, text='STATE', bg=H_BG, fg=C_CYN, font=_HF,
                 anchor='w').pack(side='left', padx=(6, 0), expand=True, fill='x')

        tk.Frame(gf, bg=C_CYN, height=1).pack(fill='x', pady=(2, 3))

        def _hud_force_bank(idx):
            bots = getattr(self, 'bots', [])
            if idx < len(bots) and bots[idx] and getattr(bots[idx], 'running', False):
                bots[idx]._banking_request = True
                self.log_debug(f'\U0001f3e6 Force bank → Bot{idx+1}')

        def _hud_force_train(idx):
            bots = getattr(self, 'bots', [])
            if idx < len(bots) and bots[idx] and getattr(bots[idx], 'running', False):
                b = bots[idx]
                try:
                    dest = b._pick_walkto_train_destination()
                    if dest:
                        b._type_ingame_message(f'::walkto {dest}')
                        b._walkto_sent_at = time.time()  # arm 30s dead zone — don't rotate/click this window
                        self.log_debug(f'\U0001f6b6 Force train → Bot{idx+1}: ::walkto {dest}')
                except Exception as _e:
                    self.log_debug(f'Force train error Bot{idx+1}: {_e}')

        _NAMES = ['MASTER', 'BOT-2', 'BOT-3', 'BOT-4', 'BOT-5']
        hud_rows = []
        for i, name in enumerate(_NAMES):
            rf = tk.Frame(gf, bg=H_BG)
            rf.pack(fill='x', pady=1)
            dot = tk.Label(rf, text='◈', bg=H_BG, fg=C_DIM, font=('Consolas', 8))
            dot.pack(side='left', padx=(0, 2))
            nl  = tk.Label(rf, text=name, bg=H_BG, fg=C_ORG if i == 0 else C_DIM,
                           font=_HF, width=6, anchor='w')
            nl.pack(side='left')
            cl  = tk.Label(rf, text='—', bg=H_BG, fg=C_DIM, font=_VF, width=4, anchor='center')
            cl.pack(side='left')
            # Bank + Train buttons packed right BEFORE the expanding state label
            train_btn = tk.Button(rf, text='💪', bg='#0a0a1e', fg='#4477bb',
                                  font=('Segoe UI Emoji', 9), width=2, pady=0, padx=1,
                                  relief='flat', cursor='hand2',
                                  command=lambda _i=i: _hud_force_train(_i))
            train_btn.pack(side='right', padx=(1, 0))
            bank_btn = tk.Button(rf, text='🏦', bg='#0a1a0a', fg='#33bb55',
                                 font=('Segoe UI Emoji', 9), width=2, pady=0, padx=1,
                                 relief='flat', cursor='hand2',
                                 command=lambda _i=i: _hud_force_bank(_i))
            bank_btn.pack(side='right', padx=(2, 1))
            sl  = tk.Label(rf, text='idle', bg=H_BG, fg=C_DIM, font=_VF, anchor='w')
            sl.pack(side='left', padx=(6, 0), expand=True, fill='x')
            hud_rows.append({'dot': dot, 'clk': cl, 'state': sl})

        tk.Frame(gf, bg=C_SEP, height=1).pack(fill='x', pady=(4, 0))

        # ════════════════════════════════════════════════════════════════════
        # STATS BOX — Red X Clicks / Banked Ore / Inv's Banked
        # ════════════════════════════════════════════════════════════════════
        sf = tk.Frame(hud, bg=H_BG)
        sf.pack(fill='x', padx=8, pady=(5, 0))
        _stat_defs = [
            ('$ BANKED ORE',  'banked', '#00FF55', 14),
            ('🎒 INV BANKED', 'invs',   '#FFFFFF', 13),
        ]
        hud_stats = {}
        for _stag, _skey, _scol, _sfont in _stat_defs:
            _cf = tk.Frame(sf, bg=H_BG)
            _cf.pack(side='left', expand=True, fill='x')
            tk.Label(_cf, text=_stag, bg=H_BG, fg=C_DIM,
                     font=('Consolas', 6, 'bold')).pack(anchor='w')
            _sv = tk.Label(_cf, text='0', bg=H_BG, fg=_scol,
                           font=('Consolas', _sfont, 'bold'))
            _sv.pack(anchor='w')
            hud_stats[_skey] = _sv

        # ════════════════════════════════════════════════════════════════════
        # CONTROL BAR — row 1: 4 main buttons (auto-width); row 2: DBG + α
        # ════════════════════════════════════════════════════════════════════
        tk.Frame(hud, bg=C_ORG, height=1).pack(fill='x', pady=(4, 0))
        ctrl = tk.Canvas(hud, bg=H_SURF, height=44, highlightthickness=0, bd=0)
        ctrl.pack(fill='x')
        util = tk.Canvas(hud, bg=H_BG, height=24, highlightthickness=0, bd=0)
        util.pack(fill='x')

        _hit      = {}      # tag -> (x0,y0,x1,y1) in owning canvas coords
        _dbg_open = [False]

        _BTNS_DEF = [
            ('▶  PLAY',  'play',  C_GRN),
            ('■  STOP',  'stop',  C_RED),
            ('⏸ PAUSE', 'pause', C_AMB),
            ('💾 SAVE',  'save',  C_CYN),
        ]

        def _draw_ctrl(W=None):
            if not hud.winfo_exists(): return
            ctrl.delete('all')
            W = ctrl.winfo_width() or 280
            H = 44
            for gx in range(0, W, 20):
                ctrl.create_line(gx, 0, gx, H, fill='#0C1220', width=1)
            n   = len(_BTNS_DEF)
            pad = 4
            bw  = max(50, (W - pad * (n + 1)) // n)
            bh  = 30
            by0, by1 = (H - bh) // 2, (H + bh) // 2
            x = pad
            for txt, tag, col in _BTNS_DEF:
                x0, x1 = x, x + bw
                ctrl.create_rectangle(x0, by0, x1, by1, outline=col,
                                      fill='#080E1A', width=1, tags=tag)
                ctrl.create_text((x0+x1)//2, H//2, text=txt,
                                 fill=col, font=('Consolas', 7, 'bold'), tags=tag)
                _hit[tag] = (x0, by0, x1, by1)
                x = x1 + pad

        def _draw_util(W=None):
            if not hud.winfo_exists(): return
            util.delete('all')
            W = util.winfo_width() or 280
            H = 24
            bh = 16
            by0, by1 = (H - bh) // 2, (H + bh) // 2
            dbg_w, alp_w = 50, 46
            alp_x0 = W - alp_w - 6
            dbg_x0 = alp_x0 - dbg_w - 4
            dbg_lbl = 'DBG ▲' if _dbg_open[0] else 'DBG ▼'
            util.create_rectangle(dbg_x0, by0, dbg_x0+dbg_w, by1,
                                   outline=C_CYN, fill='#080E1A', width=1, tags='dbg')
            util.create_text(dbg_x0+dbg_w//2, H//2, text=dbg_lbl,
                             fill=C_CYN, font=('Consolas', 7, 'bold'), tags='dbg')
            _hit['dbg'] = (dbg_x0, by0, dbg_x0+dbg_w, by1)
            alp_txt = f'α {int(_alpha[0]*100)}%'
            util.create_rectangle(alp_x0, by0, alp_x0+alp_w, by1,
                                   outline=C_DIM, fill='#080E1A', width=1, tags='alp')
            util.create_text(alp_x0+alp_w//2, H//2, text=alp_txt,
                             fill=C_TXT, font=('Consolas', 6), tags='alp')
            _hit['alp'] = (alp_x0, by0, alp_x0+alp_w, by1)

        def _ctrl_click(ev):
            for tag, (x0, y0, x1, y1) in _hit.items():
                if tag in ('dbg', 'alp'): continue
                if x0 <= ev.x <= x1 and y0 <= ev.y <= y1:
                    if   tag == 'play':  self.start_bot()
                    elif tag == 'stop':  self.stop_bot()
                    elif tag == 'pause': self.pause_bots()
                    elif tag == 'save':  self.save_config()
                    break

        def _util_click(ev):
            for tag in ('dbg', 'alp'):
                if tag not in _hit: continue
                x0, y0, x1, y1 = _hit[tag]
                if x0 <= ev.x <= x1 and y0 <= ev.y <= y1:
                    if tag == 'dbg': _toggle_dbg()
                    elif tag == 'alp': _cycle_alpha()
                    break

        def _ctrl_hover(ev):
            for tag, (x0, y0, x1, y1) in _hit.items():
                if tag in ('dbg', 'alp'): continue
                if x0 <= ev.x <= x1 and y0 <= ev.y <= y1:
                    ctrl.config(cursor='hand2'); return
            ctrl.config(cursor='')

        def _util_hover(ev):
            for tag in ('dbg', 'alp'):
                if tag not in _hit: continue
                x0, y0, x1, y1 = _hit[tag]
                if x0 <= ev.x <= x1 and y0 <= ev.y <= y1:
                    util.config(cursor='hand2'); return
            util.config(cursor='')

        ctrl.bind('<Button-1>', _ctrl_click)
        ctrl.bind('<Motion>',   _ctrl_hover)
        ctrl.bind('<Configure>', lambda e: _draw_ctrl())
        util.bind('<Button-1>', _util_click)
        util.bind('<Motion>',   _util_hover)
        util.bind('<Configure>', lambda e: _draw_util())
        hud.after(120, lambda: (_draw_ctrl(), _draw_util()))

        def _cycle_alpha():
            steps = [1.0, 0.93, 0.80, 0.65, 0.50, 0.35]
            cur   = _alpha[0]
            nxt   = min(range(len(steps)), key=lambda i: abs(steps[i]-cur))
            _alpha[0] = steps[(nxt + 1) % len(steps)]
            hud.attributes('-alpha', _alpha[0])
            _draw_util()

        # ════════════════════════════════════════════════════════════════════
        # DEBUG PANEL (collapsible, dark scrollbar)
        # ════════════════════════════════════════════════════════════════════
        dbg_outer = tk.Frame(hud, bg='#060A14')
        dbg_text  = tk.Text(
            dbg_outer, height=8, bg='#060A14', fg='#00DD77',
            font=('Consolas', 6), relief='flat', state='disabled',
            wrap='word', insertbackground='#00DD77', spacing1=1, spacing3=1)
        dbg_text.pack(fill='both', expand=True, padx=2, pady=2)
        self._mini_hud_debug = dbg_text

        def _toggle_dbg():
            _dbg_open[0] = not _dbg_open[0]
            if _dbg_open[0]:
                dbg_outer.pack(fill='both', expand=True, padx=0, pady=(0, 2))
                # Scroll to latest after geometry settles
                hud.after(40, lambda: dbg_text.see('end'))
            else:
                dbg_outer.pack_forget()
            _draw_util()   # refresh DBG button label

        # ════════════════════════════════════════════════════════════════════
        # LIVE DATA TICK
        # ════════════════════════════════════════════════════════════════════
        def _tick():
            if not hud.winfo_exists(): return
            bots    = list(getattr(self, 'bots', []) or [])
            en_vars = getattr(self, '_client_enable_vars', [None]*5)
            for idx, row in enumerate(hud_rows):
                sub    = bots[idx] if idx < len(bots) else None
                en_var = en_vars[idx] if idx < len(en_vars) else None
                enabled = True if idx == 0 else (bool(en_var.get()) if en_var else False)
                if not enabled:
                    row['dot'].config(fg='#1A2030')
                    row['clk'].config(text='—', fg=C_DIM)
                    row['state'].config(text='off', fg=C_DIM)
                    continue
                if sub is None or not getattr(sub, 'running', False):
                    row['dot'].config(fg='#301020')
                    row['clk'].config(text='—', fg=C_DIM)
                    rsn = (getattr(sub, 'stop_reason', None) or '') if sub else ''
                    row['state'].config(text=rsn[:10] if rsn else 'stopped', fg=C_RED)
                    continue
                if getattr(sub, 'paused', False):
                    row['dot'].config(fg=C_AMB)
                    row['clk'].config(text='—', fg=C_AMB)
                    row['state'].config(text='paused', fg=C_AMB)
                    continue
                row['dot'].config(fg=C_GRN)
                cur_mc      = int(getattr(sub, '_mine_count', 0))
                bank_anchor = int(getattr(sub, '_mine_count_at_bank_done', 0))
                bank_at     = int(getattr(sub, '_bank_at_clicks', 0))
                if bank_at > 0 and sub.config.get('banking_enabled', False):
                    rem = max(0, bank_at - (cur_mc - bank_anchor))
                    clr = C_GRN if rem >= 25 else C_AMB if rem >= 10 else C_RED
                    row['clk'].config(text=str(rem), fg=clr)
                else:
                    row['clk'].config(text='—', fg=C_DIM)
                act = str(getattr(sub, 'last_action', 'mining') or 'mining')
                row['state'].config(text=act[:16], fg=C_GRN)
            try:
                _any_paused = any(getattr(b, 'paused', False) for b in getattr(self, 'bots', []))
                if self.running and self._start_time and not _any_paused:
                    _paused_tot = getattr(self, '_total_paused_secs', 0.0)
                    _pause_cur  = (time.time() - self._pause_started_at) if getattr(self, '_pause_started_at', None) else 0.0
                    e = max(0, int(time.time() - self._start_time - _paused_tot - _pause_cur))
                    hud_rt.config(text=(f'{e//3600:02d}:{(e%3600)//60:02d}:{e%60:02d}'
                                        if e >= 3600 else f'{e//60:02d}:{e%60:02d}'))
                elif not self.running:
                    hud_rt.config(text='——:——')
                # else: paused — leave clock frozen at last shown value
            except Exception:
                pass
            try:
                bots_all    = list(getattr(self, 'bots', []) or [])
                rx_total    = sum(int(getattr(b, '_mine_count', 0))      for b in bots_all if b) + getattr(self, '_stat_rx_offset', 0)
                banks_total = sum(int(getattr(b, '_banks_completed', 0)) for b in bots_all if b) + getattr(self, '_stat_banks_offset', 0)
                hud_rx.config(text=str(rx_total))
                hud_stats['banked'].config(text=str(banks_total * 28))
                hud_stats['invs'].config(text=str(banks_total))
            except Exception:
                pass
            hud.after(350, _tick)

        _tick()
        hud.update_idletasks()
        sw = hud.winfo_screenwidth()
        hud.geometry(f'320x480+{sw - 346}+28')

    def show_stop_reason(self, reason):
        try:
            self.status_dot.config(text=f'● STOPPED — {reason}', fg=RED)
        except Exception:
            pass

    # ── Tkinter-based YOLO overlay ───────────────────────────────────────────

    # BGR ore colors from detector → RGB for PIL
    _ORE_COLORS_RGB = {
        'adamantite': (255, 0, 0),
        'mithril':    (128, 0, 128),
        'coal':       (100, 100, 100),
        'iron':       (200, 200, 200),
        'tin':        (0, 255, 255),
        'copper':     (255, 165, 0),
        'empty':      (255, 255, 0),
    }
    CHROMA_KEY = (255, 0, 255)   # magenta — will be invisible in-game

    def _on_overlay_mode_change(self):
        """Rebuild overlay window when overlay mode radio changes."""
        if self.overlay_mode_var.get() == 'none':
            # Tear down immediately — no new window needed.
            self._stop_overlay()
            return
        if getattr(self, 'running', False):
            self._start_overlay()

    def _start_overlay(self):
        """Create the overlay Toplevel and start polling frames from the bot."""
        # Destroy any existing overlay before creating a new one
        self._stop_overlay()
        # Sweep: destroy ANY leftover toplevels titled 'Bot V2.5 Overlay'
        try:
            for child in list(self.root.winfo_children()):
                if isinstance(child, tk.Toplevel) and child.title() in ('Bot V2.5 Overlay', 'Mining Bot Overlay'):
                    try: child.destroy()
                    except Exception: pass
        except Exception:
            pass
        self._overlay_win = None
        self._overlay_label = None
        self._overlay_canvas = None
        self._overlay_canvas_item = None
        self._overlay_photo = None
        self._last_overlay_geom = None
        self._det_seen_at = {}
        # Bump generation so any in-flight poll callbacks from prior overlays exit
        self._overlay_gen = getattr(self, '_overlay_gen', 0) + 1

        mode = self.overlay_mode_var.get()
        if mode == 'none':
            return  # No overlay window in None mode.
        chroma_hex = '#FF00FF'

        top = tk.Toplevel(self.root)
        top.title('Bot V2.5 Overlay')
        top.protocol('WM_DELETE_WINDOW', lambda: None)

        if mode == 'ingame':
            top.configure(bg=chroma_hex)
            top.overrideredirect(True)
            top.attributes('-topmost', True)
            self._overlay_canvas = tk.Canvas(top, bg=chroma_hex, highlightthickness=0)
            self._overlay_canvas.pack(fill='both', expand=True)
            self._overlay_canvas_item = None
            self._overlay_label = None
            top.update_idletasks()
            # Set WS_EX_LAYERED | TRANSPARENT | TOPMOST, then chroma-key
            try:
                # Tk wraps the toplevel in a frame — get the real HWND
                wm_frame = top.wm_frame()
                overlay_hwnd = int(wm_frame, 16) if wm_frame else 0
                if not overlay_hwnd:
                    overlay_hwnd = ctypes.windll.user32.GetParent(
                        top.winfo_id())
                if overlay_hwnd:
                    ex = win32gui.GetWindowLong(overlay_hwnd, win32con.GWL_EXSTYLE)
                    ex |= (win32con.WS_EX_LAYERED |
                           win32con.WS_EX_TRANSPARENT |
                           win32con.WS_EX_TOPMOST)
                    win32gui.SetWindowLong(overlay_hwnd, win32con.GWL_EXSTYLE, ex)
                    # LWA_COLORKEY = 0x01 — makes COLORREF magenta fully transparent
                    ctypes.windll.user32.SetLayeredWindowAttributes(
                        overlay_hwnd, 0x00FF00FF, 0, 0x01)
            except Exception:
                pass
        else:
            # Pop-Out: standalone window, NOT topmost, positioned beside the game
            top.configure(bg='black')
            top.overrideredirect(False)
            top.attributes('-topmost', False)
            # Position to the right of the game window (if found), else top-left
            try:
                if self.bot and self.bot.hwnd:
                    rect = win32gui.GetClientRect(self.bot.hwnd)
                    pt = win32gui.ClientToScreen(self.bot.hwnd, (0, 0))
                    gx, gy, gw, gh = pt[0], pt[1], rect[2], rect[3]
                    px = gx + gw + 12
                    py = gy
                    top.geometry(f'512x340+{px}+{py}')
                else:
                    top.geometry('512x340+40+40')
            except Exception:
                top.geometry('512x340+40+40')
            self._overlay_label = tk.Label(top, bg='black')
            self._overlay_label.pack(fill='both', expand=True)

        self._overlay_win = top
        self._overlay_win_gen = self._overlay_gen
        # Pop-out Toplevel steals focus from the game window; give it back
        if mode != 'ingame':
            def _refocus_game():
                if self.bot and self.bot.hwnd:
                    try:
                        self.bot.bring_window_to_front()
                    except Exception:
                        pass
            self.root.after(800, _refocus_game)
        self._poll_overlay_frame(gen=self._overlay_gen)

    def _draw_boxes_only(self, detections, width, height):
        """Render detection boxes + stats ROI box on a chroma-key background."""
        from PIL import ImageDraw, ImageFont
        img = Image.new('RGB', (width, height), self.CHROMA_KEY)
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype('consola.ttf', 13)
        except Exception:
            font = ImageFont.load_default()

        # Info Panel — Hits/Prayer/Fatigue/FPS (top-left)
        draw.rectangle([0, 0, int(width * 0.22), int(height * 0.28)],
                       outline=(0, 255, 255), width=2)
        draw.text((3, 3), 'Info Panel', fill=(0, 255, 255), font=font)

        # Chat/OCR ROI — incoming game text (bottom-left)
        chat_y1 = int(height * 0.72)
        chat_y2 = int(height * 0.92)
        chat_x2 = int(width * 0.95)
        draw.rectangle([0, chat_y1, chat_x2, chat_y2],
                       outline=(255, 200, 0), width=2)
        draw.text((3, chat_y1 + 3), 'ROI', fill=(255, 200, 0), font=font)

        box_w = max(1, self.config.get('overlay_box_thickness', 2))
        _ORE_SHORT = {
            'adamantite_rock': 'Addy', 'mithril_rock': 'Mith',
            'coal_rock': 'Coal', 'iron_rock': 'Iron',
            'tin_rock': 'Tin', 'copper_rock': 'Copper', 'empty_ore_rock': 'Empty',
        }
        show_empty = self.show_empty_var.get() if hasattr(self, 'show_empty_var') else self.config.get('show_empty_ore', False)
        for det in detections:
            name = det['class_name']
            if name == 'empty_ore_rock' and not show_empty:
                continue
            x1, y1, x2, y2 = [int(v) for v in det['box']]
            conf = det['confidence']
            color = (0, 255, 0)
            for key, c in self._ORE_COLORS_RGB.items():
                if key in name:
                    color = c
                    break
            draw.rectangle([x1, y1, x2, y2], outline=color, width=box_w)
            short = _ORE_SHORT.get(name, name.replace('_rock', '').replace('_', ' ').title())
            label = f"{short} {conf:.0%}"
            draw.text((x1, max(y1 - 14, 0)), label, fill=color, font=font)
        return img

    def _poll_overlay_frame(self, gen=None):
        """Redraw overlay whenever the bot publishes a new detection frame
        (1.8s cadence) or flags an immediate refresh. Ghost polls from a
        prior overlay generation exit immediately."""
        if gen is not None and gen != getattr(self, '_overlay_gen', 0):
            return
        if not self.running or self._overlay_win is None:
            return
        mode = self.overlay_mode_var.get()
        if mode == 'none':
            return
        refresh = False
        try:
            refresh = bool(getattr(self.bot, '_overlay_refresh_flag', False))
            if refresh:
                self.bot._overlay_refresh_flag = False
        except Exception:
            pass
        try:
            frame, region, detections, buf_ts = self.bot._overlay_buf.get()
        except Exception:
            frame, region, detections, buf_ts = None, None, [], 0.0
        last_ts = getattr(self, '_overlay_last_ts', 0.0)
        new_frame = buf_ts > last_ts
        if not (refresh or new_frame or not getattr(self, '_overlay_first_drawn', False)):
            self.root.after(200, lambda: self._poll_overlay_frame(gen=gen))
            return
        self._overlay_last_ts = buf_ts
        self._overlay_first_drawn = True
        try:
            if mode == 'ingame':
                if region is not None:
                    x, y, w, h = region
                    new_geom = (x, y, w, h)
                    # Debounce geometry repositioning: only move the overlay window
                    # after the same region appears twice consecutively (~400ms).
                    # This prevents the window from flickering in MC mode as the
                    # MC loop writes frames from different game windows rapidly.
                    _prev_pending = getattr(self, '_overlay_pending_region', None)
                    if new_geom != getattr(self, '_last_overlay_geom', None):
                        if _prev_pending == new_geom:
                            # Region stable for 2 polls — commit the move.
                            self._overlay_win.geometry(f'{w}x{h}+{x}+{y}')
                            self._last_overlay_geom = new_geom
                            self._overlay_pending_region = None
                        else:
                            # First time seeing this region — wait one more poll.
                            self._overlay_pending_region = new_geom
                            self.root.after(200, lambda: self._poll_overlay_frame(gen=gen))
                            return

                    img = self._draw_boxes_only(detections or [], w, h)
                    photo = ImageTk.PhotoImage(img)
                    if self._overlay_canvas_item is None:
                        self._overlay_canvas_item = self._overlay_canvas.create_image(
                            0, 0, anchor='nw', image=photo)
                    else:
                        self._overlay_canvas.itemconfigure(
                            self._overlay_canvas_item, image=photo)
                    self._overlay_photo = photo
            else:
                if frame is not None:
                    rgb = frame[:, :, ::-1] if frame.shape[2] == 3 else frame
                    img = Image.fromarray(rgb)
                    from PIL import ImageDraw, ImageFont
                    orig_w, orig_h = img.size
                    draw = ImageDraw.Draw(img)
                    sy2 = int(orig_h * 0.28)
                    sx2 = int(orig_w * 0.22)
                    try:
                        fnt = ImageFont.truetype('consola.ttf', 13)
                    except Exception:
                        fnt = ImageFont.load_default()
                    draw.rectangle([0, 0, sx2, sy2], outline=(0, 255, 255), width=2)
                    draw.text((3, 3), 'Info Panel', fill=(0, 255, 255), font=fnt)
                    chat_y1 = int(orig_h * 0.72)
                    chat_y2 = int(orig_h * 0.92)
                    draw.rectangle([0, chat_y1, int(orig_w * 0.95), chat_y2],
                                   outline=(255, 200, 0), width=2)
                    draw.text((3, chat_y1 + 3), 'ROI', fill=(255, 200, 0), font=fnt)
                    win_w = self._overlay_win.winfo_width()
                    win_h = self._overlay_win.winfo_height()
                    if win_w > 10 and win_h > 10:
                        img = img.resize((win_w, win_h), Image.NEAREST)
                    photo = ImageTk.PhotoImage(img)
                    self._overlay_label.configure(image=photo)
                    self._overlay_photo = photo
        except Exception:
            pass
        self.root.after(200, lambda: self._poll_overlay_frame(gen=gen))

    def _stop_overlay(self):
        """Destroy the overlay window."""
        try:
            if self._overlay_win is not None:
                self._overlay_win.destroy()
        except Exception:
            pass
        self._overlay_win = None
        self._overlay_label = None
        self._overlay_canvas = None
        self._overlay_canvas_item = None
        self._overlay_photo = None
        self._det_seen_at = {}

    def toggle_bot(self, event=None):
        if self.running:
            self.stop_bot()
        else:
            self.start_bot()

    def start_hotkey_listener(self):
        self._hotkey_alive = True
        def _thread():
            user32 = ctypes.windll.user32
            was_f6 = False
            self.log_debug('Global hotkey listener started (F6 polling)')
            while self._hotkey_alive:
                try:
                    # F6 — toggle start/stop
                    state6 = user32.GetAsyncKeyState(VK_F6)
                    if state6 & 0x8000:
                        if not was_f6:
                            was_f6 = True
                            try:
                                self.root.after(0, self.toggle_bot)
                            except Exception:
                                pass
                    else:
                        was_f6 = False
                except Exception:
                    pass
                time.sleep(0.05)
        threading.Thread(target=_thread, daemon=True).start()

    def on_closing(self):
        self._hotkey_alive = False
        self.stop_bot()
        self.root.destroy()

if __name__ == '__main__':
    while True:
        _load_active_theme()
        root = tk.Tk()
        app = MiningBotGUI(root)
        root.mainloop()
        if not getattr(app, '_restart', False):
            break
