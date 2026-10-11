import io
import os
import struct
import time
import random
import math
import threading
import wave
import win32gui
import win32con
import win32api
from mss import mss
import numpy as np
from detector import Detector
from mouse import HumanMouse
from banking import BankingFSM
import cv2
import winsound
import ctypes

try:
    import easyocr
    _HAVE_OCR = True
    _ocr_reader = None
except Exception:
    _HAVE_OCR = False

def _make_ocr_reader():
    """Create an EasyOCR reader. If SSL cert verification fails (common on PCs
    with outdated root certificates), retries with verification disabled so the
    model weights can download from GitHub."""
    import ssl
    try:
        print('[OCR] Creating EasyOCR reader...')
        reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        print('[OCR] EasyOCR reader ready')
        return reader
    except Exception as _e:
        if 'SSL' in str(_e) or 'CERTIFICATE' in str(_e) or 'urlopen' in str(_e):
            print(f'[OCR] SSL error, retrying with unverified context: {_e}')
            _orig = ssl._create_default_https_context
            try:
                ssl._create_default_https_context = ssl._create_unverified_context
                reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                print('[OCR] EasyOCR reader ready (SSL bypass)')
                return reader
            finally:
                ssl._create_default_https_context = _orig
        raise

try:
    import pytesseract
    import os as _os
    for _tess_path in [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    ]:
        if _os.path.isfile(_tess_path):
            pytesseract.pytesseract.tesseract_cmd = _tess_path
            break
    pytesseract.get_tesseract_version()   # raises if binary still missing
    _HAVE_PYTESSERACT = True
    print(f'[OCR] Tesseract ready: {pytesseract.pytesseract.tesseract_cmd}')
except Exception:
    _HAVE_PYTESSERACT = False


# Thread-safe frame buffer so the GUI can poll the latest annotated frame.
class _DetectionBuffer:
    """Thread-safe buffer holding the latest YOLO detection results."""
    def __init__(self):
        self._data = ([], None, None)  # (detections, frame, region_tuple)
        self._ts = 0.0                 # timestamp of the latest frame
        self._lock = threading.Lock()

    def update(self, detections, frame, region_tuple):
        with self._lock:
            self._data = (detections, frame, region_tuple)
            self._ts = time.time()

    def get(self):
        with self._lock:
            return self._data, self._ts


class _OverlayBuffer:
    def __init__(self):
        self._frame = None
        self._region = None
        self._detections = []
        self._ts = 0.0
        self._lock = threading.Lock()

    def update_frame(self, frame, region=None, detections=None):
        with self._lock:
            self._frame = frame
            if region is not None:
                self._region = region
            if detections is not None:
                self._detections = detections
            self._ts = time.time()

    def get(self):
        with self._lock:
            return self._frame, self._region, self._detections, self._ts


class MiningBot:
    # Shared across all instances so multi-client setups take turns on the
    # single physical mouse. Acquired around any sequence that does
    # bring-window-to-front + move + click.
    # RLock so the same thread can re-enter — the MC loop holds this around
    # _banking_tick, and banking_tick re-acquires it for the actual click.
    # A plain Lock here deadlocks the master loop (WATCHDOG stalls at [init]).
    MOUSE_LOCK = threading.RLock()

    # ── Round-robin turn control ──────────────────────────────────────────────
    # Set by the GUI at start: ordered list of active client_ids.
    # Only the client whose id == _ACTIVE_CLIENT_IDS[_TURN_IDX % n] may run
    # the click / rotate path. After each click the holder advances the index.
    # _TURN_SINCE records when the current holder acquired the turn so we can
    # auto-advance if a bot is stuck (no ore found) after TURN_TIMEOUT_S secs.
    _ACTIVE_CLIENT_IDS = []   # e.g. [0, 1] for master + Bot2
    _TURN_IDX = [0]           # current position in the list
    _TURN_SINCE = [0.0]       # monotonic time when current holder got the turn
    _TURN_LOCK = threading.Lock()
    TURN_TIMEOUT_S = 10.0     # auto-advance after this many seconds if no click

    def __init__(self, config, gui, client_id=0, window_title=None, hwnd=None):
        self.config = config
        self.gui = gui
        self.client_id = client_id
        if window_title:
            # Per-client override of which window this bot owns.
            self.config = dict(config)
            self.config['window_title'] = window_title
        self.running = False
        self.stop_reason = ''
        # hwnd can be pre-resolved by the GUI before window titles are tagged/renamed,
        # avoiding find_window confusion when multiple windows share the same base title.
        self.hwnd = hwnd or None
        self.detector = Detector(config)
        self.banking = BankingFSM(self)
        mouse_cfg = dict(config["mouse_settings"])
        # Auto-randomize seed each session unless user pinned one
        if mouse_cfg.get("mouse_seed") is None:
            mouse_cfg["mouse_seed"] = random.randint(0, 9999)
        self._mouse_seed = mouse_cfg["mouse_seed"]
        # Pass-through: when 'instant_movement' is set in top-level config, the
        # mouse skips the bezier curve / overshoot / hesitation entirely. Click
        # timings (pre-click pause, hold duration) stay randomized.
        mouse_cfg["instant_movement"] = bool(config.get("instant_movement", False))
        print(f"[MOUSE] Profile seed: {self._mouse_seed} "
              f"(instant_movement={mouse_cfg['instant_movement']})")
        self.mouse = HumanMouse(mouse_cfg)
        self.sct = None
        self.inventory_count = 0
        self.inventory_total = 30
        self._inv_fallback_limit = random.randint(28, 30)
        self._click_attempts = {}
        self._blacklist = {}  # key -> expire_time
        
        self._det_buf = _DetectionBuffer()
        self._model_lock = threading.Lock()  # guards detector.detect_with_vis() across threads

        # OCR result caches — skip inference when the screen region is unchanged
        self._fat_last_good_tess_idx = 0   # which _preprocess variant won last pytesseract call
        self._fat_crop_hash          = 0   # downsampled hash of last fatigue crop ROI
        self._fat_last_result        = None
        self._inv_roi_hash           = 0
        self._inv_roi_cache          = None  # (cur, total) from last successful inventory OCR
        self._fatmsg_roi_hash        = 0
        self._fatmsg_roi_cache       = False
        # Shared chat-region OCR cache (standing-here + chat-text read the same pixels)
        self._chat_roi_hash          = 0
        self._chat_roi_text          = ""
        # overlay_mode_var TTL cache — avoids cross-thread tkinter .get() every 50-1200ms
        self._overlay_active_cache    = False
        self._overlay_active_cache_ts = 0.0

        # Live tracking
        self.current_fatigue = 0
        self._high_fatigue_count = 0
        self._fatigue_stop_threshold = random.randint(90, 100)
        self.last_click_time = 0
        self.mouse_x = 0  # Current mouse X coordinate
        self.mouse_y = 0  # Current mouse Y coordinate
        
        self.last_break_time = time.time()
        self.next_break_interval = self.get_random_break_interval()
        self.break_end_time = 0

        self._mine_count = 0
        self._last_mine_count_time = 0.0
        # Inactivity safety net: if no click / banking transition for >45s the
        # OCR/idle watchdog re-issues ::walkto train. Bumped on every
        # _mine_count increment, every _bank_enter, and on bot start.
        self._last_activity_ts = time.time()
        self._idle_walkto_last_at = 0.0  # rate-limit the safety walkto
        self._walkto_sent_at = 0.0       # timestamp of last ::walkto — 30s dead zone
        # Startup recovery: if no click has landed within 10s of bot start,
        # assume the bot is somewhere it can't see ore (e.g. spawned at the
        # bank) and fire ::walkto train once so it reaches the mining area.
        self._started_at = time.time()
        self._first_click_seen = False
        self._startup_walkto_fired = False
        # Anchor for the click-based bank trigger. Banking fires when
        # (_mine_count - _mine_count_at_bank_done) >= _bank_at_clicks.
        # Initialized to 0 so the first bank run also requires the full
        # threshold of fresh clicks from startup.
        self._mine_count_at_bank_done = 0
        # Re-rolled each bank run so trips vary between 32-36 clicks (matches
        # observed full-inventory range). Looks more human + spreads timing.
        self._bank_at_clicks = self._roll_bank_clicks()
        # Count of full-inventory bank runs this bot has completed. Incremented
        # when CLOSE_BANK transitions to WALK_TO_TRAIN (deposit confirmed,
        # walkto sent). GUI sums these and multiplies by 28 for ores-banked.
        self._banks_completed = 0
        self._last_click_center = None  # (screen_x, screen_y) of last click

        self._overlay_buf = _OverlayBuffer()
        self._overlay_refresh_flag = False
        
        self.no_ore_counter = 0
        self.max_no_ore_moves = 5
        self._no_red_x_rotation_count = 0
        # Last time we saw a live game signal (ore detection, inventory OCR,
        # or fatigue OCR). If this goes stale for 30s the bot is likely not
        # logged in — stop as a fail-safe.
        self._last_signal_time = time.time()
        self._last_rotation_time = 0.0
        self._camera_settle_secs = 0.85
        self._last_clicked_key = None
        self._last_clicked_class = None
        self._last_acted_frame_ts = 0.0  # timestamp of the frame we last clicked on
        self._watchdog_ts = time.time()
        self._watchdog_stage = 'init'
        self._inv_fallback_limit = 30  # kept for reference, not used for click counting

        # Mining speed mode (Fast vs Lazy)
        self.fast_mining_enabled = config.get('fast_mining_enabled', True)

        # Anti-ban master switch — when False, disables all antiban checks
        # (individual feature toggles are honored when master is True).
        self.antiban_master_enabled = config.get('antiban_master_enabled', True)

        # Super-Lazy break tracking
        self._sl_next_break_at = None  # mine-count threshold for next long break

        # "Standing here" suppression (avoid double-acting within 15s)
        self._standing_last_check = 0.0
        self._standing_last_detected = 0.0

        # Powermine: when standing-here fires, click a far ore next turn.
        self._force_far_ore = False

        # Banking state machine (lazy — model loaded on first run).
        # States: IDLE, WALK_TO_BANK, FIND_BANKER, WAIT_BANK_UI,
        #         CLICK_MINE_PRESET, CLOSE_BANK, WALK_TO_TRAIN
        self._banking_state = 'IDLE'
        self._banking_state_at = 0.0
        self._banking_request = False     # set by OCR thread when inv full
        self._banker_model = None         # NPCS_TEST1.pt — lazy
        self._banking_attempts = 0

        # Live status surfaced to the GUI per-client.
        self.paused = False
        self.last_action = 'Idle'
        self.last_action_ts = time.time()

        # Multi-client mode support.
        # _peer_bots: set on master by start_bot() when multi_client_mode is on.
        # _background_only: set on slave bots — run detection threads only, no action loop.
        self._peer_bots = []
        self._background_only = False

        # Teleport / environment-change detector
        self._env_baseline = None       # small grayscale fingerprint (numpy array)
        self._env_last_check = 0.0
        self._env_pause_until = 0.0     # skip checks during known self-caused motion
        self._env_trip_count = 0        # consecutive drastic frames required to trip
        self._last_window_region = None  # shared with OCR background thread

    def _stop_bot(self, reason, beep_pattern=None, stop_all=False):
        """Central stop handler — sets reason, beeps, updates GUI.
        In multi-client mode, only the master bot triggers a full GUI stop;
        slaves stop themselves and let the master keep running.
        Pass stop_all=True to force a full shutdown of ALL clients (e.g. on
        moderator detection or chat trigger words — emergency stops)."""
        self.stop_reason = reason
        self.running = False
        print(f"[STOP] {reason}")
        try:
            self.gui.log_debug(f'⛔ STOPPED: {reason}')
        except Exception:
            pass
        # Always beep on stop — use provided pattern, or default alarm
        try:
            pattern = beep_pattern or [(1200, 200), (900, 200), (1500, 400)]
            for freq, dur in pattern:
                winsound.Beep(freq, dur)
        except Exception:
            pass
        # In multi-client mode, a slave stopping should NOT shut down all bots
        # — UNLESS stop_all=True (emergency: moderator / trigger words detected).
        _is_slave = (getattr(self, 'gui', None) is not None
                     and getattr(self.gui, 'bot', None) is not None
                     and self is not self.gui.bot)
        if _is_slave and not stop_all:
            # Just mark ourselves stopped; master's MC loop will skip us.
            print(f'[STOP] Bot{self.client_id+1} is a slave — stopping self only, master continues')
            try:
                self.gui.log_debug(f'⛔ Bot{self.client_id+1} stopped: {reason} (others continue)')
            except Exception:
                pass
            return
        if _is_slave and stop_all:
            print(f'[STOP] Bot{self.client_id+1} triggering GLOBAL stop (stop_all): {reason}')
            try:
                self.gui.log_debug(f'🚨 Bot{self.client_id+1} triggering ALL-BOT STOP: {reason}')
            except Exception:
                pass
        try:
            self.gui.root.after(0, lambda r=reason: self.gui.show_stop_reason(r))
        except Exception:
            pass
        try:
            self.gui.root.after(0, self.gui.stop_bot)
        except Exception:
            pass

    # ── Banking sound (coin WAVs, random) ────────────────────────────────────
    _COIN_SOUNDS = [
        os.path.join(os.path.dirname(__file__), 'sounds', 'coins1.wav'),
        os.path.join(os.path.dirname(__file__), 'sounds', 'coins2.wav'),
        os.path.join(os.path.dirname(__file__), 'sounds', 'coins3.wav'),
        os.path.join(os.path.dirname(__file__), 'sounds', 'coins4.wav'),
    ]

    def _play_cash_register_sound(self):
        """Play a random coin WAV via winsound in a daemon thread so it doesn't block."""
        import threading
        def _play():
            try:
                import winsound
                path = random.choice(MiningBot._COIN_SOUNDS)
                print(f'[SOUND] Playing: {os.path.basename(path)}')
                if not os.path.isfile(path):
                    print(f'[SOUND] File not found: {path}')
                    return
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
            except Exception as e:
                print(f'[SOUND] error: {e}')
        threading.Thread(target=_play, daemon=True).start()

    def _speed_mode(self):
        """Resolve the active speed mode for THIS client.
        'super_fast' / 'fast' / 'lazy' / 'super_lazy'.
        Reads `speed_mode` first; falls back to legacy `fast_mining_enabled`."""
        mode = (self.config.get('speed_mode') or '').lower().strip()
        if mode in ('ultra_fast', 'super_fast', 'fast', 'lazy', 'super_lazy'):
            return mode
        return 'fast' if self.config.get('fast_mining_enabled', True) else 'lazy'

    def _bot_mode(self):
        """Resolve the active bot mode: 'mining' / 'fight' / 'banking'.
        'banking' is a transient sub-state of mining or fight (handled by the
        loop), so this returns the user-selected top-level mode."""
        m = (self.config.get('bot_mode') or 'mining').lower().strip()
        return m if m in ('mining', 'fight') else 'mining'

    def _target_classes(self):
        """Class names this bot is currently allowed to click on, sourced from
        the active selection dict for the bot's mode."""
        if self._bot_mode() == 'fight':
            sel = self.config.get('npc_checkboxes', {})
        else:
            sel = self.config.get('ore_checkboxes', {})
        return {k for k, v in sel.items() if v}

    def _selected_target_summary(self):
        """Human-readable summary of currently selected target classes."""
        targets = sorted(self._target_classes())
        if not targets:
            return 'no targets'
        pretty = [t.replace('_rock', '').replace('_', ' ') for t in targets]
        if len(pretty) <= 2:
            return '/'.join(pretty)
        return f'{pretty[0]}/{pretty[1]}+{len(pretty) - 2}'

    def _scan_action_text(self, elapsed=None):
        """Status text for no-target/no-ore scan phases."""
        text = f'Scanning {self._selected_target_summary()}'
        if elapsed is not None:
            text = f'{text} ({elapsed}s)'
        return text

    def _set_action(self, msg):
        """Update last_action / timestamp — read by GUI status panel."""
        self.last_action = msg
        self.last_action_ts = time.time()

    def pause(self):
        self.paused = True
        self._set_action('Paused')

    def resume(self):
        self.paused = False
        self._set_action('Resumed')

    def _schedule_next_clickback(self):
        """Pick the next clickback fire time using a jittered minute range.
        User picks V minutes; actual fire = V*60 - random(30, 60) seconds.
        So 5 → 4:00–4:30, 15 → 14:00–14:30."""
        try:
            mn = int(self.config.get('clickback_min_min', 5))
            mx = int(self.config.get('clickback_max_min', 15))
        except (TypeError, ValueError):
            mn, mx = 5, 15
        if mn > mx: mn, mx = mx, mn
        v = random.randint(mn, mx)
        delay = v * 60 - random.uniform(30.0, 60.0)
        self._next_clickback_at = time.time() + max(60.0, delay)
        self._dbg(f'[CLICKBACK] next fire in {delay:.0f}s (base {v}m)')

    def _do_clickback(self):
        """Perform Click A then Click B at user-configured screen coords."""
        a = self.config.get('clickback_a')
        b = self.config.get('clickback_b')
        if not a or not b:
            self._dbg('[CLICKBACK] skipped — A or B not set')
            return
        try:
            self.gui.log_debug(f'Clickback fire: A{tuple(a)} → B{tuple(b)}')
        except Exception:
            pass
        try:
            with MiningBot.MOUSE_LOCK:
                self.bring_window_to_front()
                self.mouse.move_and_click((int(a[0]), int(a[1])))
                time.sleep(random.uniform(0.4, 1.0))
                self.mouse.move_and_click((int(b[0]), int(b[1])))
        except Exception as e:
            self._dbg(f'[CLICKBACK] error: {e}')

    def _client_slot_config(self):
        """Return this bot's per-client slot config, if one exists."""
        if self.client_id <= 0:
            return {}
        clients = self.config.get('clients') or []
        if self.client_id < len(clients) and isinstance(clients[self.client_id], dict):
            return clients[self.client_id]
        return {}

    def _active_fixed_ore_spots(self, cfg=None):
        """Return fixed spots only when that config actually has them enabled.

        The `fixed_ore_spots_enabled` key MUST be explicitly True for spots
        to be active. If the key is absent (e.g. legacy / stale config), spots
        are treated as disabled so they never silently filter out ore detections.
        """
        cfg = cfg or self.config
        spots = list(cfg.get('fixed_ore_spots') or [])
        if not spots:
            return []
        return spots if cfg.get('fixed_ore_spots_enabled', False) else []

    def _walkto_source_dict(self):
        """Resolve walkto destinations from master or per-client settings."""
        slot = self._client_slot_config()
        if not slot or slot.get('walkto_mimic_master', True):
            return self.config
        merged = dict(self.config)
        merged.update(slot)
        return merged

    def _uses_master_walkto(self):
        """Return True when this bot should follow the master's walkto choices."""
        slot = self._client_slot_config()
        return not slot or slot.get('walkto_mimic_master', True)

    def _pick_walkto_value(self, keys, *, fallback_key='', shared_attr=None):
        """Resolve a walkto destination from ordered keys.

        Master-driven destinations are resolved deterministically from the first
        non-blank entry so stale legacy fields do not randomly override the
        current master choice. Per-client overrides still keep the older random
        pool behavior when mimic-master is OFF.
        """
        src = self._walkto_source_dict()
        use_master = self._uses_master_walkto()

        if use_master and shared_attr and self.client_id > 0:
            shared = (getattr(self.gui, shared_attr, '') or '').strip()
            if shared:
                return shared

        pool = []
        for key in keys:
            value = (src.get(key, '') or '').strip()
            if value and value.lower() != 'none':
                pool.append(value)

        fallback = ''
        if fallback_key:
            fallback = (src.get(fallback_key, '') or '').strip()

        if not pool:
            choice = fallback
        elif use_master:
            choice = pool[0]
        else:
            choice = random.choice(pool)

        if use_master and shared_attr and choice:
            setattr(self.gui, shared_attr, choice)
        return choice

    def _note_registered_click(self, confirmed=True):
        """Reset the no-red-X rotation counter after a confirmed click."""
        if confirmed is False:
            return
        self._no_red_x_rotation_count = 0
        # Coal found — restore the normal coal-only confidence (0.75).
        try:
            self.detector.coal_relax = False
        except Exception:
            pass

    def _roll_bank_clicks(self):
        """Return clicks-until-bank value. Uses user min/max range if set, else random 29–34."""
        try:
            lo = int(self.config.get('bank_clicks_min') or 0)
            hi = int(self.config.get('bank_clicks_max') or 0)
            if lo > 0 and hi > 0 and hi >= lo:
                return random.randint(lo, hi)
            if lo > 0 and hi == 0:
                return lo  # only min set — use as exact value
        except (TypeError, ValueError):
            pass
        return random.randint(29, 34)

    def _pick_walkto_destination(self):
        """Resolve the active bank walkto destination."""
        return self._pick_walkto_value(
            ('walkto_dest1_a', 'walkto_dest1_b', 'walkto_dest1_user', 'walkto_dest1_xy'),
            fallback_key='walkto_destination',
            shared_attr='_shared_walkto_bank_destination',
        )

    def _pick_walkto_train_destination(self):
        """Resolve the active training walkto destination."""
        return self._pick_walkto_value(
            ('walkto_train1_user', 'walkto_train1_xy'),
            shared_attr='_shared_walkto_train_destination',
        )

    def _pick_teleport_reaction(self):
        """Pick what to type after a teleport-detect trigger.
        Source: a single comma-separated user-editable string. Random pick if
        `teleport_pick_random` else first item."""
        raw = (self.config.get('teleport_reactions_text', '') or '').strip()
        pool = [s.strip() for s in raw.split(',') if s.strip()]
        if not pool:
            # Legacy fallbacks
            legacy = (self.config.get('teleport_message', '') or '').strip()
            if legacy:
                pool = [legacy]
        if not pool:
            return ''
        if self.config.get('teleport_pick_random', True):
            return random.choice(pool)
        return pool[0]

    def _schedule_walkto_beeps(self):
        """WalkTo beeps removed per user request — arrival beeps no longer fire."""
        pass

    def _verify_click_marker(self, screen_x, screen_y, max_wait=0.50):
        """Look for the RSC red-X click marker at (screen_x, screen_y).

        The marker is a bright red cross that animates outward from the click
        point for ~200ms after a click registers. We poll a 60x60 ROI for red
        pixels — if we find enough, the game received the click. Returns True
        if confirmed within `max_wait` seconds, else False.
        """
        try:
            if not hasattr(self, '_verify_sct'):
                self._verify_sct = mss()
            roi_size = 60
            region = {
                'left': int(screen_x - roi_size // 2),
                'top':  int(screen_y - roi_size // 2),
                'width': roi_size, 'height': roi_size,
            }
            deadline = time.time() + max_wait
            poll = 0.025  # 25ms polls — marker lives ~200ms
            while time.time() < deadline:
                shot = self._verify_sct.grab(region)
                bgr = np.frombuffer(shot.raw, dtype=np.uint8) \
                        .reshape((shot.height, shot.width, 4))[:, :, :3]
                hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
                # Red wraps around 0/180 in HSV — two ranges
                m1 = cv2.inRange(hsv, np.array([0,   140, 140]), np.array([10,  255, 255]))
                m2 = cv2.inRange(hsv, np.array([170, 140, 140]), np.array([180, 255, 255]))
                red_count = int(cv2.countNonZero(m1) + cv2.countNonZero(m2))
                if red_count >= 12:
                    return True
                time.sleep(poll)
            return False
        except Exception as _e:
            self._dbg(f'[VERIFY] marker check failed: {_e}')
            return True  # fail open — don't block the bot if verification breaks

    def get_click_position(self, box):
        """Click within ±3px of the box center, clamped inside the box."""
        x1, y1, x2, y2 = box
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        x = int(max(x1 + 2, min(x2 - 2, cx + random.randint(-3, 3))))
        y = int(max(y1 + 2, min(y2 - 2, cy + random.randint(-3, 3))))
        return (x, y)
    
    def get_distance_from_center(self, box, frame_width, frame_height):
        """Calculate distance from ore center to screen center"""
        x1, y1, x2, y2 = box
        ore_cx = (x1 + x2) / 2.0
        ore_cy = (y1 + y2) / 2.0
        
        screen_cx = frame_width / 2.0
        screen_cy = frame_height / 2.0
        
        # Euclidean distance
        distance = ((ore_cx - screen_cx) ** 2 + (ore_cy - screen_cy) ** 2) ** 0.5
        return distance
    
    def get_random_break_interval(self):
        """Get random interval before next break"""
        min_sec = self.config["break_settings"].get("min_seconds_between_breaks", 600)
        max_sec = self.config["break_settings"].get("max_seconds_between_breaks", 3600)
        return random.uniform(min_sec, max_sec)
    
    def get_random_break_duration(self):
        """Get random break duration"""
        min_sec = self.config["break_settings"].get("min_break_duration_seconds", 60)
        max_sec = self.config["break_settings"].get("max_break_duration_seconds", 1200)
        return random.uniform(min_sec, max_sec)
    
    def find_window(self):
        """Resolve self.hwnd from the configured window title.
        Prefers exact match, then case-insensitive partial match.
        Handles RSCRevolution / RSCRevolution 2 naming variants automatically."""
        # Prefer a pre-resolved hwnd (avoids same-title confusion + post-tagging renames).
        try:
            if self.hwnd and win32gui.IsWindow(self.hwnd):
                title = win32gui.GetWindowText(self.hwnd)
                print(f'[CLIENT {self.client_id}] Using pre-resolved hwnd={self.hwnd} title="{title}"')
                return True
        except Exception:
            self.hwnd = None  # invalid handle — fall through to search

        target_title = self.config.get("window_title", "")
        if not target_title:
            return False

        exact = []
        partial = []

        def enum_callback(hwnd, _):
            txt = win32gui.GetWindowText(hwnd)
            if not txt:
                return True
            if txt.lower() == target_title.lower():
                exact.append(hwnd)
            elif target_title.lower() in txt.lower() or txt.lower() in target_title.lower():
                partial.append(hwnd)
            return True

        win32gui.EnumWindows(enum_callback, None)

        chosen = exact[0] if exact else (partial[0] if partial else None)
        if chosen:
            self.hwnd = chosen
            print(f'[CLIENT {self.client_id}] hwnd={chosen} title="{target_title}" '
                  f'({"exact" if exact else "substring"})')
            return True
        return False
    
    def bring_window_to_front(self):
        if self.hwnd:
            # Fast path: already focused — no sleep needed at all.
            if win32gui.GetForegroundWindow() == self.hwnd:
                return
            try:
                # AttachThreadInput trick — lets SetForegroundWindow work
                # even when another window in our process has focus
                foreground_hwnd = win32gui.GetForegroundWindow()
                fg_tid = ctypes.windll.user32.GetWindowThreadProcessId(
                    foreground_hwnd, None)
                cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = False
                if fg_tid != cur_tid:
                    ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, True)
                    attached = True
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(self.hwnd)
                if attached:
                    ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, False)
            except Exception:
                try:
                    win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(self.hwnd)
                except Exception:
                    pass
            time.sleep(0.08)
    
    def move_camera(self):
        # Cooldown: don't rotate again for 1.5–2.5s so rotations don't stack back-to-back.
        # Check BEFORE incrementing so the zoom-out counter only counts real rotations.
        if time.time() - self._last_rotation_time < random.uniform(1.5, 2.5):
            return

        self.no_ore_counter += 1
        if self.no_ore_counter >= self.max_no_ore_moves:
            self.no_ore_counter = 0

        # Always use keyboard arrow keys — RSC does not reliably respond to
        # middle-mouse drag for camera rotation, so _mouse_rotate is dropped.
        # auto-rotate/zoom mode uses all 4 arrow keys + occasional scroll zoom;
        # rotate-only mode restricts to left/right (handled inside _keyboard_rotate).
        self._keyboard_rotate()
        # In auto-rotate/zoom mode, occasionally scroll-zoom after rotating.
        if not self.config.get('camera_rotate_only', False) and random.random() < 0.25:
            self._zoom_out()
        self._last_rotation_time = time.time()
        self._pause_env_check(3.0, reset_baseline=True)

    def _force_rotate(self):
        """Force camera rotation immediately without the cooldown check."""
        self._keyboard_rotate()
        self._last_rotation_time = time.time()
        self._pause_env_check(3.0, reset_baseline=True)

    def _biased_lr_key(self):
        """Pick left vs right arrow with a 70/30 bias toward a favored side.
        The favored side is chosen randomly once per bot instance so each
        window sweeps predominantly one way (looks less mechanical than a
        strict alternation or a 50/50 coin flip) while still occasionally
        checking the other side."""
        fav = getattr(self, '_rotate_favored_dir', None)
        if fav is None:
            fav = random.choice((win32con.VK_LEFT, win32con.VK_RIGHT))
            self._rotate_favored_dir = fav
        other = win32con.VK_RIGHT if fav == win32con.VK_LEFT else win32con.VK_LEFT
        return fav if random.random() < 0.70 else other

    def _keyboard_rotate(self):
        # Focus first so keybd_event reaches the game, then also send PostMessage
        # as a belt-and-suspenders fallback (Java may prefer one path or the other).
        self.bring_window_to_front()
        # Rotate-only mode: restrict to left/right only (no tilt up/down).
        if self.config.get('camera_rotate_only', False):
            actions = [win32con.VK_LEFT, win32con.VK_RIGHT]
        else:
            actions = [win32con.VK_LEFT, win32con.VK_RIGHT, win32con.VK_UP, win32con.VK_DOWN]
        sequence_length = 1 if random.random() < 0.8 else 2
        for _ in range(sequence_length):
            key = random.choice(actions)
            if key in (win32con.VK_LEFT, win32con.VK_RIGHT):
                key = self._biased_lr_key()  # 70/30 favored-side bias
            press_duration = random.uniform(0.10, 0.25)
            win32api.keybd_event(key, 0, 0, 0)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, key, 0)
            time.sleep(press_duration)
            win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, key, 0)
            time.sleep(random.uniform(0.25, 0.55))

    def _zoom_out(self):
        """Scroll down to zoom out after repeated no-ore rotations.
        Skipped when camera_rotate_only is enabled."""
        if self.config.get('camera_rotate_only', False):
            return
        try:
            rect = win32gui.GetClientRect(self.hwnd)
            pt = win32gui.ClientToScreen(self.hwnd, (rect[2] // 2, rect[3] // 2))
            win32api.SetCursorPos(pt)
            time.sleep(0.05)
            for _ in range(random.randint(2, 4)):
                win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, -120, 0)
                time.sleep(random.uniform(0.08, 0.15))
            self._last_rotation_time = time.time()
            print("[CAMERA] Zoomed out after 5 failed rotations")
            try:
                self.gui.log_debug('Zoomed out — no ores found after 5 rotations')
            except Exception:
                pass
        except Exception:
            pass

    def _mouse_rotate(self):
        # Bring window to front so middle-drag is received by the game
        self.bring_window_to_front()
        try:
            rect = win32gui.GetClientRect(self.hwnd)
            pt = win32gui.ClientToScreen(self.hwnd, (0, 0))
            cx = pt[0] + random.randint(int(rect[2] * 0.3), int(rect[2] * 0.7))
            cy = pt[1] + random.randint(int(rect[3] * 0.3), int(rect[3] * 0.7))
            win32api.SetCursorPos((cx, cy))
            time.sleep(0.05)
        except Exception:
            return
        start_x, start_y = win32api.GetCursorPos()
        # Larger horizontal drag so RSC registers a meaningful camera rotation
        target_x = start_x + random.randint(-150, 150)
        target_y = start_y + random.randint(-20, 20)

        win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
        try:
            time.sleep(random.uniform(0.04, 0.08))
            steps = random.randint(12, 20)
            for i in range(1, steps + 1):
                t = i / steps
                x = int(start_x + (target_x - start_x) * t)
                y = int(start_y + (target_y - start_y) * t)
                win32api.SetCursorPos((x, y))
                time.sleep(random.uniform(0.008, 0.020))
            time.sleep(random.uniform(0.05, 0.10))
        finally:
            # Always release middle button — prevents camera getting stuck spinning
            win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)
        time.sleep(random.uniform(0.15, 0.25))

    def _read_inventory_from_frame(self, frame):
        """Read inventory count (X/30) from top-right corner of RSC window.
        Region was widened (x1 0.88→0.78, y2 0.07→0.12) to give OCR more pixels —
        smaller crops were dropping the "/30" suffix at high DPI.
        """
        if not _HAVE_OCR:
            return None
        import re
        h, w = frame.shape[:2]

        x1 = int(w * 0.78)            # right 22% of width (was 12%)
        y1 = max(0, int(h * 0.01))    # ~1% down to skip window border
        x2 = w
        y2 = int(h * 0.12)            # top 12% (was 7%)
        roi = frame[y1:y2, x1:x2]

        if roi.size == 0:
            return None

        # Skip EasyOCR entirely if the inventory region pixel content is unchanged.
        # Items in RSC change the text and thus the pixels; same hash → same count.
        _roi_hash = hash(roi[::2, ::2].tobytes())
        if _roi_hash == self._inv_roi_hash and self._inv_roi_cache is not None:
            return self._inv_roi_cache

        try:
            global _ocr_reader
            if _ocr_reader is None:
                _ocr_reader = _make_ocr_reader()

            import cv2
            # Upscale 6x — text is very small (tic-tac sized), needs aggressive scaling
            roi_up = cv2.resize(roi, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)

            def _try_ocr(img):
                r = _ocr_reader.readtext(img, detail=0, allowlist='0123456789/')
                return " ".join(r).strip() if r else ""

            # Method 1: raw upscaled
            detected_text = _try_ocr(roi_up)

            # Method 2: isolate yellow/orange text (RSC inventory font color)
            # Yellow-orange = high R, high G, low B in BGR
            if not detected_text or not re.search(r'\d', detected_text):
                hsv = cv2.cvtColor(roi_up, cv2.COLOR_BGR2HSV)
                # Hue 15-35 covers orange→yellow, high saturation & value
                mask = cv2.inRange(hsv, (15, 100, 100), (35, 255, 255))
                isolated = cv2.bitwise_and(roi_up, roi_up, mask=mask)
                gray_iso = cv2.cvtColor(isolated, cv2.COLOR_BGR2GRAY)
                _, thresh_iso = cv2.threshold(gray_iso, 50, 255, cv2.THRESH_BINARY)
                detected_text = _try_ocr(thresh_iso)

            # Method 3: plain grayscale threshold fallback
            if not detected_text or not re.search(r'\d', detected_text):
                gray = cv2.cvtColor(roi_up, cv2.COLOR_BGR2GRAY)
                _, thresh = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY)
                detected_text = _try_ocr(thresh)

            # Method 4: Tesseract fallback (often more reliable on small line text).
            # Always run this if EasyOCR's text doesn't contain a clean "/" — it's
            # cheap on a tiny ROI and catches the missing-leading-digit case.
            if '/' not in detected_text:
                try:
                    import pytesseract as _tess
                    # PSM 7 = single line, restrict to digits + slash.
                    cfg = r'--psm 7 -c tessedit_char_whitelist=0123456789/'
                    gray = cv2.cvtColor(roi_up, cv2.COLOR_BGR2GRAY)
                    _, thresh_t = cv2.threshold(gray, 110, 255, cv2.THRESH_BINARY)
                    tess_text = _tess.image_to_string(thresh_t, config=cfg).strip()
                    if tess_text and re.search(r'\d', tess_text):
                        # Prefer tesseract result if it has a slash that EasyOCR missed
                        if '/' in tess_text and '/' not in detected_text:
                            detected_text = tess_text
                        elif not detected_text:
                            detected_text = tess_text
                except Exception:
                    pass

            if detected_text:
                self._dbg(f'[INV-OCR] raw text: {detected_text!r}')
                m = re.search(r'(\d+)\s*/\s*(\d+)', detected_text)
                if m:
                    cur = int(m.group(1))
                    total = int(m.group(2))
                    if 0 <= cur <= 31 and 25 <= total <= 31:
                        self._inv_roi_hash  = _roi_hash
                        self._inv_roi_cache = (cur, total)
                        self._inv_last_parse_mode = 'strict'
                        self._dbg(f'[INV-OCR] parsed slash: {cur}/{total}')
                        return cur, total
                # Fallback: OCR dropped "/" — e.g. "730" → cur=7 total=30
                m2 = re.search(r'(\d{1,2})(30|29|28|27|26|25)', detected_text)
                if m2:
                    cur = int(m2.group(1))
                    total = int(m2.group(2))
                    if 0 <= cur <= 31:
                        self._inv_roi_hash  = _roi_hash
                        self._inv_roi_cache = (cur, total)
                        self._inv_last_parse_mode = 'no-slash'
                        self._dbg(f'[INV-OCR] parsed no-slash: {cur}/{total}')
                        return cur, total
                # Last-resort: any "30" alone after at least one digit suggests full inv
                if re.search(r'3\s*0\s*/?\s*3\s*0', detected_text):
                    self._inv_roi_hash  = _roi_hash
                    self._inv_roi_cache = (30, 30)
                    self._inv_last_parse_mode = 'loose'
                    self._dbg('[INV-OCR] parsed loose 30/30')
                    return 30, 30
                self._dbg(f'[INV-OCR] no parse: {detected_text!r}')
            else:
                self._dbg('[INV-OCR] OCR returned empty')
        except Exception as e:
            self._dbg(f'[INV-OCR] exception: {e}')
        return None

    def check_fatigue_message(self, frame, window_region):
        """Check bottom-left chat area for 'you are too tired to mine this rock'."""
        if not _HAVE_OCR or not self.config.get('fatigue_detection_enabled', True):
            print(f'[FATIGUE MSG] skipped — _HAVE_OCR={_HAVE_OCR} fatigue_enabled={self.config.get("fatigue_detection_enabled", True)}')
            return False

        try:
            global _ocr_reader
            if _ocr_reader is None:
                _ocr_reader = _make_ocr_reader()

            h, w = frame.shape[:2]
            # Bottom-left chat: bottom 30% height, left 75% width
            roi = frame[int(h * 0.70):int(h * 0.95), 0:int(w * 0.75)]
            if roi.size == 0:
                print('[FATIGUE MSG] roi empty')
                return False

            # Upscale 3× for small chat text
            roi_up = cv2.resize(roi, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

            keywords = ("too tired to mine", "too tired", "tired to mine",
                        "start to feel tired", "feel tired", "should rest soon",
                        "maybe you should get some rest", "get some rest")

            def _contains(text):
                t = text.lower()
                return any(k in t for k in keywords)

            results = _ocr_reader.readtext(roi_up, detail=0)
            detected = " ".join(results).lower() if results else ""
            print(f'[FATIGUE MSG] OCR read: {detected!r}')
            if _contains(detected):
                print(f'[FATIGUE MSG] MATCH — stopping bot')
                try:
                    self.gui.log_debug(f'🛑 Fatigue: {detected}')
                except Exception:
                    pass
                return True

        except Exception as e:
            print(f'[FATIGUE MSG] exception: {e}')
        return False

    
    def check_fatigue_bar_topleft(self, frame):
        """
        Alternative fatigue detection: Check the fatigue bar on top-left of game window.
        The fatigue indicator is usually in the top-left stats area.
        Returns True if fatigue bar appears to be at 100% (red/full).
        """
        try:
            h, w = frame.shape[:2]
            
            # Top-left corner where stats/fatigue bar typically is (roughly first 15% width, first 20% height)
            roi_topleft = frame[0:int(h * 0.25), 0:int(w * 0.20)]
            
            if roi_topleft.size == 0:
                return False
            
            # Look for red color (fatigue bar is typically red at high fatigue)
            # Red in BGR is (B, G, R) = (0-50, 0-100, 200-255)
            b, g, r = cv2.split(roi_topleft)
            
            # Create mask for red pixels (high fatigue indicator)
            red_mask = (r > 180) & (g < 120) & (b < 120)
            
            # If more than 5% of top-left area is red, fatigue is likely high
            red_percentage = np.count_nonzero(red_mask) / roi_topleft.size * 100
            
            if red_percentage > 5:
                print(f"[FATIGUE BAR] Detected high fatigue bar (red: {red_percentage:.1f}%)")
                try:
                    self.gui.log_debug(f'⚠️ FATIGUE BAR: High fatigue detected ({red_percentage:.1f}% red)')
                except Exception:
                    pass
                return True
            
        except Exception as e:
            print(f"[FATIGUE BAR] Error checking fatigue bar: {e}")
        
        return False

    def _fatigue_line_variants(self, fat_line):
        """Yield image variants for OCR: raw, green-threshold, red-threshold."""
        yield fat_line
        for ch_idx in (1, 2):  # green, then red (BGR)
            ch = fat_line[:, :, ch_idx]
            ch_up = cv2.resize(ch, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
            _, binary = cv2.threshold(ch_up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            yield binary

    def read_menu_bar_fatigue(self, frame):
        """REMOVED — fatigue % OCR was unreliable and unnecessary. Kept as no-op
        for backwards compat; callers will see None and do nothing.
        Use the bottom 'too tired to mine' OCR (check_fatigue_message) and the
        fatigue 100% template (_tm_check_fatigue100) instead."""
        return None

    def _read_menu_bar_fatigue_DISABLED(self, frame):
        if not self.config.get("fatigue_detection_enabled", True):
            return None

        import re

        try:
            h, w = frame.shape[:2]
            roi = frame[0:int(h * 0.35), 0:int(w * 0.25)]
            if roi.size == 0:
                return None

            def _preprocess(img):
                """8× INTER_NEAREST upscale + multiple binary variants."""
                big = cv2.resize(img, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
                gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY) if len(big.shape) == 3 else big
                _, bw_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                _, bw80 = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY)
                variants = [bw_otsu, cv2.bitwise_not(bw_otsu), cv2.bitwise_not(bw80)]
                if len(img.shape) == 3:
                    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
                    yel = cv2.inRange(hsv, (15, 50, 80), (45, 255, 255))
                    variants.append(yel)
                return variants

            def _parse(text):
                m = re.search(r'(\d{1,3})\s*%?', text.strip())
                if m:
                    v = int(m.group(1))
                    if 0 <= v <= 100:
                        return v
                return None

            # Fatigue is line 3 of 4 → ~45-78% of panel height
            fat_y1 = int(roi.shape[0] * 0.45)
            fat_y2 = int(roi.shape[0] * 0.78)
            fat_crop = roi[fat_y1:fat_y2, :] if (fat_y2 - fat_y1) > 2 else roi
            _src = fat_crop if fat_crop.size > 0 else roi

            # Fast pixel-hash check: if the fatigue region hasn't changed since
            # the last call, return the cached result without touching OCR at all.
            # Fatigue changes slowly (~1% per ~10 rocks) so this skips 80-90% of
            # pytesseract subprocess launches in steady-state mining.
            _fat_hash = hash(_src[::2, ::2].tobytes())
            if _fat_hash == self._fat_crop_hash and self._fat_last_result is not None:
                self.current_fatigue = self._fat_last_result
                return self._fat_last_result

            crop_variants = _preprocess(_src)

            # --- pytesseract (primary) ---
            if _HAVE_PYTESSERACT:
                cfg = '--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789%'
                # Try whichever variant succeeded last time first — in steady-state
                # the same variant keeps working, reducing calls from N to ~1.
                _n = len(crop_variants)
                _last = self._fat_last_good_tess_idx
                _order = list(range(_last, _n)) + list(range(0, _last))
                for _vi in _order:
                    try:
                        v = _parse(pytesseract.image_to_string(crop_variants[_vi], config=cfg))
                        if v is not None:
                            self._dbg(f'[FATIGUE] tess {v}%')
                            self.current_fatigue = v
                            self._fat_last_good_tess_idx = _vi
                            self._fat_crop_hash = _fat_hash
                            self._fat_last_result = v
                            return v
                    except Exception:
                        pass
                # retry on full ROI (only reached when ALL crop variants failed)
                for img_v in _preprocess(roi):
                    try:
                        v = _parse(pytesseract.image_to_string(img_v, config=cfg))
                        if v is not None:
                            self._dbg(f'[FATIGUE] tess-full {v}%')
                            self.current_fatigue = v
                            self._fat_crop_hash = _fat_hash
                            self._fat_last_result = v
                            return v
                    except Exception:
                        pass

            # --- EasyOCR (fallback) ---
            if _HAVE_OCR:
                global _ocr_reader
                if _ocr_reader is None:
                    _ocr_reader = _make_ocr_reader()
                for img_v in crop_variants:
                    try:
                        results = _ocr_reader.readtext(img_v, detail=0,
                                                       allowlist='0123456789%')
                        v = _parse(' '.join(results))
                        if v is not None:
                            self._dbg(f'[FATIGUE] ocr {v}%')
                            self.current_fatigue = v
                            self._fat_crop_hash = _fat_hash
                            self._fat_last_result = v
                            return v
                    except Exception:
                        pass

            self._dbg('[FATIGUE] all methods failed')

        except Exception as e:
            self._dbg(f'[FATIGUE] error: {e}')

        return None
    
    def should_take_break(self):
        if not self.config["break_settings"].get("breaks_enabled", True):
            return False
        return time.time() - self.last_break_time >= self.next_break_interval
    
    def take_break(self):
        duration = self.get_random_break_duration()
        self.break_end_time = time.time() + duration
        print(f"Taking break for {duration:.0f}s...")
        try:
            self.gui.log_debug(f'☕ Break started ({int(duration)}s)')
        except Exception:
            pass
        time.sleep(duration)
        self.break_end_time = 0
        self.last_break_time = time.time()
        self.next_break_interval = self.get_random_break_interval()
    
    def get_micro_break(self):
        """Get a random micro break duration if enabled"""
        if self.config["break_settings"].get("micro_breaks_enabled", False):
            min_ms = self.config["break_settings"].get("micro_break_min_ms", 100)
            max_ms = self.config["break_settings"].get("micro_break_max_ms", 500)
            return random.randint(min_ms, max_ms) / 1000.0
        return 0

    def _interruptible_sleep(self, duration, chunk=1.0):
        """Sleep in small chunks so watchdog and no-signal failsafe stay alive.

        Keeps _watchdog_ts and _last_signal_time updated each tick so that
        long waits (super_lazy 30s, long breaks up to 45s) don't trip the
        30-second no-signal failsafe or flood the watchdog log.
        """
        end = time.time() + duration
        while self.running and time.time() < end:
            remaining = end - time.time()
            time.sleep(min(chunk, remaining) if remaining > 0 else 0)
            self._watchdog_ts = time.time()
            (peek_dets, _, _), _ = self._det_buf.get()
            if peek_dets:
                self._last_signal_time = time.time()
    
    def _dbg(self, msg):
        """Log only when verbose debug is enabled."""
        if not self.config.get('verbose_debug', False):
            return
        ts = time.strftime('%H:%M:%S')
        # Prefix per-bot so MC-mode logs from multiple clients are tellable apart.
        bid = f'Bot{getattr(self, "client_id", 0) + 1}'
        print(f'[DBG {ts}] [{bid}] {msg}')
        try:
            self.gui.log_debug(f'[V] [{bid}] {msg}')
        except Exception:
            pass

    def _start_watchdog(self):
        """Background thread — alerts if main loop stalls >10s."""
        def _watch():
            while self.running:
                time.sleep(5)
                if not self.running:
                    break
                stall = time.time() - self._watchdog_ts
                if stall > 10:
                    msg = f'⚠ WATCHDOG: loop stalled {stall:.1f}s at stage [{self._watchdog_stage}]'
                    print(msg)
                    try:
                        self.gui.log_debug(msg)
                    except Exception:
                        pass
        t = threading.Thread(target=_watch, daemon=True)
        t.start()

    def _start_ocr_thread(self):
        """Background thread: runs slow EasyOCR every ~6s.
        Stores results in self.current_fatigue / self.inventory_count so the
        main action loop never blocks on OCR."""
        def _ocr_loop():
            from mss import mss as _mss_ocr
            sct = _mss_ocr()
            interval = 6.0

            # Pre-warm the EasyOCR reader immediately so it is never lazily
            # initialised mid-game (avoids the PyTorch legacy-format warning
            # for craft_mlt_25k.pth appearing in the middle of a mining session).
            global _ocr_reader
            if _HAVE_OCR and _ocr_reader is None:
                import io as _io, sys as _sys
                _saved_out, _saved_err = _sys.stdout, _sys.stderr
                _sys.stdout = _sys.stderr = _io.StringIO()
                try:
                    _ocr_reader = _make_ocr_reader()
                except Exception:
                    pass
                finally:
                    _sys.stdout, _sys.stderr = _saved_out, _saved_err

            while self.running:
                t0 = time.time()

                # Post-click fatigue check: fires 0.5s after each ore click
                # so "too tired" text is caught immediately rather than waiting
                # up to 6s for the normal interval.
                if time.time() >= getattr(self, '_fatigue_check_after', float('inf')):
                    self._fatigue_check_after = float('inf')  # clear flag
                    try:
                        _fc_region = self._last_window_region
                        if _fc_region is not None:
                            _fc_shot = sct.grab(_fc_region)
                            _fc_frame = np.ascontiguousarray(
                                np.frombuffer(_fc_shot.raw, dtype=np.uint8)
                                .reshape((_fc_shot.height, _fc_shot.width, 4))[:, :, :3])
                            if self.check_fatigue_message(_fc_frame, _fc_region):
                                self._stop_bot('Too tired to mine', [(1000, 200), (1000, 200)])
                                return
                    except Exception as _fce:
                        self._dbg(f'[FATIGUE POST-CLICK] err: {_fce}')

                try:
                    region = self._last_window_region
                    if region is None:
                        time.sleep(0.5)
                        continue

                    screenshot = sct.grab(region)
                    # frombuffer: zero-copy view of mss raw bytes — avoids intermediate np.array() allocation
                    frame = np.ascontiguousarray(
                        np.frombuffer(screenshot.raw, dtype=np.uint8)
                        .reshape((screenshot.height, screenshot.width, 4))[:, :, :3]
                    )

                    # Inventory count — disabled by default (banking now uses
                    # click-count, not OCR). Re-enable via config flag if you
                    # want the live X/30 readout in the GUI again.
                    if self.config.get('inventory_ocr_enabled', False):
                        inv = self._read_inventory_from_frame(frame)
                    else:
                        inv = None

                    # Startup recovery — if no click landed within 20s of bot
                    # start, fire ::walkto train ONCE. Only fires on the master
                    # bot; slaves are driven by the MC loop so their recovery
                    # is handled by the master's idle watchdog instead.
                    try:
                        _user_active_now = False
                        try:
                            import user_activity as _ua2
                            _user_active_now = _ua2.is_user_active(window_secs=2.0)
                        except Exception:
                            pass
                        if _user_active_now:
                            self._started_at = time.time()  # reset clock while paused
                        if (not self._first_click_seen
                                and not self._startup_walkto_fired
                                and self._banking_state == 'IDLE'
                                and not self.config.get('powermine_enabled', False)
                                and time.time() - self._started_at > 30.0):
                            train = self._pick_walkto_train_destination()
                            if not train:
                                train = self._pick_walkto_destination()
                            if train:
                                self._dbg(f'[STARTUP] no click in 30s — ::walkto {train}')
                                try: self.gui.log_debug(f'⚠ Startup recovery → ::walkto {train}')
                                except Exception: pass
                                try:
                                    # No _walkto_sent_at here — recovery walkto
                                    # (nothing found to click) must NOT arm the
                                    # 30s dead zone; keep scanning immediately.
                                    self._type_ingame_message(f'::walkto {train}')
                                except Exception as _e:
                                    self._dbg(f'[STARTUP] walkto err: {_e}')
                                self._startup_walkto_fired = True
                                self._last_activity_ts = time.time()
                    except Exception as _se:
                        self._dbg(f'[STARTUP] recovery err: {_se}')

                    # Idle safety net — if no click / banking transition for
                    # >60s and we're not currently banking or powermining,
                    # re-issue ::walkto train so the bot recovers from a stuck
                    # state. Rate-limited so the same walkto isn't spammed.
                    try:
                        if getattr(self, 'paused', False):
                            self._last_activity_ts = time.time()  # freeze idle timer while paused
                        IDLE_LIMIT_S = 60.0
                        idle = time.time() - getattr(self, '_last_activity_ts', time.time())
                        last_walkto = getattr(self, '_idle_walkto_last_at', 0.0)
                        if (idle > IDLE_LIMIT_S
                                and self._banking_state == 'IDLE'
                                and not self.config.get('powermine_enabled', False)
                                and time.time() - last_walkto > IDLE_LIMIT_S):
                            train = self._pick_walkto_train_destination()
                            if not train:
                                train = self._pick_walkto_destination()
                            if train:
                                self._dbg(f'[IDLE] no activity {idle:.0f}s — ::walkto {train}')
                                try: self.gui.log_debug(f'⚠ Idle {idle:.0f}s → ::walkto {train}')
                                except Exception: pass
                                try:
                                    # No _walkto_sent_at here — recovery walkto
                                    # (nothing found to click) must NOT arm the
                                    # 30s dead zone; keep scanning immediately.
                                    self._type_ingame_message(f'::walkto {train}')
                                except Exception as _e:
                                    self._dbg(f'[IDLE] walkto err: {_e}')
                                self._idle_walkto_last_at = time.time()
                                self._last_activity_ts = time.time()
                    except Exception as _ie:
                        self._dbg(f'[IDLE] watchdog err: {_ie}')
                    if inv is not None:
                        cur, total = inv
                        self.inventory_count = cur
                        self.inventory_total = total
                        self._last_signal_time = time.time()
                        try:
                            self.gui.root.after(0, lambda c=cur, t=total: self.gui.update_inventory(c, t))
                        except Exception:
                            pass

                    # ─── Inventory-full trigger ─────────────────────────
                    # Pure click-count trigger (32-38, rolled at startup +
                    # after each bank). OCR and template-match are turned
                    # off because both produced unreliable false positives /
                    # negatives on the small "X/30" indicator. Lives outside
                    # the `if inv is not None` block so OCR failures don't
                    # block banking from firing.
                    _clicks_since_bank = self._mine_count - self._mine_count_at_bank_done
                    if (_clicks_since_bank >= self._bank_at_clicks
                            and not self.config.get('powermine_enabled', False)):
                        _why = f'{_clicks_since_bank} clicks since last bank'
                        if self.config.get('banking_enabled', False):
                            if self._banking_state == 'IDLE' and not self._banking_request:
                                self._dbg(f'[BANK] Inventory full ({_why}) — requesting bank run')
                                try: self.gui.log_debug(f'🏦 Inventory full ({_why}) → banking')
                                except Exception: pass
                                self._banking_request = True
                        elif self.config.get('stop_on_full_inventory', True):
                            self._stop_bot(f'Inventory full ({_why})',
                                           [(1200, 300), (1200, 300), (1500, 500)])
                            return

                    # Fatigue % OCR removed — disabled per user request.
                    # The 'too tired to mine' bottom OCR + fatigue-100% template
                    # still drive sleeping/stopping logic below.

                    # "Too tired to mine" chat message
                    if self.check_fatigue_message(frame, region):
                        self._stop_bot('Too tired to mine', [(1000, 200), (1000, 200)])
                        return

                    # Top-left fatigue % OCR removed — causes SSL spam on PCs
                    # without up-to-date certificates. Fatigue 100% is detected
                    # via template-match (fatigue100red.png) and the bottom-chat
                    # "too tired to mine" OCR, both handled elsewhere.

                    # "You have been standing here" anti-AFK nudge
                    self._check_standing_here(frame)

                    # Chat-text stop phrases (terror/kleio/moderator names)
                    # stop_all=True so every client shuts down, not just this one.
                    if (self.config.get('antiban_master_enabled', True)
                            and self.config.get('chat_text_stop_enabled', False)):
                        hit = self._detect_chat_text(frame)
                        if hit:
                            self._stop_bot(f'Chat text matched: "{hit}"',
                                           [(1600, 200), (1000, 200)],
                                           stop_all=True)
                            return

                    # Autologin: fires when bot has been idle long enough and
                    # autologin_enabled is toggled on for this client.
                    try:
                        if (self.config.get('autologin_enabled', True)
                                and self._banking_state == 'IDLE'
                                and not getattr(self, 'paused', False)
                                and not getattr(self, '_autologin_running', False)):
                            _al_thresh_s = float(self.config.get('autologin_no_response_mins', 2.0)) * 60.0
                            _al_interval_s = float(self.config.get('autologin_check_interval_s', 60.0))
                            _al_idle = time.time() - getattr(self, '_last_activity_ts', time.time())
                            _al_last = getattr(self, '_autologin_last_check', 0.0)
                            if (_al_idle > _al_thresh_s
                                    and time.time() - _al_last > _al_interval_s):
                                self._autologin_last_check = time.time()
                                wr = self._get_current_window_region()
                                if wr:
                                    self._autologin_running = True
                                    try:
                                        self._run_autologin_check(wr)
                                    finally:
                                        self._autologin_running = False
                    except Exception as _ale:
                        self._dbg(f'[LOGIN] periodic check err: {_ale}')

                except Exception as e:
                    self._dbg(f'OCR thread error: {e}')

                elapsed = time.time() - t0
                time.sleep(max(0.0, interval - elapsed))

        t = threading.Thread(target=_ocr_loop, daemon=True, name='ocr-thread')
        t.start()

    def _start_detection_thread(self):
        """Dedicated thread: captures + runs YOLO continuously.
        Uses a generation counter so stop+restart never leaves a zombie thread."""
        self._detection_gen = getattr(self, '_detection_gen', 0) + 1
        my_gen = self._detection_gen

        def _loop():
            from mss import mss as _mss_det
            sct = _mss_det()
            def _label(mode):
                return {'ultra_fast': 'ultra-fast 0.05-0.25ms',
                        'super_fast': 'super-fast 50-300ms',
                        'fast': 'fast 800-1200ms',
                        'lazy': 'lazy 1200-2400ms',
                        'super_lazy': 'super-lazy 10-30s'}.get(mode, 'lazy')
            print(f'[DETECT] Detection thread started gen={my_gen} '
                  f'({_label(self._speed_mode())})')
            while self.running and self._detection_gen == my_gen:
                t0 = time.time()
                # Re-evaluate per tick so a live mode-switch takes effect immediately.
                mode = self._speed_mode()
                if mode == 'ultra_fast':
                    poll_interval = random.uniform(0.00005, 0.00025)
                elif mode == 'super_fast':
                    poll_interval = random.uniform(0.05, 0.10)
                elif mode == 'fast':
                    poll_interval = random.uniform(0.80, 1.20)
                elif mode == 'super_lazy':
                    poll_interval = random.uniform(10.0, 30.0)
                else:
                    poll_interval = random.uniform(1.20, 2.40)
                try:
                    rect = win32gui.GetClientRect(self.hwnd)
                    pt = win32gui.ClientToScreen(self.hwnd, (0, 0))
                    region = {
                        'left': pt[0], 'top': pt[1],
                        'width': rect[2] - rect[0], 'height': rect[3] - rect[1],
                    }
                    screenshot = sct.grab(region)
                    # frombuffer: zero-copy view — avoids full intermediate np.array() allocation
                    frame = np.ascontiguousarray(
                        np.frombuffer(screenshot.raw, dtype=np.uint8)
                        .reshape((screenshot.height, screenshot.width, 4))[:, :, :3]
                    )
                    _now_ov = time.time()
                    if _now_ov - self._overlay_active_cache_ts > 1.0:
                        _overlay_active = (getattr(self.gui, 'overlay_mode_var', None) is not None
                                           and self.gui.overlay_mode_var.get() != 'none')
                        self._overlay_active_cache    = _overlay_active
                        self._overlay_active_cache_ts = _now_ov
                    else:
                        _overlay_active = self._overlay_active_cache
                    _yolo_t0 = time.time()
                    with self._model_lock:
                        detections, annotated = self.detector.detect_with_vis(
                            frame, region, annotate=_overlay_active)
                    _yolo_ms = (time.time() - _yolo_t0) * 1000
                    reg_tuple = (region['left'], region['top'], region['width'], region['height'])
                    self._det_buf.update(detections, frame, reg_tuple)
                    if _overlay_active:
                        self._overlay_buf.update_frame(annotated, region=reg_tuple, detections=detections)
                    # Log YOLO inference time periodically (every ~5s) so user can
                    # see whether super_fast is bottlenecked by YOLO speed.
                    if mode == 'super_fast' and _yolo_t0 - getattr(self, '_yolo_log_at', 0) > 5.0:
                        self._yolo_log_at = _yolo_t0
                        self._dbg(f'[YOLO] inference={_yolo_ms:.0f}ms (super_fast poll={poll_interval*1000:.0f}ms)')
                except Exception as e:
                    self._dbg(f'Detection thread error: {e}')
                elapsed = time.time() - t0
                sleep_t = max(0.0, poll_interval - elapsed)
                time.sleep(sleep_t)
        t = threading.Thread(target=_loop, daemon=True, name='detection-thread')
        self._detection_thread = t
        t.start()

    def start_background_only(self):
        """Multi-client slave: OCR thread only — MC loop drives YOLO + clicking."""
        if not self.find_window():
            raise Exception(f"Window '{self.config['window_title']}' not found")
        self.running = True
        self._set_action('Scanning')
        from mss import mss as _mss
        self.sct = _mss()
        # Start OCR so fatigue/inventory are read for this window.
        # Skip detection thread — master's MC loop does live YOLO for all windows.
        # Skip watchdog — MC loop updates self._watchdog_ts on master; slaves don't need it.
        self._start_ocr_thread()
        self._start_welcome_banner_thread()  # always-on: ESC dismisses login banner
        while self.running:
            self._watchdog_ts = time.time()
            time.sleep(1.0)

    def _run_multi_client_loop(self):
        """Single action loop that hops through master + all peer bot windows.
        Stays in each window until an ore is clicked (or 30s timeout), THEN hops.
        Mouse never leaves a window until the click is made."""
        from mss import mss as _mss_mc
        mc_sct = _mss_mc()
        all_bots = [self] + list(self._peer_bots)
        mc_idx = 0
        print(f'[MC] Multi-Client loop started — {len(all_bots)} windows: '
              + ', '.join(f'Bot{b.client_id+1}(hwnd={b.hwnd})' for b in all_bots))
        try:
            self.gui.log_debug(f'Multi-Client loop: {len(all_bots)} windows active')
        except Exception:
            pass

        while self.running:
            self._watchdog_ts = time.time()

            # Pause ALL bots as a group when the user is touching mouse/keyboard.
            # This lives in the outer loop so banking FSM ticks also pause.
            # Also freeze all idle/startup timers so no ::walkto fires during
            # user interaction.
            if self.config.get('pause_on_user_input', True):
                try:
                    import user_activity as _ua
                    if _ua.is_user_active(window_secs=2.0):
                        for _b in all_bots:
                            _b._set_action('Paused (user input)')
                            # Freeze idle + startup timers so walkto doesn't fire.
                            _b._last_activity_ts = time.time()
                            _b._started_at = time.time()
                        time.sleep(0.10)
                        continue
                except Exception:
                    pass

            # If every window has been sent to the bank, stop everything.
            if all(getattr(b, '_mc_walkto_done', False) for b in all_bots):
                self._stop_bot('WalkTo executed for all windows — stopping bot')
                return

            cur = all_bots[mc_idx % len(all_bots)]
            mc_idx += 1

            # Skip slaves that have been stopped (e.g. banking timeout, can't
            # path to training destination). Master stopping ends the loop via
            # the `while self.running` condition above.
            if cur is not self and not getattr(cur, 'running', True):
                time.sleep(0.02)
                continue

            if cur.paused:
                time.sleep(0.05)
                continue

            # Skip while autologin is running on this client.
            if getattr(cur, '_autologin_running', False):
                time.sleep(0.05)
                continue

            # 30s dead zone after ::walkto — let the character walk undisturbed.
            if (cur._banking_state == 'IDLE'
                    and time.time() - getattr(cur, '_walkto_sent_at', 0) < 30.0):
                time.sleep(0.05)
                continue

            # Permanently skip windows that have already been sent to the bank.
            if getattr(cur, '_mc_walkto_done', False):
                time.sleep(0.02)
                continue

            # Skip while mid-walkto or blocked (no-ore 30s timeout).
            if time.time() < getattr(cur, '_mc_skip_until', 0):
                _rem = int(cur._mc_skip_until - time.time())
                print(f'[MC] Bot{cur.client_id+1} blocked — {_rem}s remaining')
                time.sleep(0.05)
                continue

            # Validate window handle
            if not cur.hwnd or not win32gui.IsWindow(cur.hwnd):
                print(f'[MC] Bot{cur.client_id+1} hwnd={cur.hwnd} invalid — skipping')
                time.sleep(0.1)
                continue

            try:
                rect = win32gui.GetClientRect(cur.hwnd)
                pt = win32gui.ClientToScreen(cur.hwnd, (0, 0))
                win_region = {
                    'left': pt[0], 'top': pt[1],
                    'width': rect[2] - rect[0], 'height': rect[3] - rect[1],
                }
            except Exception as e:
                print(f'[MC] Bot{cur.client_id+1} region error: {e}')
                time.sleep(0.1)
                continue

            # Banking FSM hook for MC slaves: each bot has its own FSM state.
            # OCR thread on each bot sets _banking_request when its inv hits 30/30.
            if cur._banking_state != 'IDLE' or cur._banking_request:
                if cur._banking_request and cur._banking_state == 'IDLE':
                    cur._banking_request = False
                    cur._bank_begin()
                # Hold THIS bot only during the atomic loadout-click → close →
                # walkto-train-send sequence (FSM toggles _bank_atomic_active
                # right before clicking the preset and clears it after the
                # ::walkto train command is typed). All other phases (banker
                # hunt, bank-UI wait, walking back to train) yield after each
                # tick so other bots can interleave.
                _bank_hold_started = time.time()
                _BANK_HOLD_MAX_S = 15.0   # safety cap; the atomic seq is short
                while True:
                    try:
                        (_bdets, _bframe, _), _ = cur._det_buf.get()
                    except Exception:
                        _bframe = None
                    self._watchdog_ts = time.time()  # keep watchdog fresh
                    with MiningBot.MOUSE_LOCK:
                        cur._banking_tick(_bframe, win_region)
                    if not getattr(cur, '_bank_atomic_active', False):
                        break
                    if time.time() - _bank_hold_started > _BANK_HOLD_MAX_S:
                        cur._dbg(f'[BANK] atomic hold cap reached ({_BANK_HOLD_MAX_S}s) — releasing')
                        cur._bank_atomic_active = False
                        break
                continue  # let other bots act between banking ticks

            print(f'[MC] → Bot{cur.client_id+1} (hwnd={cur.hwnd})')
            cur._last_window_region = win_region
            cur._set_action(cur._scan_action_text())

            # Pre-position mouse to a fixed spot for this window on first visit
            # so the first YOLO scan covers the correct ore locations.
            _startup_fixed = cur._active_fixed_ore_spots(cur.config)
            if _startup_fixed:
                try:
                    _sf = random.choice(_startup_fixed)
                    _sfx = int(win_region['left'] + _sf[0] * win_region['width'])
                    _sfy = int(win_region['top']  + _sf[1] * win_region['height'])
                    with MiningBot.MOUSE_LOCK:
                        cur.mouse.teleport(_sfx, _sfy)
                except Exception:
                    pass

            # ── Inner loop: stay in this window until ore clicked or 30s ──────
            _win_start = time.time()
            _inner_no_ore = 0
            _did_click = False
            # Roll a fresh random quick-turn threshold for this window visit
            # so each hop feels natural and is harder to fingerprint.
            _qt_threshold = random.uniform(1.5, 3.5)

            while self.running and not _did_click:
                self._watchdog_ts = time.time()

                # Break out immediately if a bank run was requested (GUI bank
                # button) so the outer loop can start the banking FSM without
                # waiting up to 30s for this inner loop to time out.
                if cur._banking_request or cur._banking_state != 'IDLE':
                    break

                # 30-second no-ore timeout → block this window, move on.
                # Do NOT type ::walkto here — ores are just depleted and need to
                # respawn. Sending walkto would move the character away from the
                # mining spot, breaking the next ore-click cycle.
                if time.time() - _win_start > 30.0:
                    print(f'[MC] Bot{cur.client_id+1} no ore for 30s — blocking 30s')
                    cur._mc_skip_until = time.time() + 30.0
                    break

                # Live YOLO using master's warm model
                try:
                    screenshot = mc_sct.grab(win_region)
                    frame = np.ascontiguousarray(
                        np.frombuffer(screenshot.raw, dtype=np.uint8)
                        .reshape((screenshot.height, screenshot.width, 4))[:, :, :3]
                    )
                    # Resolve effective ore_checkboxes for this slave BEFORE detection
                    # so the master's detector doesn't silently discard slave-specific ores.
                    _ore_cfg = cur.config.get('ore_checkboxes', {})
                    if not any(_ore_cfg.values()):
                        _ore_cfg = self.config.get('ore_checkboxes', {})
                    _overlay_active = (getattr(self.gui, 'overlay_mode_var', None) is not None
                                       and self.gui.overlay_mode_var.get() != 'none')
                    detections, annotated = self.detector.detect_with_vis(
                        frame, win_region, ore_checkboxes=_ore_cfg, annotate=_overlay_active)
                    reg_tuple = (win_region['left'], win_region['top'],
                                 win_region['width'], win_region['height'])
                    if _overlay_active:
                        self._overlay_buf.update_frame(annotated, region=reg_tuple, detections=detections)
                    cur._det_buf.update(detections, frame, reg_tuple)
                except Exception as e:
                    print(f'[MC] YOLO error on Bot{cur.client_id+1}: {e}')
                    time.sleep(0.2)
                    continue

                mineable = [
                    d for d in detections
                    if d['class_name'] != 'empty_ore_rock'
                    and _ore_cfg.get(d['class_name'], False)
                ]

                # Fixed-spot filter — camera_rotation_enabled is a master-level
                # toggle; read from self.config so live GUI changes are respected
                # even for slave bots whose sub_cfg was snapshotted at startup.
                fixed_spots = cur._active_fixed_ore_spots(cur.config)
                if not self.config.get('camera_rotation_enabled', True) and fixed_spots:
                    fh, fw = frame.shape[:2]
                    def _near_fixed(det, _fw=fw, _fh=fh, _spots=fixed_spots):
                        bx1, by1, bx2, by2 = det['box']
                        cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
                        for rx, ry in _spots:
                            if math.sqrt((cx - rx * _fw) ** 2 + (cy - ry * _fh) ** 2) < 55:
                                return True
                        return False
                    mineable = [d for d in mineable if _near_fixed(d)]

                if not mineable:
                    _inner_no_ore += 1
                    _elapsed = int(time.time() - _win_start)
                    if _elapsed < 30:
                        cur._set_action(cur._scan_action_text(_elapsed))
                    print(f'[MC] Bot{cur.client_id+1} no ore (#{_inner_no_ore}, {_elapsed}s elapsed)')
                    # If this bot recently returned from the bank it may still
                    # be walking to the mining spot. After 5 consecutive misses
                    # inside the post-bank grace window, skip the bot and come
                    # back later so others aren't starved.
                    if (_inner_no_ore >= 5
                            and time.time() < getattr(cur, '_post_bank_idle_until', 0)):
                        _rem = int(cur._post_bank_idle_until - time.time())
                        print(f'[MC] Bot{cur.client_id+1} post-bank walk — skipping ({_rem}s grace left)')
                        cur._mc_skip_until = time.time() + 5.0  # short skip, try again soon
                        break
                    # Quick-turn on empty ores: if enabled and the bot has spent
                    # more than the configured threshold with no ore, release its
                    # turn immediately so the next client gets to go. No blocking
                    # penalty (_mc_skip_until NOT set) — the bot re-enters rotation
                    # normally and will be checked again on the next cycle.
                    # Read from master config so the live GUI toggle takes effect
                    # instantly without restarting the bot.
                    if self.config.get('quick_turn_no_ore_enabled', False):
                        if time.time() - _win_start >= _qt_threshold:
                            print(f'[MC] Bot{cur.client_id+1} quick-turn: no ore after {_qt_threshold:.2f}s — hopping')
                            cur._set_action('Waiting (empty)')
                            break
                    # Rotate camera every 3rd miss while waiting.
                    # Use self.config (master's live config) — slave sub_cfg is a
                    # frozen snapshot that doesn't reflect GUI toggle changes.
                    # Fire if EITHER rotation mode is enabled.
                    _any_rotation = (self.config.get('camera_rotation_enabled', False)
                                     or self.config.get('camera_rotate_only', False))
                    if _any_rotation and _inner_no_ore % 3 == 0:
                        print(f'[MC] Bot{cur.client_id+1} rotating camera (miss #{_inner_no_ore})')
                        with MiningBot.MOUSE_LOCK:
                            cur.bring_window_to_front()
                            cur._set_action('Rotating camera...')
                            cur.move_camera()
                        # Coal-only adaptive confidence (same as master single path):
                        # after 2 rotation passes with no coal (rotate fires every
                        # 3rd miss, so >=6 misses = 2 rotations), temporarily drop
                        # the coal-only threshold 0.75 -> 0.60. Restored below when
                        # ore is found again.
                        if _inner_no_ore >= 6:
                            try:
                                cur.detector.coal_relax = True
                            except Exception:
                                pass
                    # Sleep scales with speed mode — no need to hammer YOLO in fast/lazy.
                    _nm = cur._speed_mode()
                    time.sleep(0.00015 if _nm == 'ultra_fast' else 0.05 if _nm == 'super_fast' else 0.40 if _nm == 'fast' else 0.60)
                    continue

                # ── Ore found — click ─────────────────────────────────────────
                _inner_no_ore = 0
                # Coal reappeared — restore normal coal-only confidence (0.75).
                try:
                    cur.detector.coal_relax = False
                except Exception:
                    pass
                fh, fw = frame.shape[:2]
                # Standing-here far-ore click: powermine always, normal mode
                # only when no fixed spots (fixed spots would just snap back).
                _mc_pm = cur.config.get('powermine_enabled', False)
                _mc_fixed = bool(cur._active_fixed_ore_spots(cur.config))
                _mc_use_far = (getattr(cur, '_force_far_ore', False)
                               and (_mc_pm or not _mc_fixed))
                if _mc_use_far:
                    cur._force_far_ore = False
                    mineable.sort(key=lambda x: -cur.get_distance_from_center(x['box'], fw, fh))
                    _tag = 'PM' if _mc_pm else 'NORMAL'
                    cur._dbg(f'[STANDING-{_tag}] Bot{cur.client_id+1} targeting FARTHEST ore')
                    try:
                        cur.gui.log_debug(f'⚠ Standing-here Bot{cur.client_id+1} ({_tag}) — far ore')
                    except Exception:
                        pass
                else:
                    # PRIORITY tier first (top of ore list wins), then closest within tier.
                    _mc_priority = cur.config.get('priority_order', [])
                    mineable.sort(key=lambda x: (
                        cur._ore_priority(x['class_name'], _mc_priority),
                        cur.get_distance_from_center(x['box'], fw, fh),
                    ))
                target = mineable[0]
                tbx1, tby1, tbx2, tby2 = target['box']
                t_cx = (tbx1 + tbx2) / 2
                t_cy = (tby1 + tby2) / 2

                click_pos = cur.get_click_position(target['box'])
                screen_x = int(click_pos[0] + win_region['left'])
                screen_y = int(click_pos[1] + win_region['top'])

                # Target box in screen coords — used for post-click verification.
                _box_sx1 = int(tbx1 + win_region['left'])
                _box_sy1 = int(tby1 + win_region['top'])
                _box_sx2 = int(tbx2 + win_region['left'])
                _box_sy2 = int(tby2 + win_region['top'])

                print(f'[MC] Bot{cur.client_id+1} clicking {target["class_name"]} @ ({screen_x},{screen_y})')
                with MiningBot.MOUSE_LOCK:
                    # Re-assert focus immediately before clicking — detection can take
                    # several frames (each 0.15s), during which another window may steal
                    # focus (particularly affects the last bot in the rotation, e.g. Bot4).
                    cur.bring_window_to_front()
                    # Per-bot action update so the GUI status row shows the
                    # CURRENT activity for each bot, not master's last act.
                    cur._set_action(f'Mining {target["class_name"]}')
                    # MC mode: teleport across the window-hop so the cursor
                    # never visibly drags from the previous client to this one.
                    # Within-window curves don't apply in MC because each
                    # iteration is a different window. Click timing (pre-pause,
                    # hold) still randomized.
                    cur.mouse.teleport(screen_x, screen_y)
                    cur.mouse.click()

                    # Verify cursor landed inside the ore's bounding box.
                    _cx, _cy = win32api.GetCursorPos()
                    if not (_box_sx1 <= _cx <= _box_sx2 and _box_sy1 <= _cy <= _box_sy2):
                        print(f'[MC] Bot{cur.client_id+1} cursor missed box ({_cx},{_cy}) — forcing re-click')
                        win32api.SetCursorPos((screen_x, screen_y))
                        time.sleep(random.uniform(0.04, 0.08))
                        cur.mouse.click()

                    red_x_confirmed = not cur.config.get('click_verify_enabled', False)
                    # Red-X marker verification (toggleable in Experimental tab).
                    if (cur.config.get('click_verify_enabled', False)
                            and not cur._verify_click_marker(screen_x, screen_y, max_wait=0.40)):
                        cur._dbg(f'[VERIFY] Bot{cur.client_id+1} no red-X — re-clicking')
                        for _retry in range(2):
                            win32api.SetCursorPos((screen_x, screen_y))
                            time.sleep(random.uniform(0.04, 0.08))
                            cur.mouse.click()
                            if cur._verify_click_marker(screen_x, screen_y, max_wait=0.40):
                                red_x_confirmed = True
                                break
                        else:
                            try:
                                cur.gui.log_debug(f'⚠ Bot{cur.client_id+1} click not registering')
                            except Exception:
                                pass
                    else:
                        red_x_confirmed = True

                    cur._note_registered_click(red_x_confirmed)

                cur.last_click_time = int(time.time() * 1000)
                # Schedule a post-click fatigue OCR 0.5s from now on this client
                cur._fatigue_check_after = time.time() + 0.5
                _now_ms = cur.last_click_time
                if _now_ms - getattr(cur, '_last_mine_count_time', 0) >= 500:
                    cur._mine_count = getattr(cur, '_mine_count', 0) + 1
                    cur._last_activity_ts = time.time()
                    cur._first_click_seen = True
                    cur._last_mine_count_time = _now_ms

                _did_click = True

            # ── After clicking: pre-position mouse AND pre-scan next window ───
            if _did_click:
                try:
                    # Find the next ACTIVE (non-walked-to) bot in rotation.
                    _next_bot = None
                    for _si in range(1, len(all_bots) + 1):
                        _candidate = all_bots[(mc_idx + _si - 1) % len(all_bots)]
                        if not getattr(_candidate, '_mc_walkto_done', False) and not _candidate.paused:
                            _next_bot = _candidate
                            break
                    if _next_bot is None or _next_bot is cur:
                        _next_bot = None  # only one active window left — no hop needed

                    if _next_bot is not None and _next_bot.hwnd and win32gui.IsWindow(_next_bot.hwnd):
                        _nr = win32gui.GetClientRect(_next_bot.hwnd)
                        _np = win32gui.ClientToScreen(_next_bot.hwnd, (0, 0))
                        _nw = _nr[2] - _nr[0]
                        _nh = _nr[3] - _nr[1]
                        _next_win_region = {
                            'left': _np[0], 'top': _np[1],
                            'width': _nw, 'height': _nh,
                        }

                        # ── Pre-scan FIRST so we know where the ore is ────────
                        _ps_dets = []
                        try:
                            _ps_shot = mc_sct.grab(_next_win_region)
                            _ps_frame = np.ascontiguousarray(
                                np.frombuffer(_ps_shot.raw, dtype=np.uint8)
                                .reshape((_ps_shot.height, _ps_shot.width, 4))[:, :, :3]
                            )
                            _ps_ore_cfg = _next_bot.config.get('ore_checkboxes', {})
                            if not any(_ps_ore_cfg.values()):
                                _ps_ore_cfg = self.config.get('ore_checkboxes', {})
                            _ps_dets, _ = self.detector.detect_with_vis(
                                _ps_frame, _next_win_region, ore_checkboxes=_ps_ore_cfg, annotate=False)
                            _ps_reg = (_next_win_region['left'], _next_win_region['top'],
                                       _next_win_region['width'], _next_win_region['height'])
                            _next_bot._det_buf.update(_ps_dets, _ps_frame, _ps_reg)
                            _next_bot._last_window_region = _next_win_region
                            print(f'[MC] Pre-scan Bot{_next_bot.client_id+1}: '
                                  f'{len(_ps_dets)} detection(s)')
                        except Exception as _pse:
                            print(f'[MC] Pre-scan error: {_pse}')

                        # ── Compute pre-position target ───────────────────────
                        _direct = self.config.get('direct_ore_preposition', False)
                        _next_fixed = _next_bot._active_fixed_ore_spots(_next_bot.config)
                        _ncx, _ncy = None, None

                        if _direct and _ps_dets:
                            # Direct-to-ore: aim at the closest mineable ore found
                            _ps_ore_cfg_used = _next_bot.config.get('ore_checkboxes', {})
                            if not any(_ps_ore_cfg_used.values()):
                                _ps_ore_cfg_used = self.config.get('ore_checkboxes', {})
                            _ps_mine = [
                                d for d in _ps_dets
                                if d['class_name'] != 'empty_ore_rock'
                                and _ps_ore_cfg_used.get(d['class_name'], False)
                            ]
                            if _ps_mine:
                                _ps_mine.sort(key=lambda d: _next_bot.get_distance_from_center(
                                    d['box'], _nw, _nh))
                                _pt = _next_bot.get_click_position(_ps_mine[0]['box'])
                                _ncx = int(_pt[0] + _np[0]) + random.randint(-4, 4)
                                _ncy = int(_pt[1] + _np[1]) + random.randint(-4, 4)
                                print(f'[MC] Direct-to-ore prepos '
                                      f'Bot{_next_bot.client_id+1} → ({_ncx},{_ncy})')

                        if _ncx is None:
                            # Fallback: fixed spot or window centre ±50px
                            if _next_fixed:
                                _spot = random.choice(_next_fixed)
                                _ncx = _np[0] + int(_spot[0] * _nw) + random.randint(-20, 20)
                                _ncy = _np[1] + int(_spot[1] * _nh) + random.randint(-20, 20)
                            else:
                                _ncx = _np[0] + _nw // 2 + random.randint(-50, 50)
                                _ncy = _np[1] + _nh // 2 + random.randint(-50, 50)

                        _mmm = self.config.get('mouse_settings', {}).get('mouse_movement_mode', 'teleport')
                        with MiningBot.MOUSE_LOCK:
                            if _mmm == 'human':
                                self.mouse.move_mouse(_ncx, _ncy)
                            else:
                                cur.mouse.teleport(_ncx, _ncy)
                except Exception:
                    pass

                # WalkTo-after-N-clicks trigger REMOVED — banking mode (with 30/30
                # template + OCR) handles trips back to the bank now.

                # ── Speed-mode sleep then hop ─────────────────────────────────
                _mode = cur._speed_mode()
                # Super-fast is only meaningful when multiple clients are active;
                # with a single remaining client it would spam clicks pointlessly.
                if _mode in ('ultra_fast', 'super_fast'):
                    _active_count = sum(
                        1 for b in all_bots
                        if not getattr(b, '_mc_walkto_done', False) and not b.paused
                    )
                    if _active_count <= 1:
                        _mode = 'fast'
                if _mode == 'ultra_fast':
                    time.sleep(random.uniform(0.00005, 0.00025))
                elif _mode == 'super_fast':
                    # 50-300ms, RNG-weighted toward ~100ms (triangular, mode=100ms);
                    # long right tail keeps it from being too fast every hop.
                    time.sleep(random.triangular(0.050, 0.300, 0.100))
                elif _mode == 'fast':
                    time.sleep(random.uniform(0.80, 1.20))
                elif _mode == 'super_lazy':
                    time.sleep(random.uniform(10.0, 30.0))
                else:  # lazy
                    time.sleep(random.uniform(1.20, 2.40))

    def run(self):
        if not self.find_window():
            raise Exception(f"Window '{self.config['window_title']}' not found")

        # Start the user-input watcher thread (idempotent — safe to call per bot)
        try:
            import user_activity as _ua
            _ua.start_watcher_thread()
        except Exception as _ue:
            self._dbg(f'[USER] watcher start err: {_ue}')

        self.bring_window_to_front()
        self.running = True
        self._set_action(self._scan_action_text())
        self.last_break_time = time.time()
        print(f"Bot started! Fatigue stop threshold: {self._fatigue_stop_threshold}%")
        try:
            self.gui.log_debug(f'Bot started — fatigue stop @ {self._fatigue_stop_threshold}%')
        except Exception:
            pass

        try:
            # reset GUI counters on start
            self.gui.root.after(0, self.gui.reset_obtain_count)
            self.gui.root.after(0, lambda: self.gui.update_inventory(0, 30))
        except Exception:
            pass

        self._no_red_x_rotation_count = 0

        self._mouse_parked_outside = False

        # Lower this process to below-normal priority so the Java RSC client
        # always gets first pick of CPU/GPU time.
        try:
            import psutil
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass

        # Boost java.exe / javaw.exe (RSCRevolution client) to above-normal
        # priority so the game never lags while the bot is running inference.
        try:
            import psutil as _ps
            for _proc in _ps.process_iter(['name']):
                try:
                    if _proc.info['name'] in ('java.exe', 'javaw.exe'):
                        _proc.nice(_ps.ABOVE_NORMAL_PRIORITY_CLASS)
                except (_ps.NoSuchProcess, _ps.AccessDenied, _ps.ZombieProcess):
                    pass
        except Exception:
            pass

        # mss for OCR (inventory/fatigue reads — separate from detection thread)
        from mss import mss as _mss
        self.sct = _mss()

        self._start_watchdog()
        # In multi-client mode the MC loop runs YOLO for every window directly;
        # starting a separate detection thread for the master window would be
        # redundant and waste GPU/CPU on duplicate inference.
        if not self._peer_bots:
            self._start_detection_thread()
        self._start_ocr_thread()
        self._start_template_match_thread()
        self._start_welcome_banner_thread()  # always-on: ESC dismisses login banner

        # Brief wait so detection thread has at least one frame ready
        time.sleep(0.35)

        # Multi-client mode: master's loop cycles all windows; slaves run background only.
        if self._peer_bots:
            self._run_multi_client_loop()
            return

        action_loop_hz = 0.040  # 40ms action loop — detection thread drives YOLO at 100ms
        last_loop_time = time.time()
        _win_region_cache = None
        _win_region_last_refresh = 0.0
        _WIN_REGION_TTL = 0.5  # re-fetch window coords at most every 500ms

        while self.running:
            self._watchdog_ts = time.time()
            self._watchdog_stage = 'action-loop-hz'
            elapsed = time.time() - last_loop_time
            if elapsed < action_loop_hz:
                time.sleep(action_loop_hz - elapsed)
            last_loop_time = time.time()

            # Block action cycle while autologin is running on this client.
            if getattr(self, '_autologin_running', False):
                time.sleep(0.1)
                continue

            # 30s dead zone after any ::walkto — don't touch the window while
            # the character is still walking. Banking FSM handles its own wait;
            # this guard only fires when not in an active banking state.
            if (self._banking_state == 'IDLE'
                    and time.time() - getattr(self, '_walkto_sent_at', 0) < 30.0):
                time.sleep(0.1)
                continue

            # Per-client pause: skip work entirely until resumed.
            if self.paused:
                time.sleep(0.2)
                continue

            try:
                self._watchdog_stage = 'break-check'
                if self.should_take_break():
                    self._watchdog_stage = 'taking-break'
                    self._dbg('Taking scheduled break')
                    self.take_break()
                    self.bring_window_to_front()

                # Get current window rect for click coord translation + OCR
                # Cached to avoid win32gui overhead every 40ms when not clicking.
                self._watchdog_stage = 'win32-rect'
                _now_t = time.time()
                if (_win_region_cache is None
                        or _now_t - _win_region_last_refresh > _WIN_REGION_TTL):
                    try:
                        rect = win32gui.GetClientRect(self.hwnd)
                        pt = win32gui.ClientToScreen(self.hwnd, (0, 0))
                        _win_region_cache = {
                            'left': pt[0], 'top': pt[1],
                            'width': rect[2] - rect[0], 'height': rect[3] - rect[1],
                        }
                        _win_region_last_refresh = _now_t
                    except Exception:
                        pass
                window_region = _win_region_cache
                if window_region is None:
                    time.sleep(0.05)
                    continue
                self._last_window_region = window_region

                # Pause-on-user-input: if user has touched mouse/keyboard within
                # the last 2s (toggle-gated), idle this iteration. Doesn't break
                # banking — banking FSM also yields when this is set.
                if self.config.get('pause_on_user_input', True):
                    try:
                        import user_activity as _ua
                        if _ua.is_user_active(window_secs=2.0):
                            # Pause ALL bots simultaneously — same pattern as MC loop.
                            try:
                                _all_bots = self.gui.bots
                            except Exception:
                                _all_bots = [self]
                            for _pb in _all_bots:
                                _pb._set_action('Paused (user input)')
                                _pb._last_activity_ts = time.time()
                                _pb._started_at = time.time()
                            time.sleep(0.10)
                            continue
                    except Exception:
                        pass

                # Banking FSM: takes over the action loop when active. The OCR
                # thread sets `_banking_request = True` on inventory full.
                if self._banking_state != 'IDLE' or self._banking_request:
                    if self._banking_request and self._banking_state == 'IDLE':
                        self._banking_request = False
                        self._bank_begin()
                    try:
                        (_bdets, _bframe, _), _ = self._det_buf.get()
                    except Exception:
                        _bframe = None
                    if self._banking_tick(_bframe, window_region):
                        continue  # FSM consumed the tick
                    # Banking FSM just released control (bank run complete).
                    # Reset the no-signal timer so the 30s failsafe doesn't
                    # fire immediately after a long bank run where no ores were
                    # visible (single-client: _last_signal_time can be 2-4min
                    # stale by the time WALK_TO_TRAIN grace expires).
                    self._last_signal_time = time.time()

                # Per-tick config locals — avoids repeated dict lookups in the hot path
                _cfg_pm       = self.config.get('powermine_enabled', False)
                _cfg_hover    = self.config.get('hover_mode_enabled', False)
                _cfg_cam_rot  = self.config.get('camera_rotation_enabled', True)
                _cfg_spots    = self._active_fixed_ore_spots(self.config)
                _cfg_priority = self.config['priority_order']

                # Read latest detections from the dedicated detection thread (no YOLO here)
                self._watchdog_stage = 'read-detections'
                (detections, frame, _reg), frame_ts = self._det_buf.get()
                if frame is None:
                    time.sleep(0.05)
                    continue

                # Banking FSM tick: when active, it consumes the iteration so
                # the normal mining click-cycle is skipped.
                if not self.banking.is_idle():
                    if self.banking.tick(detections, frame):
                        time.sleep(0.05)
                        continue

                # Periodic clickback: A → pause → B at jittered intervals.
                if self.config.get('clickback_enabled', False):
                    if not hasattr(self, '_next_clickback_at'):
                        self._schedule_next_clickback()
                    elif time.time() >= self._next_clickback_at:
                        self._do_clickback()
                        self._schedule_next_clickback()

                # Gate: only act once per fresh YOLO scan AND only on frames
                # captured AFTER the most recent camera rotation finished.
                # Without the rotation check, a frame captured mid-rotation
                # passes the freshness test but holds stale geometry → misclick.
                if frame_ts <= self._last_acted_frame_ts:
                    time.sleep(0.05)
                    continue
                rot_settle = self._camera_settle_secs
                if frame_ts < (self._last_rotation_time + rot_settle):
                    # Frame predates the rotation-settle window — wait for a
                    # truly post-rotation capture before acting.
                    time.sleep(0.05)
                    continue

                # ── Round-robin gate ─────────────────────────────────────────
                # In multi-client mode only the "active" bot runs the action
                # path (click OR rotate). The others spin here at 40ms until
                # the turn is passed to them. This ensures the physical mouse
                # never interleaves between windows mid-action.
                if len(MiningBot._ACTIVE_CLIENT_IDS) > 1:
                    _my_turn = False
                    with MiningBot._TURN_LOCK:
                        _n = len(MiningBot._ACTIVE_CLIENT_IDS)
                        _cur = MiningBot._ACTIVE_CLIENT_IDS[MiningBot._TURN_IDX[0] % _n]
                        # Auto-advance a stale turn so one dead bot can't block all others
                        if _cur != self.client_id:
                            if time.time() - MiningBot._TURN_SINCE[0] > MiningBot.TURN_TIMEOUT_S:
                                MiningBot._TURN_IDX[0] = (MiningBot._TURN_IDX[0] + 1) % _n
                                MiningBot._TURN_SINCE[0] = time.time()
                                _cur = MiningBot._ACTIVE_CLIENT_IDS[MiningBot._TURN_IDX[0] % _n]
                        _my_turn = (_cur == self.client_id)
                    if not _my_turn:
                        time.sleep(0.05)
                        continue  # leave frame un-consumed so we act on it when turn arrives
                # ─────────────────────────────────────────────────────────────

                self._last_acted_frame_ts = frame_ts  # consume this scan
                self._dbg(f'Got {len(detections)} detections from buffer')
                now_sig = time.time()
                if detections:
                    self._last_signal_time = now_sig
                # Fail-safe: if no live signal (ore detection / inventory OCR /
                # fatigue OCR) for 30s, assume the game isn't logged in.
                if now_sig - self._last_signal_time > 30:
                    # Zoom out fully before stopping so the game state is visible
                    try:
                        self.bring_window_to_front()
                        time.sleep(0.5)
                        self._zoom_out()
                        time.sleep(1.0)
                    except Exception:
                        pass
                    self._stop_bot('Fail-safe: no game signal for 30s (likely logged out)',
                                   [(1400, 250), (900, 250)])
                    break
                
                # Check if last clicked ore has since depleted (only clear attempts on success).
                # We deliberately do NOT penalise "still showing" here because the ore
                # takes several seconds to deplete and would double-count with the increment
                # already applied when the click was dispatched.
                if self._last_clicked_key is not None:
                    empty_keys = set()
                    for det in detections:
                        bx1, by1, bx2, by2 = det["box"]
                        dk = (int((bx1+bx2)/2)//10, int((by1+by2)/2)//10)
                        if det["class_name"] == "empty_ore_rock":
                            empty_keys.add(dk)
                    if self._last_clicked_key in empty_keys:
                        self._click_attempts.pop(self._last_clicked_key, None)
                        self._dbg(f'[CLICK CHECK] Ore depleted at {self._last_clicked_key}')
                    self._last_clicked_key = None

                # Filter to user-selected targets (mode-aware: ores in mining,
                # NPCs in fight). The variable stays named `mineable` for
                # historical reasons — read it as "targetable".
                _targets = self._target_classes()
                mineable = []
                for det in detections:
                    cn = det["class_name"]
                    if cn == "empty_ore_rock":
                        continue
                    if cn in _targets:
                        mineable.append(det)
                
                # Fixed-spot filter: when rotation off + spots defined, only mine near those spots
                fixed_spots = self._active_fixed_ore_spots(self.config)
                if not self.config.get('camera_rotation_enabled', True) and fixed_spots:
                    frame_h, frame_w = frame.shape[:2]
                    def _near_spot(det):
                        bx1, by1, bx2, by2 = det['box']
                        cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
                        for rx, ry in fixed_spots:
                            sx, sy = rx * frame_w, ry * frame_h
                            if (cx - sx)**2 + (cy - sy)**2 < 3025:  # 55² = 3025
                                return True
                        return False
                    mineable = [d for d in mineable if _near_spot(d)]

                if mineable:
                    # Ores detected — reset no-ore counter regardless of settle state
                    self.no_ore_counter = 0

                    # Skip clicking if camera recently rotated — positions are stale
                    secs_since_rotation = time.time() - self._last_rotation_time
                    if secs_since_rotation < self._camera_settle_secs:
                        wait = self._camera_settle_secs - secs_since_rotation
                        time.sleep(wait)
                        continue  # Re-scan with fresh frame after settle
                    
                    # PRIMARY: Sort by distance from center (closest ore to character)
                    # SECONDARY: Sort by priority order (if configured)
                    priority_order = self.config["priority_order"]
                    frame_h, frame_w = frame.shape[:2]

                    # Standing-here far-ore: powermine always; normal mode only
                    # when no fixed spots are configured.
                    _sc_pm = self.config.get('powermine_enabled', False)
                    _sc_fixed = bool(self._active_fixed_ore_spots(self.config))
                    _use_far_ore = (self._force_far_ore
                                    and (_sc_pm or not _sc_fixed))
                    if _use_far_ore:
                        self._force_far_ore = False
                        mineable.sort(key=lambda x: (
                            -self.get_distance_from_center(x["box"], frame_w, frame_h),
                        ))
                        _tag = 'PM' if _sc_pm else 'NORMAL'
                        self._dbg(f'[STANDING-{_tag}] Targeting FARTHEST ore from center')
                        try:
                            self.gui.log_debug(f'⚠ Standing-here ({_tag}) — targeting farthest ore')
                        except Exception:
                            pass
                    else:
                        # Sort: PRIORITY tier first (top of list wins), then closest to center within that tier.
                        mineable.sort(key=lambda x: (
                            self._ore_priority(x["class_name"], priority_order),
                            self.get_distance_from_center(x["box"], frame_w, frame_h),
                        ))
                    
                    target = mineable[0]
                    target_distance = self.get_distance_from_center(target["box"], frame_w, frame_h)
                    try:
                        self.gui.log_debug(f"Mining: {target['class_name']} (distance: {target_distance:.1f}px from center)")
                    except Exception:
                        pass
                    bx1, by1, bx2, by2 = target["box"]
                    center = (int((bx1+bx2)/2), int((by1+by2)/2))
                    key = (center[0]//10, center[1]//10)
                    # purge expired blacklist entries
                    now = time.time()
                    for bk in list(self._blacklist.keys()):
                        if self._blacklist[bk] <= now:
                            del self._blacklist[bk]

                    # Same-spot double-click guard (always on, distinct from periodic
                    # "clickback" feature). Skips if target is within 35px of the
                    # previous click and inside the 3s cooldown window.
                    _scr_cx = center[0] + window_region['left']
                    _scr_cy = center[1] + window_region['top']
                    _cooldown_ms = 3000
                    if (not self.config.get('hover_mode_enabled', False)
                            and self._last_click_center is not None):
                        _dx = _scr_cx - self._last_click_center[0]
                        _dy = _scr_cy - self._last_click_center[1]
                        if math.sqrt(_dx*_dx + _dy*_dy) < 35:
                            _since_ms = time.time() * 1000 - self.last_click_time
                            if _since_ms < _cooldown_ms:
                                time.sleep(0.05)
                                continue

                    # In fixed-spot mode (rotation disabled + spots set), skip blacklisting
                    # entirely — there's nowhere else to go, so blacklisting deadlocks the bot.
                    # Also skip in powermine mode — the bot intentionally clicks the same ore
                    # over and over; blacklisting would cause unwanted rotations.
                    fixed_spot_mode = (not self.config.get('camera_rotation_enabled', True)
                                       and bool(fixed_spots))
                    _pm_skip_blacklist = self.config.get('powermine_enabled', False)
                    if not fixed_spot_mode and not _pm_skip_blacklist:
                        if key in self._blacklist:
                            try:
                                self.gui.log_debug('Ore blacklisted — rotating for new target')
                            except Exception:
                                pass
                            self._force_rotate()
                            time.sleep(self.config['detection_settings']['no_ore_retry_delay_ms'] / 1000.0)
                            if len(MiningBot._ACTIVE_CLIENT_IDS) > 1:
                                with MiningBot._TURN_LOCK:
                                    _n = len(MiningBot._ACTIVE_CLIENT_IDS)
                                    MiningBot._TURN_IDX[0] = (MiningBot._TURN_IDX[0] + 1) % _n
                                    MiningBot._TURN_SINCE[0] = time.time()
                            continue
                        self._click_attempts[key] = self._click_attempts.get(key, 0)
                        if self._click_attempts[key] >= 3:
                            self._blacklist[key] = now + 30.0
                            try:
                                self.gui.log_debug('Ore stuck (3 clicks) — blacklisted 30s')
                            except Exception:
                                pass
                            self._force_rotate()
                            time.sleep(self.config['detection_settings']['no_ore_retry_delay_ms'] / 1000.0)
                            if len(MiningBot._ACTIVE_CLIENT_IDS) > 1:
                                with MiningBot._TURN_LOCK:
                                    _n = len(MiningBot._ACTIVE_CLIENT_IDS)
                                    MiningBot._TURN_IDX[0] = (MiningBot._TURN_IDX[0] + 1) % _n
                                    MiningBot._TURN_SINCE[0] = time.time()
                            continue
                    
                    # Pre-click ore validity check: confirm the target hasn't
                    # depleted since the last detection cycle.
                    # If the detection-thread buffer is fresh (< 150ms old) use
                    # it directly — no extra YOLO needed. Otherwise grab a live
                    # frame and run inference under _model_lock so we don't race
                    # with the detection thread.
                    tgt_bx1, tgt_by1, tgt_bx2, tgt_by2 = target["box"]
                    tgt_cx = (tgt_bx1 + tgt_bx2) / 2
                    tgt_cy = (tgt_by1 + tgt_by2) / 2
                    (_buf_dets, _, _), _buf_ts = self._det_buf.get()
                    _buf_age = time.time() - _buf_ts
                    if _buf_age < 0.15:
                        # Buffer < 150ms old — detection thread just ran, trust it
                        _pre_dets = _buf_dets
                    else:
                        _pre_dets = []
                        try:
                            _pre_shot = self.sct.grab(window_region)
                            _pre_frame = np.ascontiguousarray(
                                np.frombuffer(_pre_shot.raw, dtype=np.uint8)
                                .reshape((_pre_shot.height, _pre_shot.width, 4))[:, :, :3]
                            )
                            with self._model_lock:
                                _pre_dets, _ = self.detector.detect_with_vis(
                                    _pre_frame, window_region, annotate=False)
                        except Exception as _pce:
                            self._dbg(f'[PRE-CLICK] Live scan error: {_pce}')
                            _pre_dets = _buf_dets
                    still_valid = False
                    _has_empty_at_target = False
                    for _d in _pre_dets:
                        _bx1, _by1, _bx2, _by2 = _d['box']
                        _dcx = (_bx1 + _bx2) / 2
                        _dcy = (_by1 + _by2) / 2
                        if abs(_dcx - tgt_cx) < 40 and abs(_dcy - tgt_cy) < 40:
                            if _d['class_name'] == 'empty_ore_rock':
                                _has_empty_at_target = True
                            else:
                                still_valid = True
                                break
                    if not still_valid:
                        _why = 'now empty_ore_rock' if _has_empty_at_target else 'gone from frame'
                        self._dbg(f'[CLICK] Target {_why} in pre-click scan — skipping')
                        try:
                            self.gui.log_debug(f'Pre-click rescan: ore {_why} — skipping')
                        except Exception:
                            pass
                        # Bump attempts so blacklist still kicks in if it keeps happening.
                        self._click_attempts[key] = self._click_attempts.get(key, 0) + 1
                        continue

                    # get click position (frame-local) and convert to screen coords
                    click_pos = self.get_click_position(target["box"])
                    click_pos = (int(click_pos[0] + window_region["left"]), int(click_pos[1] + window_region["top"]))

                    # Acquire the shared mouse lock so a second client can't interleave
                    # mid-click. Single-client = uncontested. Window focus + click
                    # must be atomic per client.
                    with MiningBot.MOUSE_LOCK:
                        self._watchdog_stage = 'bring-to-front'
                        self.bring_window_to_front()

                        self._watchdog_stage = 'mouse-move-click'
                        self._dbg(f'Clicking {target["class_name"]} at {click_pos}')
                        self.mouse_x = click_pos[0]
                        self.mouse_y = click_pos[1]

                        self._mouse_parked_outside = False
                        self.mouse.move_and_click(click_pos,
                                                   focus_cb=self.bring_window_to_front)

                        # Verify cursor landed inside the ore's bounding box.
                        _box_sx1 = int(target["box"][0] + window_region["left"])
                        _box_sy1 = int(target["box"][1] + window_region["top"])
                        _box_sx2 = int(target["box"][2] + window_region["left"])
                        _box_sy2 = int(target["box"][3] + window_region["top"])
                        _cx, _cy = win32api.GetCursorPos()
                        if not (_box_sx1 <= _cx <= _box_sx2 and _box_sy1 <= _cy <= _box_sy2):
                            self._dbg(f'Cursor missed box ({_cx},{_cy}) — forcing re-click at {click_pos}')
                            win32api.SetCursorPos((click_pos[0], click_pos[1]))
                            time.sleep(random.uniform(0.04, 0.08))
                            self.mouse.click()

                        red_x_confirmed = not self.config.get('click_verify_enabled', False)
                        # Red-X marker verification (toggleable in Experimental tab).
                        if (self.config.get('click_verify_enabled', False)
                                and not self._verify_click_marker(click_pos[0], click_pos[1], max_wait=0.40)):
                            self._dbg(f'[VERIFY] No red-X marker — re-clicking {click_pos}')
                            for _retry in range(2):
                                win32api.SetCursorPos((click_pos[0], click_pos[1]))
                                time.sleep(random.uniform(0.04, 0.08))
                                self.mouse.click()
                                if self._verify_click_marker(click_pos[0], click_pos[1], max_wait=0.40):
                                    self._dbg(f'[VERIFY] Marker confirmed on retry {_retry+1}')
                                    red_x_confirmed = True
                                    break
                            else:
                                self._dbg('[VERIFY] Marker never appeared after 2 retries')
                                try:
                                    self.gui.log_debug('⚠ Click not registering — check focus/admin')
                                except Exception:
                                    pass
                        else:
                            red_x_confirmed = True

                        self._note_registered_click(red_x_confirmed)

                        self._set_action(f'Mining {target["class_name"]}')

                    # Record the time of this click (in milliseconds since epoch)
                    self.last_click_time = int(time.time() * 1000)
                    # Schedule a post-click fatigue OCR 0.5s from now
                    self._fatigue_check_after = time.time() + 0.5
                    self._pause_env_check(5.0)  # keep baseline so terror still detectable
                    # Force-expire the region cache so the very next loop tick
                    # re-fetches fresh coords (window may have shifted during focus swap).
                    _win_region_last_refresh = 0.0

                    # ── Round-robin: pass turn to next bot right after clicking ──
                    # We advance immediately so the next bot can click during our
                    # post-click delay, maximising clicks-per-minute across all clients.
                    if len(MiningBot._ACTIVE_CLIENT_IDS) > 1:
                        with MiningBot._TURN_LOCK:
                            _n = len(MiningBot._ACTIVE_CLIENT_IDS)
                            MiningBot._TURN_IDX[0] = (MiningBot._TURN_IDX[0] + 1) % _n
                            MiningBot._TURN_SINCE[0] = time.time()

                    # Antiban: move mouse outside the game window after clicking
                    # HOVER MODE: always stays on-screen to hover next ore, so skip this
                    if (self.config.get('mouse_outside_window', False)
                            and not self.config.get('hover_mode_enabled', False)):
                        try:
                            left = window_region['left']
                            top = window_region['top']
                            w = window_region['width']
                            h = window_region['height']
                            # Park mouse on left, right, or bottom only — never top
                            edge = random.randint(0, 2)
                            offset = random.randint(5, 40)
                            if edge == 0:
                                ox, oy = left - offset, random.randint(top + int(h * 0.3), top + h)
                            elif edge == 1:
                                ox, oy = left + w + offset, random.randint(top + int(h * 0.3), top + h)
                            else:
                                ox, oy = random.randint(left + int(w * 0.1), left + int(w * 0.9)), top + h + offset
                            self.mouse.move_mouse(ox, oy)
                            self._mouse_parked_outside = True

                            if self._speed_mode() == 'fast':
                                # Fast mode: very brief pause outside then return immediately
                                time.sleep(random.uniform(0.08, 0.25))
                                rx = random.randint(left + int(w * 0.15), left + int(w * 0.85))
                                ry = random.randint(top + int(h * 0.15), top + int(h * 0.85))
                                self.mouse.move_mouse(rx, ry)
                                self._mouse_parked_outside = False
                            # Lazy / super-lazy: mouse stays outside until next ore
                        except Exception:
                            pass

                    # record attempt and stamp last clicked for next-frame verification
                    self._click_attempts[key] = self._click_attempts.get(key, 0) + 1
                    self._last_clicked_key = key
                    self._last_clicked_class = target["class_name"]
                    self._last_click_center = (_scr_cx, _scr_cy)

                    now_ms = time.time() * 1000
                    if now_ms - self._last_mine_count_time >= 500:
                        self._mine_count += 1
                        self._last_activity_ts = time.time()
                        self._first_click_seen = True
                        self._last_mine_count_time = now_ms

                    # WalkTo-after-N-clicks trigger REMOVED — banking mode (with
                    # 30/30 inventory template + OCR) handles trips back to bank.

                    self._watchdog_stage = 'post-click-sleep'
                    hover_mode = self.config.get('hover_mode_enabled', False)
                    hover_clicked = False

                    if hover_mode and self.running:
                        fixed_spots = self._active_fixed_ore_spots(self.config)
                        f_h, f_w = frame.shape[:2]

                        if fixed_spots:
                            num_spots = len(fixed_spots)
                            # Which fixed spot did we just click?
                            # Find nearest spot to click_pos (screen coords).
                            cur_idx = 0
                            _min_d = float('inf')
                            for _i, (_rx, _ry) in enumerate(fixed_spots):
                                _sx = _rx * f_w + window_region['left']
                                _sy = _ry * f_h + window_region['top']
                                _d = (click_pos[0]-_sx)**2 + (click_pos[1]-_sy)**2
                                if _d < _min_d:
                                    _min_d = _d
                                    cur_idx = _i
                            next_idx = (cur_idx + 1) % num_spots
                            rx, ry = fixed_spots[next_idx]

                            # Screen coords of next spot
                            next_sx = int(rx * f_w + window_region['left'])
                            next_sy = int(ry * f_h + window_region['top'])

                            # Try to refine aim to actual ore detection near that spot
                            (fresh_dets, _, _), _ = self._det_buf.get()
                            hx, hy = next_sx, next_sy
                            _next_ore_confirmed = False
                            for _d in fresh_dets:
                                if _d['class_name'] == 'empty_ore_rock':
                                    continue
                                if not self.config['ore_checkboxes'].get(_d['class_name'], False):
                                    continue
                                _b = _d['box']
                                _dcx = (_b[0] + _b[2]) / 2
                                _dcy = (_b[1] + _b[3]) / 2
                                if math.sqrt((_dcx + window_region['left'] - next_sx) ** 2 +
                                             (_dcy + window_region['top'] - next_sy) ** 2) < 60:
                                    _cp = self.get_click_position(_d['box'])
                                    hx = int(_cp[0] + window_region['left'])
                                    hy = int(_cp[1] + window_region['top'])
                                    _next_ore_confirmed = True
                                    break

                            try:
                                self.gui.log_debug(f'Hover {cur_idx}→{next_idx} ore_confirmed={_next_ore_confirmed}')
                            except Exception:
                                pass

                            if not _next_ore_confirmed:
                                self._dbg(f'[HOVER] no ore at spot {next_idx} — skipping click')
                            else:
                                # Move to next spot immediately
                                self.mouse.move_mouse(hx, hy)
                                self._watchdog_ts = time.time()

                                # Wait for current spot to go empty — failsafe 1400-1600ms
                                failsafe = random.uniform(1.4, 1.6)
                                transitioned = self._wait_for_ore_empty_at(
                                    float(click_pos[0]), float(click_pos[1]),
                                    window_region, max_wait=failsafe)
                                self._watchdog_ts = time.time()

                                if self.running:
                                    self._dbg(f'[HOVER] {"depleted" if transitioned else "failsafe"} → clicking spot {next_idx}')
                                    time.sleep(random.uniform(0.04, 0.10))
                                    self.mouse.click()
                                    _ht = time.time()
                                    self.last_click_time = int(_ht * 1000)
                                    self._last_click_center = (float(hx), float(hy))
                                    self._pause_env_check(5.0)
                                    _now_ms2 = _ht * 1000
                                    if _now_ms2 - self._last_mine_count_time >= 500:
                                        self._mine_count += 1
                                        self._last_mine_count_time = _now_ms2
                                        self._last_activity_ts = time.time()
                                        self._first_click_seen = True
                                    hover_clicked = True
                        else:
                            # No fixed spots — fallback: find nearest available ore
                            next_ore = self._get_hover_target(target, window_region)
                            if next_ore is not None:
                                hx, hy, h_key, h_det = next_ore
                                self.mouse.move_mouse(hx, hy)
                                self._watchdog_ts = time.time()
                                failsafe = random.uniform(1.4, 1.6)
                                transitioned = self._wait_for_ore_empty_at(
                                    float(click_pos[0]), float(click_pos[1]),
                                    window_region, max_wait=failsafe)
                                self._watchdog_ts = time.time()
                                if self.running:
                                    time.sleep(random.uniform(0.04, 0.10))
                                    self.mouse.click()
                                    _ht = time.time()
                                    self.last_click_time = int(_ht * 1000)
                                    self._last_click_center = (float(hx), float(hy))
                                    self._pause_env_check(5.0)
                                    _now_ms2 = _ht * 1000
                                    if _now_ms2 - self._last_mine_count_time >= 500:
                                        self._mine_count += 1
                                        self._last_mine_count_time = _now_ms2
                                        self._last_activity_ts = time.time()
                                        self._first_click_seen = True
                                    hover_clicked = True

                    if not hover_clicked:
                        _mode = self._speed_mode()
                        if _mode == 'ultra_fast':
                            post_delay = random.uniform(0.00005, 0.00025)
                        elif _mode == 'super_fast':
                            # 50-300ms, RNG-weighted toward ~100ms (triangular, mode=100ms);
                            # long right tail keeps it from being too fast every click.
                            post_delay = random.triangular(0.050, 0.300, 0.100)
                        elif _mode == 'fast':
                            post_delay = random.uniform(0.8, 1.2)
                        elif _mode == 'super_lazy':
                            # 1–30s, biased toward the high end (triangular with mode=25)
                            post_delay = random.triangular(1.0, 30.0, 25.0)
                        else:
                            post_delay = random.uniform(1.2, 2.4)
                        post_delay += self.get_micro_break()
                        self._watchdog_ts = time.time()
                        self._dbg(f'Post-click sleep {post_delay:.2f}s')
                        self._interruptible_sleep(post_delay)

                        # Super Lazy: random long break every 10–40 clicks
                        if _mode == 'super_lazy':
                            if self._sl_next_break_at is None:
                                self._sl_next_break_at = self._mine_count + random.randint(10, 40)
                            if self._mine_count >= self._sl_next_break_at:
                                _break_secs = random.uniform(10.0, 45.0)
                                self._dbg(f'[SUPER LAZY] Long break {_break_secs:.1f}s after {self._mine_count} clicks')
                                try:
                                    self.gui.log_debug(f'Super Lazy break: {_break_secs:.1f}s')
                                except Exception:
                                    pass
                                self._interruptible_sleep(_break_secs)
                                self._sl_next_break_at = self._mine_count + random.randint(10, 40)

                    # Lazy / super-lazy idle pause (toggle — not applicable in super_fast)
                    _mode_check = self._speed_mode()
                    if (_mode_check in ('lazy', 'super_lazy')
                            and self.config.get('lazy_idle_pause_enabled', False)
                            and not self.config.get('hover_mode_enabled', False)):
                        # Slow down further when powermine is also on — user feedback: too fast.
                        _pm = self.config.get('powermine_enabled', False)
                        _pause_lo, _pause_hi = (8, 35) if _pm else (5, 25)
                        _idle_lo, _idle_hi = (8.0, 25.0) if _pm else (5.0, 20.0)
                        if not hasattr(self, '_lazy_next_pause_at'):
                            self._lazy_next_pause_at = self._mine_count + random.randint(_pause_lo, _pause_hi)
                        if self._mine_count >= self._lazy_next_pause_at:
                            idle_secs = random.uniform(_idle_lo, _idle_hi)
                            print(f"[LAZY IDLE] Pausing {idle_secs:.1f}s (mouse outside window)")
                            try:
                                self.gui.log_debug(f'Lazy idle pause: {idle_secs:.1f}s')
                            except Exception:
                                pass
                            try:
                                rect2 = win32gui.GetClientRect(self.hwnd)
                                pt2 = win32gui.ClientToScreen(self.hwnd, (0, 0))
                                iw, ih = rect2[2], rect2[3]
                                edge2 = random.randint(0, 2)
                                off2 = random.randint(20, 60)
                                if edge2 == 0:
                                    ox = pt2[0] - off2
                                    oy = pt2[1] + random.randint(ih // 3, ih)
                                elif edge2 == 1:
                                    ox = pt2[0] + iw + off2
                                    oy = pt2[1] + random.randint(ih // 3, ih)
                                else:
                                    ox = pt2[0] + random.randint(iw // 10, iw * 9 // 10)
                                    oy = pt2[1] + ih + off2
                                self.mouse.move_mouse(ox, oy)
                            except Exception:
                                pass
                            self._interruptible_sleep(idle_secs)
                            self._lazy_next_pause_at = self._mine_count + random.randint(_pause_lo, _pause_hi)

                else:
                    rotation_enabled = (self.config.get("camera_rotation_enabled", True)
                                        or self.config.get("camera_rotate_only", False))
                    self._set_action(self._scan_action_text())

                    _did_rotate = False
                    if rotation_enabled:
                        next_pass = self._no_red_x_rotation_count + 1
                        print(f"[NO RED X] No confirmed click before rotation — pass {next_pass}/10")
                        try:
                            self.gui.log_debug(f'No red-X clicks before rotation ({next_pass}/10)')
                        except Exception:
                            pass
                        self._no_red_x_rotation_count = next_pass
                        # Coal-only adaptive confidence: after 2 empty rotation
                        # passes, temporarily relax the coal threshold (0.75 -> 0.60)
                        # so weaker coal candidates get picked up. Restored to 0.75
                        # on the next confirmed click (_note_registered_click).
                        if self._no_red_x_rotation_count >= 2:
                            try:
                                self.detector.coal_relax = True
                            except Exception:
                                pass
                        if self._no_red_x_rotation_count >= 10:
                            self._stop_bot(
                                f'No confirmed red-X clicks for 10 rotation passes — stopping Bot {self.client_id}',
                                [(1500, 200), (1200, 200), (900, 400)]
                            )
                            break
                        self._watchdog_stage = 'camera-rotate'
                        self._dbg('Rotating camera')
                        self._set_action('Rotating camera (no ore)')
                        self.move_camera()
                        # Force the next click to wait for a brand-new
                        # post-rotation frame: invalidate any in-flight frame.
                        self._last_acted_frame_ts = time.time()
                        _did_rotate = True
                    # After rotation wait up to 3.2s for detection to settle;
                    # fixed-spot mode uses the configured retry delay.
                    if _did_rotate:
                        time.sleep(random.uniform(2.8, 3.2))
                    else:
                        time.sleep(self.config['detection_settings']['no_ore_retry_delay_ms'] / 1000.0)
                    # ── Round-robin: pass turn after no-ore cycle ──────────────
                    if len(MiningBot._ACTIVE_CLIENT_IDS) > 1:
                        with MiningBot._TURN_LOCK:
                            _n = len(MiningBot._ACTIVE_CLIENT_IDS)
                            MiningBot._TURN_IDX[0] = (MiningBot._TURN_IDX[0] + 1) % _n
                            MiningBot._TURN_SINCE[0] = time.time()

                # Fast pixel checks (no OCR) — mod crown + environment change.
                # Reuse the detection-thread buffer frame (already ≤1.2s stale at
                # worst) instead of doing a redundant full sct.grab() every 2s.
                now_chk = time.time()
                if now_chk - getattr(self, '_last_chk_time', 0) >= 2.0:
                    self._last_chk_time = now_chk
                    try:
                        (_, frame_check, _), _chk_ts = self._det_buf.get()
                        if frame_check is None:
                            raise ValueError('buffer empty')

                        if (self.config.get('antiban_master_enabled', True)
                                and self.config.get('mod_crown_detection_enabled', False)):
                            if self._detect_mod_crown(frame_check):
                                # stop_all=True — moderator detected, shut down ALL clients.
                                self._stop_bot('Mod crown detected in chat',
                                               [(1800, 200), (1200, 200), (1800, 400)],
                                               stop_all=True)
                                break

                        if self._check_environment_change(frame_check):
                            msg = self._pick_teleport_reaction()
                            if msg:
                                self._dbg(f'[TELEPORT] Typing reaction: {msg}')
                                self._type_ingame_message(msg)
                            self._stop_bot('Scenery changed drastically — possible teleport',
                                           [(1500, 250), (900, 250), (1500, 500)])
                            break
                    except Exception:
                        pass

                # Fatigue % stop check REMOVED — was based on unreliable OCR.
                # Stops now come from: (a) "too tired to mine" chat OCR,
                # (b) fatigue-100% template + auto-sleep flow (if enabled).

            except Exception as e:
                print(f"Error in bot loop: {e}")
                time.sleep(1)
        
        try:
            self.gui.log_debug('Bot stopped')
        except Exception:
            pass
        print("Bot stopped!")
    
    # ── Hover Mode helpers ────────────────────────────────────────────────────

    def _ore_priority(self, class_name, priority_order=None):
        """Priority tier for an ore class — lower wins. Tiers follow
        config priority_order (addy > mithril > coal > iron > copper/tin),
        except copper_rock and tin_rock share ONE tier (both take the better
        of their two list positions) so distance decides between them."""
        if priority_order is None:
            priority_order = self.config.get('priority_order', [])
        if class_name in ('copper_rock', 'tin_rock'):
            idxs = [priority_order.index(c) for c in ('copper_rock', 'tin_rock')
                    if c in priority_order]
            return min(idxs) if idxs else 999
        return priority_order.index(class_name) if class_name in priority_order else 999

    def _get_hover_target(self, current_target, window_region):
        """Return (screen_x, screen_y, grid_key, det) for the next best mineable ore,
        excluding the ore currently being mined. Returns None if no candidate found."""
        (detections, frame, _), _ = self._det_buf.get()
        enabled_ores = self.config.get('ore_checkboxes', {})
        priority_order = self.config.get('priority_order', [])
        fixed_spots = self._active_fixed_ore_spots(self.config)
        use_fixed = (not self.config.get('camera_rotation_enabled', True) and bool(fixed_spots))

        candidates = []
        cur_bx1, cur_by1, cur_bx2, cur_by2 = current_target['box']
        cur_cx = (cur_bx1 + cur_bx2) / 2
        cur_cy = (cur_by1 + cur_by2) / 2

        if window_region is None:
            return None

        frame_w = window_region['width']
        frame_h = window_region['height']

        for det in detections:
            cn = det['class_name']
            if cn == 'empty_ore_rock':
                continue
            if not enabled_ores.get(cn, False):
                continue
            bx1, by1, bx2, by2 = det['box']
            dcx = (bx1 + bx2) / 2
            dcy = (by1 + by2) / 2
            # Skip the ore we just clicked (within 15px)
            if abs(dcx - cur_cx) < 15 and abs(dcy - cur_cy) < 15:
                continue
            # Respect fixed ore spots — only hover to ores near a configured spot
            if use_fixed:
                near = any(
                    math.sqrt((dcx - rx * frame_w) ** 2 + (dcy - ry * frame_h) ** 2) < 55
                    for rx, ry in fixed_spots
                )
                if not near:
                    continue
            grid_key = (int(dcx) // 10, int(dcy) // 10)
            if grid_key in self._blacklist and self._blacklist[grid_key] > time.time():
                continue
            dist = self.get_distance_from_center(det['box'], frame_w, frame_h)
            pri = self._ore_priority(cn, priority_order)
            candidates.append((dist, pri, det, grid_key))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[1], x[0]))  # priority first, then closest
        dist, pri, det, grid_key = candidates[0]
        click_pos = self.get_click_position(det['box'])
        sx = int(click_pos[0] + window_region['left'])
        sy = int(click_pos[1] + window_region['top'])
        return sx, sy, grid_key, det

    def _wait_for_ore_empty(self, grid_key, current_class, max_wait=12.0):
        """Poll _det_buf until the rock at grid_key is detected as empty_ore_rock.
        In RSC the depleted rock stays visible — it changes class, it doesn't
        disappear. A YOLO miss (not found at all) is NOT treated as depletion.
        Returns True once empty_ore_rock is seen 2 consecutive reads,
        False on timeout."""
        deadline = time.time() + max_wait
        consec_empty = 0
        last_frame_ts = 0.0
        while time.time() < deadline and self.running:
            self._watchdog_ts = time.time()
            (detections, _, _), frame_ts = self._det_buf.get()
            if frame_ts <= last_frame_ts:
                time.sleep(0.05)
                continue
            last_frame_ts = frame_ts

            found_empty = False
            for det in detections:
                bx1, by1, bx2, by2 = det['box']
                dcx = (bx1 + bx2) / 2
                dcy = (by1 + by2) / 2
                k = (int(dcx) // 10, int(dcy) // 10)
                if k == grid_key and det['class_name'] == 'empty_ore_rock':
                    found_empty = True
                    break

            if found_empty:
                self._dbg(f'[HOVER] Rock depleted at {grid_key}')
                return True

        return False

    def _wait_for_ore_empty_at(self, screen_x, screen_y, window_region, max_wait=1.5):
        """Hover-mode depletion check using screen coords.
        Watches for empty_ore_rock within 55px of (screen_x, screen_y).
        Returns True on the FIRST detection frame that shows empty (rock respawns
        ~0.8s after depletion — no time to wait for a second confirmation frame).
        Returns False on timeout (failsafe)."""
        deadline = time.time() + max_wait
        last_ts = 0.0
        while time.time() < deadline and self.running:
            self._watchdog_ts = time.time()
            (dets, _, _), ts = self._det_buf.get()
            if ts <= last_ts:
                time.sleep(0.04)
                continue
            last_ts = ts
            for d in dets:
                if d['class_name'] != 'empty_ore_rock':
                    continue
                bx1, by1, bx2, by2 = d['box']
                cx = (bx1 + bx2) / 2 + window_region['left']
                cy = (by1 + by2) / 2 + window_region['top']
                if (cx - screen_x)**2 + (cy - screen_y)**2 < 3025:  # 55² = 3025
                    return True
        return False

    # ─────────────────────────────────────────────────────────────────────────

    def _type_ingame_message(self, text):
        """Focus the game window and type text + Enter (for chat messages).
        Typing speed is randomized per call — 60% fast typist, 40% hunt-and-peck,
        with occasional multi-char pauses for the slow style."""
        if not text:
            return
        try:
            with MiningBot.MOUSE_LOCK:
                self.bring_window_to_front()
                time.sleep(0.12)
                # Pick a typing personality for this invocation
                _fast_typist = random.random() < 0.6
                if _fast_typist:
                    _key_lo, _key_hi = 0.012, 0.025
                    _gap_lo, _gap_hi = 0.005, 0.018
                else:
                    _key_lo, _key_hi = 0.035, 0.07
                    _gap_lo, _gap_hi = 0.012, 0.035
                _burst_count = 0
                _burst_max = random.randint(3, 6)
                for ch in text:
                    vk = win32api.VkKeyScan(ch)
                    if vk == -1:
                        continue
                    shift = (vk >> 8) & 1
                    code = vk & 0xFF
                    if shift:
                        win32api.keybd_event(0x10, 0, 0, 0)       # Shift down
                    win32api.keybd_event(code, 0, 0, 0)            # key down
                    time.sleep(random.uniform(_key_lo, _key_hi))
                    win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)
                    if shift:
                        win32api.keybd_event(0x10, 0, win32con.KEYEVENTF_KEYUP, 0)
                    _burst_count += 1
                    # Hunt-and-peck: occasional thinking pause after a few chars
                    if not _fast_typist and _burst_count >= _burst_max:
                        time.sleep(random.uniform(0.07, 0.18))
                        _burst_count = 0
                        _burst_max = random.randint(3, 6)
                    else:
                        time.sleep(random.uniform(_gap_lo, _gap_hi))
                time.sleep(0.07)
                # Enter
                win32api.keybd_event(0x0D, 0, 0, 0)
                time.sleep(0.018)
                win32api.keybd_event(0x0D, 0, win32con.KEYEVENTF_KEYUP, 0)
        except Exception as e:
            self._dbg(f'[CHAT] Type error: {e}')

    # ── Environment-change (teleport) detector ───────────────────────────────

    def _env_fingerprint(self, frame):
        """Downscale the central play area to a tiny grayscale fingerprint.
        Excludes top-left info panel and bottom chat ROI."""
        h, w = frame.shape[:2]
        y1 = int(h * 0.30)           # skip top info panel
        y2 = int(h * 0.70)           # skip bottom chat
        x1 = int(w * 0.20)           # skip left edge (inventory etc.)
        x2 = int(w * 0.95)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
        return small.astype(np.int16)

    def _pause_env_check(self, seconds=3.0, reset_baseline=False):
        """Pause the teleport detector for `seconds`.
        Pass reset_baseline=True only after camera rotations — this lets the
        detector rebuild from the new camera angle without a false positive.
        Do NOT reset after ore clicks: keeping the baseline means a terror
        teleport that happens during the click pause is still detectable."""
        self._env_pause_until = time.time() + seconds
        if reset_baseline:
            self._env_baseline = None

    def _detect_chat_text(self, frame):
        """OCR the chat area (bottom-left) and return the first user-configured
        phrase found in the text, or None. Throttled to once every 3s.
        Phrases are matched case-insensitively."""
        if not _HAVE_OCR:
            return None
        raw = self.config.get('chat_text_stop_phrases', []) or []
        phrases = [str(p).strip().lower() for p in raw if str(p).strip()]
        if not phrases:
            return None
        now = time.time()
        if now - getattr(self, '_chat_text_last_check', 0) < 3.0:
            return None
        self._chat_text_last_check = now
        try:
            global _ocr_reader
            if _ocr_reader is None:
                _ocr_reader = _make_ocr_reader()
            h, w = frame.shape[:2]
            roi = frame[int(h * 0.72):int(h * 0.98), 0:int(w * 0.55)]
            if roi.size == 0:
                return None
            text = self._chat_ocr(roi)
            if not text:
                return None
            for p in phrases:
                if p and p in text:
                    return p
        except Exception:
            pass
        return None

    def _chat_ocr(self, roi):
        """Return lowercased OCR text for the chat ROI, using a pixel-hash cache
        so that _check_standing_here and _detect_chat_text share one EasyOCR call
        when they run on the same frame (which they always do in the OCR thread)."""
        _hash = hash(roi[::3, ::3].tobytes())
        if _hash == self._chat_roi_hash:
            return self._chat_roi_text
        try:
            global _ocr_reader
            if _ocr_reader is None:
                _ocr_reader = _make_ocr_reader()
            results = _ocr_reader.readtext(roi, detail=0)
            text = ' '.join(results).lower() if results else ''
        except Exception:
            text = ''
        self._chat_roi_hash = _hash
        self._chat_roi_text = text
        return text

    def _check_standing_here(self, frame):
        """OCR the chat area for 'standing here' anti-AFK message.
        On detection: beep and log. If standing_here_far_ore_enabled, flags
        the bot to click the furthest detected ore next tick (walks character).
        Throttled to 4s between checks, 15s lockout after detection."""
        if not _HAVE_OCR:
            return False
        now = time.time()
        if now - self._standing_last_check < 4.0:
            return False
        self._standing_last_check = now
        if now - self._standing_last_detected < 15.0:
            return False
        try:
            h, w = frame.shape[:2]
            roi = frame[int(h * 0.72):int(h * 0.98), 0:int(w * 0.55)]
            if roi.size == 0:
                return False
            text = self._chat_ocr(roi)
            if 'standing' in text:
                self._standing_last_detected = now
                self._dbg('[STANDING] "standing here" detected')
                try:
                    import winsound
                    winsound.Beep(1000, 300)
                except Exception:
                    pass
                if self.config.get('standing_here_far_ore_enabled', True):
                    self._force_far_ore = True
                    self._dbg('[STANDING] flagging far-ore click to walk player')
                    try:
                        self.gui.log_debug('⚠ Standing here — clicking furthest ore to walk')
                    except Exception:
                        pass
                else:
                    try:
                        self.gui.log_debug('⚠ Standing here detected (far-ore click disabled)')
                    except Exception:
                        pass
                return True
        except Exception:
            pass
        return False

    def _detect_mod_crown(self, frame):
        """Detect mod/admin crown icons in the bottom-left chat area via
        OpenCV template matching against bundled gold/silver crown PNGs.
        Threshold = 0.75 normalized correlation. Throttled to 1.0s."""
        now = time.time()
        if now - getattr(self, '_crown_last_check', 0) < 1.0:
            return False
        self._crown_last_check = now

        # Lazy-load templates once.
        if not hasattr(self, '_crown_templates'):
            self._crown_templates = []
            tdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
            for name in ('goldcrown1.png', 'silvercrown.png'):
                p = os.path.join(tdir, name)
                if os.path.exists(p):
                    img = cv2.imread(p, cv2.IMREAD_COLOR)
                    if img is not None and img.size > 0:
                        self._crown_templates.append((name, img))
            if not self._crown_templates:
                self._dbg('[MOD-CROWN] no templates loaded; detector disabled')

        if not self._crown_templates:
            return False

        try:
            h, w = frame.shape[:2]
            roi = frame[int(h * 0.72):int(h * 0.99), 0:int(w * 0.20)]
            if roi.size == 0:
                return False
            threshold = 0.75
            for name, tpl in self._crown_templates:
                th, tw = tpl.shape[:2]
                if roi.shape[0] < th or roi.shape[1] < tw:
                    continue
                res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    self._dbg(f'[MOD-CROWN] {name} matched score={max_val:.3f}')
                    return True
        except Exception as e:
            self._dbg(f'[MOD-CROWN] detect err: {e}')
        return False

    # ── Welcome Banner ESC (always-on anti-ban) ───────────────────────────────

    def _start_welcome_banner_thread(self):
        """Always-on background thread — no config toggle required.
        Scans the game window every 1.5s for the 'Welcome to RSCRevolution2!'
        login banner.  On match, waits 200-800ms then sends ESC to dismiss it
        (prevents the banner from blocking clicks on lower z-order windows and
        looks more human than immediately clicking away).
        Throttled to once per 30s to avoid hammering ESC mid-session."""
        def _banner_loop():
            from mss import mss as _mss_wb
            sct = _mss_wb()
            _VK_ESCAPE = 0x1B
            _last_hit = 0.0
            while self.running:
                t0 = time.time()
                try:
                    region = self._last_window_region
                    if region is None:
                        time.sleep(1.5)
                        continue
                    # Throttle: don't fire again within 30s of last successful dismiss
                    if t0 - _last_hit < 30.0:
                        time.sleep(1.5)
                        continue
                    shot = sct.grab(region)
                    frame = np.ascontiguousarray(
                        np.frombuffer(shot.raw, dtype=np.uint8)
                        .reshape((shot.height, shot.width, 4))[:, :, :3]
                    )
                    # Search the top 30% of the frame — the welcome banner always
                    # appears near the top of the game viewport.
                    matched, score, _, _ = self._tm_match(
                        frame, 'welcome_rscrevolution.png',
                        threshold=0.60,
                        roi=(0.0, 0.30, 0.0, 1.0))
                    if matched:
                        _last_hit = time.time()
                        delay = random.uniform(0.200, 0.800)
                        self._dbg(f'[WELCOME] Banner detected (score={score:.2f}) — ESC in {delay:.2f}s')
                        try:
                            self.gui.log_debug(f'⚡ Welcome banner — pressing ESC in {delay:.2f}s')
                        except Exception:
                            pass
                        time.sleep(delay)
                        if self.running:
                            try:
                                self.bring_window_to_front()
                                win32api.keybd_event(_VK_ESCAPE, 0, 0, 0)
                                win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, _VK_ESCAPE, 0)
                                time.sleep(random.uniform(0.05, 0.12))
                                win32api.keybd_event(_VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)
                                win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, _VK_ESCAPE, 0)
                                self._dbg('[WELCOME] ESC sent')
                                try:
                                    self.gui.log_debug('✓ Welcome banner dismissed (ESC)')
                                except Exception:
                                    pass
                            except Exception as _ke:
                                self._dbg(f'[WELCOME] ESC send error: {_ke}')
                except Exception as e:
                    self._dbg(f'[WELCOME] thread error: {e}')
                elapsed = time.time() - t0
                time.sleep(max(0.0, 1.5 - elapsed))

        t = threading.Thread(target=_banner_loop, daemon=True, name='welcome-banner-thread')
        t.start()

    # ── Template Matching ─────────────────────────────────────────────────────

    def _tm_load(self, name):
        """Lazy-load a template image from the templates dir.
        Returns None if the file doesn't exist or can't be read.
        Successful loads are cached. None results re-check disk every 5s so a
        newly-added template gets picked up without needing a bot restart."""
        if not hasattr(self, '_tm_cache'):
            self._tm_cache = {}     # name -> ndarray
            self._tm_miss_at = {}   # name -> last-checked timestamp for misses
        if name in self._tm_cache:
            return self._tm_cache[name]
        # Miss path: re-check disk at most every 5s.
        now = time.time()
        if now - self._tm_miss_at.get(name, 0) < 5.0:
            return None
        self._tm_miss_at[name] = now
        tdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
        p = os.path.join(tdir, name)
        if not os.path.exists(p):
            self._dbg(f'[TM] template not on disk: {p}')
            return None
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is None:
            self._dbg(f'[TM] failed to read template image: {p}')
            return None
        self._tm_cache[name] = img
        print(f'[TM] loaded template {name} shape={img.shape}')
        return img

    def _tm_match(self, frame, template_name, threshold=0.75, roi=None):
        """Run cv2 template matching (TM_CCOEFF_NORMED).
        roi = (y1_frac, y2_frac, x1_frac, x2_frac) as fractions of frame size.
        Returns (matched: bool, score: float, loc: (x,y) in frame, tpl_wh: (w,h))."""
        tpl = self._tm_load(template_name)
        if tpl is None:
            return False, 0.0, (0, 0), (0, 0)
        haystack = frame
        offset_x = offset_y = 0
        if roi is not None:
            h, w = frame.shape[:2]
            y1 = int(h * roi[0]); y2 = int(h * roi[1])
            x1 = int(w * roi[2]); x2 = int(w * roi[3])
            haystack = frame[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1
        th, tw = tpl.shape[:2]
        if haystack.shape[0] < th or haystack.shape[1] < tw:
            return False, 0.0, (0, 0), (tw, th)
        try:
            res = cv2.matchTemplate(haystack, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val >= threshold:
                loc = (max_loc[0] + offset_x, max_loc[1] + offset_y)
                return True, max_val, loc, (tw, th)
        except Exception as e:
            self._dbg(f'[TM] matchTemplate error ({template_name}): {e}')
        return False, 0.0, (0, 0), (tw, th)

    def _tm_match_multiscale(self, frame, template_name, threshold=0.70,
                             roi=None, scales=(0.50, 0.66, 0.80, 1.00, 1.25, 1.50, 1.75, 2.00)):
        """Multi-scale template match. Returns best (matched, score, loc, wh).
        Necessary when DPI / window-size mismatch changed since the template
        was captured (e.g. our PER_MONITOR_AWARE_V2 fix made captures larger)."""
        tpl = self._tm_load(template_name)
        if tpl is None:
            return False, 0.0, (0, 0), (0, 0)
        haystack = frame
        offset_x = offset_y = 0
        if roi is not None:
            h, w = frame.shape[:2]
            y1 = int(h * roi[0]); y2 = int(h * roi[1])
            x1 = int(w * roi[2]); x2 = int(w * roi[3])
            haystack = frame[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1
        best_score = 0.0
        best_loc = (0, 0)
        best_wh = tpl.shape[1], tpl.shape[0]
        for s in scales:
            try:
                if abs(s - 1.0) < 0.01:
                    scaled = tpl
                else:
                    new_w = max(1, int(round(tpl.shape[1] * s)))
                    new_h = max(1, int(round(tpl.shape[0] * s)))
                    scaled = cv2.resize(tpl, (new_w, new_h),
                                         interpolation=cv2.INTER_AREA if s < 1.0 else cv2.INTER_CUBIC)
                if haystack.shape[0] < scaled.shape[0] or haystack.shape[1] < scaled.shape[1]:
                    continue
                res = cv2.matchTemplate(haystack, scaled, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val > best_score:
                    best_score = max_val
                    best_loc = (max_loc[0] + offset_x, max_loc[1] + offset_y)
                    best_wh = (scaled.shape[1], scaled.shape[0])
            except Exception:
                continue
        return (best_score >= threshold), best_score, best_loc, best_wh

    def _tm_frame_click(self, region, loc, wh):
        """Convert frame-relative (loc, wh) to screen coords and left-click the centre."""
        sx = region['left'] + loc[0] + wh[0] // 2
        sy = region['top']  + loc[1] + wh[1] // 2
        with MiningBot.MOUSE_LOCK:
            self.bring_window_to_front()
            self.mouse.move_and_click((sx, sy))

    # ── Sleeping Bag Flow ─────────────────────────────────────────────────────

    def _tm_sleeping_bag_flow(self, frame, region):
        """If fatigue >= threshold and sleeping bag visible in inventory:
        click it, OCR the random challenge word, type it, confirm sleep success."""
        if not self.config.get('tm_sleep_enabled', False):
            return
        now = time.time()
        if now - getattr(self, '_tm_sleep_cooldown', 0) < 30.0:
            return
        if getattr(self, '_tm_sleep_in_progress', False):
            return
        threshold = int(self.config.get('tm_sleep_fatigue_threshold', 90))
        fat = getattr(self, 'current_fatigue', None)
        if fat is None or fat < threshold:
            return
        # Search for sleeping bag icon in the right-side inventory area.
        _thr = float(self.config.get('tm_threshold', 0.72))
        matched, score, loc, wh = self._tm_match(
            frame, 'static_sleepingbag.png', threshold=max(0.60, _thr - 0.05),
            roi=(0.38, 1.0, 0.50, 1.0))
        if not matched:
            return

        self._tm_sleep_in_progress = True
        self._dbg(f'[TM-SLEEP] Sleeping bag found (score={score:.2f}, fat={fat}%) — initiating sleep')
        try:
            self.gui.log_debug(f'\U0001f4a4 Sleeping bag detected — fatigue {fat}% \u2265 {threshold}% — sleeping...')
        except Exception:
            pass
        try:
            # 1. Click the sleeping bag.
            self._tm_frame_click(region, loc, wh)
            time.sleep(0.9)

            # 2. Grab a fresh frame and OCR the challenge word (centre of screen).
            from mss import mss as _mss_sl
            with _mss_sl() as _sct:
                shot = _sct.grab(region)
                cf = np.ascontiguousarray(
                    np.frombuffer(shot.raw, dtype=np.uint8)
                    .reshape((shot.height, shot.width, 4))[:, :, :3])
            h, w = cf.shape[:2]
            word_roi = cf[int(h * 0.32):int(h * 0.68), int(w * 0.18):int(w * 0.82)]
            word_up = cv2.resize(word_roi, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            global _ocr_reader
            if _ocr_reader is None:
                _ocr_reader = _make_ocr_reader()
            results = _ocr_reader.readtext(word_up, detail=0)
            # Keep only alphabetic tokens of 3+ chars; pick the longest one.
            tokens = [t.strip() for t in results if len(t.strip()) >= 3 and t.strip().isalpha()]
            sleep_word = max(tokens, key=len) if tokens else ' '.join(results).strip()

            if sleep_word:
                self._dbg(f'[TM-SLEEP] Challenge word: "{sleep_word}"')
                try:
                    self.gui.log_debug(f'\U0001f4a4 Sleep challenge: "{sleep_word}"')
                except Exception:
                    pass
                # 3. Type using the existing human-like typer (includes Enter).
                self._type_ingame_message(sleep_word)
                time.sleep(1.8)

                # 4. Check for successful_sleep template.
                with _mss_sl() as _sct2:
                    shot2 = _sct2.grab(region)
                    pf = np.ascontiguousarray(
                        np.frombuffer(shot2.raw, dtype=np.uint8)
                        .reshape((shot2.height, shot2.width, 4))[:, :, :3])
                ok, ok_score, _, _ = self._tm_match(pf, 'successful_sleep.png', threshold=max(0.60, _thr - 0.07))
                if ok:
                    self._dbg(f'[TM-SLEEP] Sleep confirmed (score={ok_score:.2f})')
                    try:
                        self.gui.log_debug('\u2705 Sleep successful \u2014 fatigue reset')
                    except Exception:
                        pass
                    self.current_fatigue = 0
                    try:
                        self.gui.root.after(0, lambda: self.gui.update_live_stats(fatigue=0))
                    except Exception:
                        pass
                    self._tm_sleep_cooldown = now + 90.0
                else:
                    self._dbg('[TM-SLEEP] Success template not seen \u2014 cooldown 20s')
                    self._tm_sleep_cooldown = now + 20.0
            else:
                self._dbg('[TM-SLEEP] Could not OCR challenge word \u2014 retrying in 15s')
                self._tm_sleep_cooldown = now + 15.0
        except Exception as e:
            self._dbg(f'[TM-SLEEP] Flow error: {e}')
            self._tm_sleep_cooldown = now + 15.0
        finally:
            self._tm_sleep_in_progress = False

    # ── Auto-Close Windows ────────────────────────────────────────────────────

    def _tm_auto_close_windows(self, frame, region):
        """Detect open bank / shop / settings popups and click their close button."""
        if not self.config.get('tm_auto_close_enabled', False):
            return
        # Hard interlock: while banking FSM is active it OWNS the bank UI —
        # auto-close would prematurely shut the bank before the Mine1 click.
        if getattr(self, '_banking_state', 'IDLE') != 'IDLE':
            return
        # Also skip for a short cool-off after banking finishes, to avoid
        # racing the FSM's own close click.
        if time.time() - getattr(self, '_banking_finished_at', 0) < 5.0:
            return
        now = time.time()
        if now - getattr(self, '_tm_close_cooldown', 0) < 3.0:
            return
        _thr = float(self.config.get('tm_threshold', 0.72))
        for tname in ('close_window_bank1.png', 'close_windowshop.png',
                      'client_settings_closewindow.png'):
            matched, score, loc, wh = self._tm_match(frame, tname, threshold=_thr)
            if matched:
                self._dbg(f'[TM-CLOSE] {tname} matched (score={score:.2f}) \u2014 closing')
                try:
                    self.gui.log_debug(f'\U0001f532 Auto-close: {tname}')
                except Exception:
                    pass
                self._tm_frame_click(region, loc, wh)
                self._tm_close_cooldown = now + 3.0
                return  # one close per check

    # ── Fatigue 100% Visual ───────────────────────────────────────────────────

    def _tm_check_fatigue100(self, frame):
        """Template-based fatigue-at-100% detection. Always active.
        Searches only the top-left 30% of the frame where the fatigue bar lives.
        Requires two consecutive matches (confirm pass) before stopping."""
        now = time.time()
        if now - getattr(self, '_tm_fat100_last', 0) < 4.0:
            return
        # Top-left ROI: top 25% height, left 30% width
        _roi = (0.0, 0.25, 0.0, 0.30)
        _thr = 0.72  # first-pass threshold — broad enough to catch at different DPI
        _confirm_thr = 0.70  # confirm pass can be slightly looser
        for tname in ('fatgiue100red.png', 'fatigue100red2.png'):
            matched, score, _, _ = self._tm_match(frame, tname, threshold=_thr, roi=_roi)
            if matched:
                # Second confirmation pass — re-run immediately on same frame
                matched2, score2, _, _ = self._tm_match(frame, tname, threshold=_confirm_thr, roi=_roi)
                if not matched2:
                    self._dbg(f'[TM-FAT100] {tname} first pass {score:.2f} but confirm failed — ignoring')
                    continue
                self._tm_fat100_last = now
                self._dbg(f'[TM-FAT100] {tname} confirmed (pass1={score:.2f} pass2={score2:.2f}) — fatigue=100 → stopping')
                self.current_fatigue = 100
                try:
                    self.gui.root.after(0, lambda: self.gui.update_live_stats(fatigue=100))
                except Exception:
                    pass
                try:
                    self.gui.log_debug('🛑 Fatigue 100% (template) — stopping bot')
                except Exception:
                    pass
                self._stop_bot('Fatigue 100%', [(1000, 200), (1000, 200)])
                return

    # ── Template Match Thread ─────────────────────────────────────────────────

    def _start_template_match_thread(self):
        """Background thread: grabs a frame every ~2s and runs all enabled
        template-matching checks. Only started when template_match_enabled=True."""
        if not self.config.get('template_match_enabled', False):
            return

        def _tm_loop():
            from mss import mss as _mss_tm
            sct = _mss_tm()
            while self.running:
                t0 = time.time()
                try:
                    region = self._last_window_region
                    if region is None:
                        time.sleep(1.0)
                        continue
                    shot = sct.grab(region)
                    frame = np.ascontiguousarray(
                        np.frombuffer(shot.raw, dtype=np.uint8)
                        .reshape((shot.height, shot.width, 4))[:, :, :3])
                    self._tm_sleeping_bag_flow(frame, region)
                    self._tm_auto_close_windows(frame, region)
                    self._tm_check_fatigue100(frame)
                    self._check_login_info_screen(frame, region)
                except Exception as e:
                    self._dbg(f'[TM] thread error: {e}')
                elapsed = time.time() - t0
                time.sleep(max(0.5, 2.0 - elapsed))

        t = threading.Thread(target=_tm_loop, daemon=True, name='tm-thread')
        t.start()

    def _check_environment_change(self, frame):
        """Return True if the central scene differs drastically from baseline.
        Rebuilds baseline on every successful non-drastic check."""
        if not self.config.get('antiban_master_enabled', True):
            return False
        if not self.config.get('teleport_detection_enabled', True):
            return False
        now = time.time()
        if now < self._env_pause_until:
            # Keep baseline during click pauses so a terror teleport mid-pause
            # is still detectable. Baseline is only reset explicitly by
            # _pause_env_check(reset_baseline=True) after camera rotations.
            return False
        interval = float(self.config.get('teleport_check_interval_s', 4.0))
        if now - self._env_last_check < interval:
            return False
        self._env_last_check = now

        fp = self._env_fingerprint(frame)
        if fp is None:
            return False
        if self._env_baseline is None:
            self._env_baseline = fp
            return False

        diff = np.mean(np.abs(fp - self._env_baseline))
        threshold = float(self.config.get('teleport_threshold', 35.0))

        if diff >= threshold:
            self._env_trip_count += 1
            self._dbg(f'[ENV] Drastic change {diff:.1f} ≥ {threshold} '
                      f'(trip {self._env_trip_count}/2)')
            if self._env_trip_count >= 2:
                self._env_trip_count = 0
                return True
        else:
            self._env_trip_count = 0
            # slowly adapt baseline to natural drift
            self._env_baseline = ((self._env_baseline * 0.6) + (fp * 0.4)).astype(np.int16)
        return False

    # ─────────────────────────────────────────────────────────────────────────

    def stop(self):
        self.running = False
        # Wait for detection thread to finish so its YOLO inference doesn't
        # overlap with a new bot instance's detection thread.
        t = getattr(self, '_detection_thread', None)
        if t is not None and t.is_alive():
            try: t.join(timeout=0.8)
            except Exception: pass

    # ─────────────────────────────────────────────────────────────────────
    # Banking state machine
    # ─────────────────────────────────────────────────────────────────────
    BANK_STATE_DISPLAY = {
        'WALK_TO_BANK':      'Walking to Bank',
        'FIND_BANKER':       'Finding Banker',
        'CLICK_MINE_PRESET': 'First-Slot Preset',
        'CLOSE_BANK':        'Closing Bank',
        'WALK_TO_TRAIN':     'Walking to Training',
    }

    BANK_TIMEOUTS = {
        'WALK_TO_BANK':    180.0,   # walk + arrival template + 5-10s settle + banker click
        'FIND_BANKER':      30.0,
        'CLICK_MINE_PRESET': 45.0,  # 5-10s wait for UI + click + verification
        'CLOSE_BANK':       30.0,   # close action + deposit verification
        'WALK_TO_TRAIN':    180.0,
    }

    def _bank_enter(self, new_state, reason=''):
        # Record exit-time so the auto-close watcher cools off after banking.
        if new_state == 'IDLE' and getattr(self, '_banking_state', 'IDLE') != 'IDLE':
            self._banking_finished_at = time.time()
        # Banking transitions count as activity for the idle watchdog.
        self._last_activity_ts = time.time()
        # Any transition out of the atomic window clears the MC-hold flag —
        # protects against timeouts / errors that bypass the normal exit path.
        if new_state in ('IDLE', 'WALK_TO_TRAIN', 'WALK_TO_BANK'):
            self._bank_atomic_active = False
        self._banking_state = new_state
        self._banking_state_at = time.time()
        display = self.BANK_STATE_DISPLAY.get(new_state, new_state)
        self._set_action(f'Banking: {display}')
        self._dbg(f'[BANK] -> {new_state} {reason}')
        try:
            self.gui.log_debug(f'🏦 Banking → {display} {reason}')
        except Exception:
            pass

    def _bank_load_npc_model(self):
        """Lazy-load NPCS_TEST1.pt for banker detection. Cached on the bot."""
        if self._banker_model is not None:
            return self._banker_model
        try:
            from ultralytics import YOLO
            import torch
            path = 'NPCS_TEST1.pt'
            if not os.path.exists(path):
                self._dbg('[BANK] NPCS_TEST1.pt missing — banking cannot run')
                try: self.gui.log_debug('⚠ NPCS_TEST1.pt missing — banking aborted')
                except Exception: pass
                return None
            m = YOLO(path, verbose=False)
            m.to('cuda' if torch.cuda.is_available() else 'cpu')
            self._banker_model = m
            self._dbg(f'[BANK] NPCS_TEST1.pt loaded — classes: {m.names}')
        except Exception as e:
            self._dbg(f'[BANK] NPC model load failed: {e}')
            return None
        return self._banker_model

    def _bank_grab_frame(self, window_region):
        # mss device contexts are thread-local. self.sct was created in the
        # slave bot's OCR/detection thread, but _banking_tick runs from the MC
        # master-loop thread → "_thread._local has no attribute 'srcdc'".
        # Keep a separate mss handle per-thread keyed by thread ident.
        try:
            import threading as _th
            tid = _th.get_ident()
            cache = getattr(self, '_bank_sct_by_tid', None)
            if cache is None:
                cache = {}
                self._bank_sct_by_tid = cache
            sct = cache.get(tid)
            if sct is None:
                from mss import mss as _mss
                sct = _mss()
                cache[tid] = sct
            shot = sct.grab(window_region)
            return np.ascontiguousarray(
                np.frombuffer(shot.raw, dtype=np.uint8)
                .reshape((shot.height, shot.width, 4))[:, :, :3]
            )
        except Exception as e:
            self._dbg(f'[BANK] grab err: {e}')
            return None

    # ── Autologin ────────────────────────────────────────────────────────────

    def _get_current_window_region(self):
        """Return mss-compatible region dict for this bot's window, or None."""
        try:
            import win32gui as _wg
            l, t, r, b = _wg.GetWindowRect(self.hwnd)
            return {'left': l, 'top': t, 'width': r - l, 'height': b - t}
        except Exception:
            return None

    def _autologin_raw_click(self, window_region, loc, wh):
        """Send a left-click at template location. Caller must hold MOUSE_LOCK."""
        from mouse import (_send_mouse_flag, _MOUSEEVENTF_LEFTDOWN,
                           _MOUSEEVENTF_LEFTUP, _begin_bot_input, _end_bot_input)
        import win32api as _w32
        sx = int(window_region['left'] + loc[0] + wh[0] // 2)
        sy = int(window_region['top']  + loc[1] + wh[1] // 2)
        _w32.SetCursorPos((sx, sy))
        time.sleep(random.uniform(0.04, 0.08))
        _begin_bot_input()
        try:
            _send_mouse_flag(_MOUSEEVENTF_LEFTDOWN)
            time.sleep(random.uniform(0.06, 0.12))
            _send_mouse_flag(_MOUSEEVENTF_LEFTUP)
        finally:
            _end_bot_input()

    def _run_autologin_check(self, window_region):
        """TM-based login: click Existing_User then Loginpart2_ClickOK.
        Holds MOUSE_LOCK for the full sequence so no other bot action fires.
        Blocks until the post-login info screen is dismissed before returning."""
        threshold = 0.70
        _did_login = False
        with MiningBot.MOUSE_LOCK:
            self.bring_window_to_front()
            time.sleep(0.30)
            frame = self._bank_grab_frame(window_region)
            if frame is None:
                self._dbg('[LOGIN] frame grab returned None — skipping')
                return False
            self._dbg('[LOGIN] checking for login screen')
            matched, score, loc, wh = self._tm_match(frame, 'Existing_User.png', threshold=threshold)
            self._dbg(f'[LOGIN] Existing_User score={score:.3f} matched={matched}')
            if matched:
                self._dbg(f'[LOGIN] Existing_User found ({score:.2f}) — clicking')
                self.bring_window_to_front()
                self._autologin_raw_click(window_region, loc, wh)
                try: self.gui.log_debug('🔑 Auto-login: clicked Existing User')
                except Exception: pass
                time.sleep(random.uniform(1.2, 2.0))
                frame2 = self._bank_grab_frame(window_region)
                if frame2 is not None:
                    matched2, s2, loc2, wh2 = self._tm_match(frame2, 'Loginpart2_ClickOK.png', threshold=threshold)
                    if matched2:
                        self._dbg(f'[LOGIN] ClickOK found ({s2:.2f}) — clicking')
                        self._autologin_raw_click(window_region, loc2, wh2)
                        try: self.gui.log_debug('🔑 Auto-login: clicked OK — logged in')
                        except Exception: pass
                        time.sleep(random.uniform(0.6, 1.2))
                    else:
                        self._dbg('[LOGIN] OK button not found after Existing_User click')
                _did_login = True
            else:
                matched2, s2, loc2, wh2 = self._tm_match(frame, 'Loginpart2_ClickOK.png', threshold=threshold)
                self._dbg(f'[LOGIN] ClickOK direct score={s2:.3f} matched={matched2}')
                if matched2:
                    self._dbg(f'[LOGIN] ClickOK found directly ({s2:.2f}) — clicking')
                    self._autologin_raw_click(window_region, loc2, wh2)
                    try: self.gui.log_debug('🔑 Auto-login: clicked OK')
                    except Exception: pass
                    time.sleep(random.uniform(0.6, 1.2))
                    _did_login = True
                else:
                    self._dbg(f'[LOGIN] no login screen detected (EU={score:.3f} OK={s2:.3f})')
        if _did_login:
            self._dismiss_info_screen_after_login(window_region)
        return _did_login

    def _dismiss_info_screen_after_login(self, window_region):
        """Block until the post-login info/notice screen is dismissed or 20s elapses.
        Must complete before the bot resumes any mining or clicking actions."""
        self._dbg('[LOGIN] waiting for post-login info screen...')
        try: self.gui.log_debug('🔑 Waiting for post-login info screen...')
        except Exception: pass
        deadline = time.time() + 20.0
        dismissed = False
        while time.time() < deadline:
            time.sleep(1.5)
            frame = self._bank_grab_frame(window_region)
            if frame is None:
                continue
            matched, score, loc, wh = self._tm_match(
                frame, 'client_settings_closewindow.png', threshold=0.68)
            if not matched:
                if dismissed:
                    self._dbg('[LOGIN] info screen confirmed gone — resuming')
                    break
                continue
            dismissed = True
            self._login_info_cooldown = 0  # bypass regular throttle
            self._dbg(f'[LOGIN] post-login info screen ({score:.2f}) — dismissing')
            try: self.gui.log_debug('🔑 Dismissing post-login info screen')
            except Exception: pass
            if random.random() < 0.5:
                self._tm_frame_click(window_region, loc, wh)
            else:
                self._bank_press_esc()

    def _check_login_info_screen(self, frame, region):
        """Always-on per-client check for the post-login notice screen.
        50/50: click the close button or press ESC. Throttled to once per 10s."""
        if getattr(self, '_banking_state', 'IDLE') != 'IDLE':
            return
        now = time.time()
        if now - getattr(self, '_login_info_cooldown', 0) < 10.0:
            return
        matched, score, loc, wh = self._tm_match(
            frame, 'client_settings_closewindow.png', threshold=0.68)
        if not matched:
            return
        self._login_info_cooldown = now
        self._dbg(f'[LOGIN] info screen found ({score:.2f}) — dismissing')
        try: self.gui.log_debug('🔑 Login info screen — dismissing')
        except Exception: pass
        if random.random() < 0.5:
            self._tm_frame_click(region, loc, wh)
        else:
            self._bank_press_esc()

    # ── /Autologin ───────────────────────────────────────────────────────────

    def _bank_find_banker_box(self, window_region):
        """Capture + run NPC YOLO. Return (cx, cy) screen coords of banker, or None."""
        m = self._bank_load_npc_model()
        if m is None:
            self._dbg('[BANK] NPC model not loaded — cannot find banker')
            return None
        frame = self._bank_grab_frame(window_region)
        if frame is None:
            self._dbg('[BANK] frame grab failed — cannot find banker')
            return None
        try:
            # Strict threshold — rejects shop/guard NPCs which commonly
            # scored lower and caused clicks on the wrong character.
            results = m(frame, conf=self.config.get('bank_npc_conf', 0.76), verbose=False)
        except Exception as e:
            self._dbg(f'[BANK] inference err: {e}')
            return None
        # Among all banker detections, pick the one closest to the centre of
        # the frame — not the highest confidence. A high-conf banker in the
        # far corner is almost always a background NPC; the real teller we
        # want to click is near the middle of the screen.
        fh, fw = frame.shape[:2]
        frame_cx = fw / 2.0
        frame_cy = fh / 2.0
        best = None
        best_conf = 0.0
        best_dist = float('inf')
        all_classes = []
        for r in results:
            boxes = r.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_name = m.names[int(box.cls[0])]
                conf = float(box.conf[0])
                all_classes.append(f'{cls_name}:{conf:.2f}')
                if cls_name != 'banker':
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cx_b = (x1 + x2) / 2.0
                cy_b = (y1 + y2) / 2.0
                dist = math.sqrt((cx_b - frame_cx) ** 2 + (cy_b - frame_cy) ** 2)
                if dist < best_dist:
                    best = (x1, y1, x2, y2)
                    best_conf = conf
                    best_dist = dist
        if best is None:
            # Log everything YOLO saw so user can verify banker is actually visible.
            if all_classes:
                self._dbg(f'[BANK] no banker — YOLO saw: {", ".join(all_classes[:8])}')
            else:
                self._dbg('[BANK] no banker — YOLO saw nothing')
            return None
        cx_f = (best[0] + best[2]) / 2 + random.randint(-4, 4)
        cy_f = (best[1] + best[3]) / 2 + random.randint(-4, 4)
        sx = int(cx_f + window_region['left'])
        sy = int(cy_f + window_region['top'])
        self._dbg(f'[BANK] banker detected conf={best_conf:.2f} dist={best_dist:.0f}px → ({sx},{sy})')
        return (sx, sy)

    def _bank_slight_rotate(self):
        """Left/right arrow tap to shift camera angle while hunting for the banker.
        Uses the 70/30 favored-side bias so the sweep leans one way but still
        checks the other side."""
        self.bring_window_to_front()
        key = self._biased_lr_key()
        press_duration = random.uniform(0.30, 0.50)
        win32api.keybd_event(key, 0, 0, 0)
        try: win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, key, 0)
        except Exception: pass
        time.sleep(press_duration)
        win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
        try: win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, key, 0)
        except Exception: pass
        time.sleep(random.uniform(0.4, 0.7))  # settle after rotate before next scan

    def _bank_press_esc(self):
        try:
            _VK_ESCAPE = 0x1B
            self.bring_window_to_front()
            win32api.keybd_event(_VK_ESCAPE, 0, 0, 0)
            try: win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, _VK_ESCAPE, 0)
            except Exception: pass
            time.sleep(random.uniform(0.05, 0.12))
            win32api.keybd_event(_VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)
            try: win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, _VK_ESCAPE, 0)
            except Exception: pass
            self._dbg('[BANK] ESC sent')
            return True
        except Exception as e:
            self._dbg(f'[BANK] ESC err: {e}')
            return False

    def _bank_find_mine_preset_via_ocr(self, window_region):
        """Find the mine/Mine/mine1/Mine1 loadout button via OCR.
        Tries EasyOCR + Tesseract. Returns screen (x,y) or None.

        Match logic is fuzzy: any text whose lowercase form starts with 'mine'
        and (after stripping non-alnum) is at most 'mineN' where N is 1 digit.
        Rejects 'miner', 'mining', etc. Letter-vs-digit confusion handled
        ('mlne1', 'min e1', 'mine!' all accepted)."""
        if not _HAVE_OCR:
            return None
        global _ocr_reader
        import re
        try:
            if _ocr_reader is None:
                _ocr_reader = _make_ocr_reader()
            frame = self._bank_grab_frame(window_region)
            if frame is None:
                return None

            def _accepts(text):
                """True if text reasonably matches mine/Mine/mine1/Mine1."""
                if not text:
                    return False
                # Normalize: lowercase, replace l/I→1 for digits, strip punctuation/spaces
                norm = re.sub(r'[^\w]', '', text.lower())
                # Allow Mlne -> mine via l→i swap
                norm = norm.replace('l', 'i').replace('1', 'i') if len(norm) > 0 else norm
                # After swap, look for 'minei' (which was 'mine1') or just 'mine'
                if norm in ('mine', 'minei'):  # 'minei' = 'mine1' post-swap
                    return True
                # Original raw check (without swap) — 'mine' or 'mineN'
                raw = re.sub(r'[^\w]', '', text.lower())
                if raw == 'mine' or re.match(r'^mine\d$', raw):
                    return True
                return False

            best_bbox = None
            best_conf = 0.0
            best_src = None

            # ── Pass 1: EasyOCR on the whole frame ──────────────────────────
            try:
                results = _ocr_reader.readtext(frame, detail=1)
                self._dbg(f'[BANK] EasyOCR returned {len(results or [])} regions')
                for bbox, text, conf in results or []:
                    self._dbg(f'  [BANK-OCR] {text!r}  conf={conf:.2f}')
                    if _accepts(text) and conf > best_conf:
                        best_bbox = bbox
                        best_conf = conf
                        best_src = f'easyocr {text!r}'
            except Exception as _ee:
                self._dbg(f'[BANK] EasyOCR err: {_ee}')

            # ── Pass 2: Tesseract on upscaled grayscale ─────────────────────
            if best_bbox is None:
                try:
                    import pytesseract as _tess
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    gray_up = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    _, th_tess = cv2.threshold(gray_up, 130, 255, cv2.THRESH_BINARY)
                    cfg = r'--psm 11 -c tessedit_char_whitelist=AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz0123456789'
                    data = _tess.image_to_data(th_tess, config=cfg, output_type=_tess.Output.DICT)
                    n = len(data.get('text', []))
                    for i in range(n):
                        text = (data['text'][i] or '').strip()
                        if not text:
                            continue
                        try:
                            conf = float(data['conf'][i])
                        except Exception:
                            conf = 0.0
                        if conf < 30:
                            continue
                        if _accepts(text):
                            # Tesseract bbox is (x, y, w, h) at 2x scale → divide back.
                            x = data['left'][i] / 2.0
                            y = data['top'][i] / 2.0
                            w = data['width'][i] / 2.0
                            h = data['height'][i] / 2.0
                            bbox = [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]
                            tess_conf = conf / 100.0
                            self._dbg(f'  [BANK-TESS] {text!r}  conf={tess_conf:.2f}')
                            if tess_conf > best_conf:
                                best_bbox = bbox
                                best_conf = tess_conf
                                best_src = f'tesseract {text!r}'
                except Exception as _te:
                    self._dbg(f'[BANK] Tesseract err: {_te}')

            if best_bbox is None:
                self._dbg('[BANK] No OCR engine found mine/Mine/mine1/Mine1 label')
                return None

            xs = [p[0] for p in best_bbox]
            ys = [p[1] for p in best_bbox]
            cx_f = sum(xs) / 4.0 + random.randint(-5, 5)
            cy_f = sum(ys) / 4.0 + random.randint(-5, 5)
            sx = int(cx_f + window_region['left'])
            sy = int(cy_f + window_region['top'])
            self._dbg(f'[BANK] {best_src} conf={best_conf:.2f} → click ({sx},{sy})')
            return (sx, sy)
        except Exception as e:
            self._dbg(f'[BANK] OCR mine-preset err: {e}')
            return None

    def _bank_ui_visible(self, window_region):
        """Detect whether the bank UI panel is open. Looks for the words
        'Bank' or 'Close window' near the top of the window via EasyOCR.
        Cheap enough to run as a poll. Returns True/False."""
        if not _HAVE_OCR:
            return False
        global _ocr_reader
        try:
            if _ocr_reader is None:
                _ocr_reader = _make_ocr_reader()
            frame = self._bank_grab_frame(window_region)
            if frame is None:
                return False
            h, w = frame.shape[:2]
            # Top half of frame is enough — bank header / Close window button live there.
            top = frame[0:int(h * 0.55), :]
            results = _ocr_reader.readtext(top, detail=0)
            joined = ' '.join((r or '') for r in (results or [])).lower()
            for needle in ('bank', 'close window', 'closewindow'):
                if needle in joined:
                    self._dbg(f'[BANK] UI visible — found {needle!r} in OCR')
                    return True
            return False
        except Exception as _e:
            self._dbg(f'[BANK] UI-visible OCR err: {_e}')
            return False

    def _bank_close_via_template(self, window_region):
        """Template-match the bank's close-X button and click it."""
        frame = self._bank_grab_frame(window_region)
        if frame is None:
            return False
        matched, score, loc, wh = self._tm_match_multiscale(
            frame, 'close_window_bank1.png', threshold=0.65)
        if not matched:
            self._dbg(f'[BANK] close template not matched (best score={score:.2f})')
            return False
        sx = window_region['left'] + loc[0] + wh[0] // 2
        sy = window_region['top']  + loc[1] + wh[1] // 2
        with MiningBot.MOUSE_LOCK:
            self.bring_window_to_front()
            self.mouse.move_and_click((sx, sy))
        self._dbg(f'[BANK] clicked close-X @ ({sx},{sy})')
        return True

    def _bank_begin(self):
        """Kick off a bank run."""
        dest = self._pick_walkto_destination()
        if not dest:
            self._dbg('[BANK] no bank destination configured — aborting')
            self._banking_state = 'IDLE'
            self._stop_bot('Banking: no bank dest set', [(1200, 300)])
            return
        self._banking_attempts = 0
        self._bank_walk_arrived = False
        self._bank_first_sight_at = 0
        self._bank_settle_secs = 0
        self._bank_walk_grace_s = None  # reset walk-back grace for this run
        self._close_action_done = False
        self._bank_ui_confirmed = False
        self._mine_press_log_sec = -1
        self._inv_ocr_fail_count = 0
        self._bank_no_banker_count = 0
        self._bank_no_banker_rotations = 0
        self._bank_arrive_settle_until = 0
        self._bank_enter('WALK_TO_BANK', reason=f'dest={dest!r}')
        try:
            self._type_ingame_message(f'::walkto {dest}')
            self._walkto_sent_at = time.time()
        except Exception as e:
            self._dbg(f'[BANK] walkto type err: {e}')

    def _banking_tick(self, frame, window_region):
        """One iteration of the banking FSM. Called from main action loop.
        Returns True if FSM consumed the tick (caller skips normal mining cycle)."""
        if self._banking_state == 'IDLE':
            return False

        # Yield to user-input pause: don't take any banking action while user
        # is interacting. Banking timeout clock continues — that's intentional.
        if self.config.get('pause_on_user_input', True):
            try:
                import user_activity as _ua
                if _ua.is_user_active(window_secs=2.0):
                    if time.time() - getattr(self, '_bank_yield_log_at', 0) > 1.0:
                        self._dbg(f'[BANK] yielding ({self._banking_state}) — user input active')
                        self._bank_yield_log_at = time.time()
                    time.sleep(0.10)
                    return True
            except Exception:
                pass

        # Per-state timeout — bail out gracefully.
        elapsed = time.time() - self._banking_state_at
        timeout = self.BANK_TIMEOUTS.get(self._banking_state, 0.0)
        if timeout and elapsed > timeout:
            _timed_state = self._banking_state
            self._dbg(f'[BANK] {_timed_state} timeout after {elapsed:.1f}s — recovering to IDLE')
            try: self.gui.log_debug(f'⚠ Banking {_timed_state} timeout — resuming mining')
            except Exception: pass
            self._bank_enter('IDLE', reason='timeout')
            self._last_activity_ts = time.time()  # reset idle watchdog after recovery
            return True

        if self._banking_state == 'WALK_TO_BANK':
            # 1) Brief min-walk so we don't catch a banker NPC visible from the
            #    mining spot. 4s is enough that the player has at least left.
            if elapsed < 4.0:
                if int(elapsed) != getattr(self, '_walk_log_sec', -1):
                    self._walk_log_sec = int(elapsed)
                    self._dbg(f'[BANK] WALK_TO_BANK min-walk wait {elapsed:.1f}/4.0s')
                time.sleep(0.20)
                return True
            # 2) Look for "arrived" template OR fall back after 12s grace.
            if not getattr(self, '_bank_walk_arrived', False):
                f_arrive = self._bank_grab_frame(window_region)
                if f_arrive is not None:
                    arrived, score, _, _ = self._tm_match(
                        f_arrive, 'autowalkarrived.png', threshold=0.70)
                    if arrived:
                        self._bank_walk_arrived = True
                        self._dbg(f'[BANK] arrived template hit (score={score:.2f}) — starting banker hunt')
                if not getattr(self, '_bank_walk_arrived', False) and elapsed < 12.0:
                    if int(elapsed) != getattr(self, '_walk_log_sec', -1):
                        self._walk_log_sec = int(elapsed)
                        self._dbg(f'[BANK] waiting for arrival template… {elapsed:.1f}/12.0s')
                    time.sleep(0.30)
                    return True
                # 12s grace expired — start banker hunt anyway.
                self._bank_walk_arrived = True
                self._dbg('[BANK] arrival grace expired — starting banker hunt')
                try: self.gui.log_debug('🏦 Hunting for banker (NPCS_TEST1)')
                except Exception: pass
            # 3) Arrive-settle: wait 8-12s after arrival for player + banker to
            #    stop moving before starting YOLO scans. Misfire rate drops sharply
            #    when the character has fully stopped walking.
            if not self._bank_arrive_settle_until:
                _settle = random.uniform(3.0, 5.0)
                self._bank_arrive_settle_until = time.time() + _settle
                self._dbg(f'[BANK] arrived — settling {_settle:.1f}s before banker hunt')
                try: self.gui.log_debug(f'🏦 Arrived — settling {_settle:.0f}s')
                except Exception: pass
            if time.time() < self._bank_arrive_settle_until:
                _remain = self._bank_arrive_settle_until - time.time()
                if int(_remain) != getattr(self, '_bank_settle_log_s', -1):
                    self._bank_settle_log_s = int(_remain)
                    self._dbg(f'[BANK] settling… {_remain:.0f}s remaining')
                self._set_action(f'Banking: Settling ({_remain:.0f}s)')
                time.sleep(0.20)
                return True

            # 4) Hunt for banker — rotate camera on consecutive YOLO misses if
            #    camera rotation is enabled (skip in fixed-spot / rotate-off mode).
            #    Up to 20 rotations before giving up and recovering to IDLE.
            _no_find = getattr(self, '_bank_no_banker_count', 0)
            _rotations = getattr(self, '_bank_no_banker_rotations', 0)
            _can_rotate = (self.config.get('camera_rotation_enabled', True)
                           or self.config.get('camera_rotate_only', False))

            if _can_rotate and _rotations >= 20:
                self._dbg('[BANK] banker hunt exhausted (20 rotations, no banker) — recovering to IDLE')
                try: self.gui.log_debug('⚠ Banker not found after 20 rotations — aborting run')
                except Exception: pass
                self._bank_enter('IDLE', reason='banker hunt exhausted')
                self._last_activity_ts = time.time()
                return True

            if _no_find == 0:
                _state_str = f'Banking: Hunting banker — Scanning (Rot {_rotations}/20)'
            else:
                _state_str = f'Banking: Hunting banker — Miss {_no_find}, Rot {_rotations}/20'
            self._set_action(_state_str)
            self.bring_window_to_front()
            click = self._bank_find_banker_box(window_region)

            if click is None:
                _no_find += 1
                self._bank_no_banker_count = _no_find
                self.banker_miss_count = getattr(self, 'banker_miss_count', 0) + 1
                # Every 2 YOLO ticks with no banker → camera rotation
                if _can_rotate and _no_find % 2 == 0:
                    _rotations += 1
                    self._bank_no_banker_rotations = _rotations
                    self._dbg(f'[BANK] {_no_find} YOLO misses — rotating camera ({_rotations}/20)')
                    try: self.gui.log_debug(f'⚠ Banker not found ({_no_find} misses) — rotating {_rotations}/20')
                    except Exception: pass
                    self._bank_slight_rotate()
                time.sleep(0.20)
                return True

            self._bank_no_banker_count = 0  # found — reset miss counter

            # First-sight delay: record when we first see the banker and wait
            # 6-10s before clicking — looks human, avoids misfire on arrival.
            if not self._bank_first_sight_at:
                self._bank_first_sight_at = time.time()
                self._bank_settle_secs = random.uniform(1.0, 3.0)
                self._dbg(f'[BANK] banker first sight — waiting {self._bank_settle_secs:.1f}s before click')
                try: self.gui.log_debug(f'🏦 Banker visible — clicking in {self._bank_settle_secs:.0f}s')
                except Exception: pass

            _sight_waited = time.time() - self._bank_first_sight_at
            if _sight_waited < self._bank_settle_secs:
                _remain = self._bank_settle_secs - _sight_waited
                self._set_action(f'Banking: Banker in sight ({_remain:.0f}s)')
                time.sleep(0.20)
                return True

            self._dbg(f'[BANK] first-sight settle done — clicking banker @ {click}')
            # Banker click: zero-delay teleport + instant click. The banker can
            # walk away mid-curve, and missing once costs ~30s of retries +
            # potentially the whole bank trip. Server doesn't see local cursor
            # curves anyway — only the click event matters.
            with MiningBot.MOUSE_LOCK:
                from mouse import (_send_mouse_flag, _MOUSEEVENTF_LEFTDOWN,
                                   _MOUSEEVENTF_LEFTUP, _begin_bot_input, _end_bot_input)
                import win32api as _w32
                _w32.SetCursorPos((int(click[0]), int(click[1])))
                # No settle delay — SetCursorPos teleports instantly; SendInput
                # does not need OS cursor-settle time the way bezier moves do.
                _begin_bot_input()  # tell user-activity watcher this is bot input
                try:
                    _send_mouse_flag(_MOUSEEVENTF_LEFTDOWN)
                    time.sleep(random.uniform(0.030, 0.060))  # human-like press duration
                    _send_mouse_flag(_MOUSEEVENTF_LEFTUP)
                finally:
                    _end_bot_input()
            # Verify red-X marker so we KNOW the click registered on the banker.
            red_x_ok = False
            try:
                red_x_ok = self._verify_click_marker(click[0], click[1], max_wait=0.50)
            except Exception:
                pass
            if red_x_ok:
                self._dbg(f'[BANK] banker click VERIFIED (red-X) @ {click}')
            else:
                self._dbg(f'[BANK] banker click sent @ {click} — NO red-X')
                # Retry immediately (up to 2 times) without waiting the full 5s
                # in CLICK_MINE_PRESET — faster recovery than the existing fallback.
                self._banking_attempts += 1
                if self._banking_attempts <= 2:
                    self._dbg(f'[BANK] no red-X — retrying banker click ({self._banking_attempts}/2)')
                    try: self.gui.log_debug(f'⚠ Banker not clicked — retry {self._banking_attempts}/2')
                    except Exception: pass
                    # _bank_first_sight_at=1 is old enough that the settle check
                    # passes instantly, so next tick goes straight to fresh-detect + click.
                    self._bank_first_sight_at = 1
                    self._bank_settle_secs = 0
                    self._bank_repoll_started_at = 0
                    return True
                self._dbg('[BANK] no red-X after 2 immediate retries — checking bank UI anyway')
                try: self.gui.log_debug('⚠ Banker click unconfirmed — checking bank UI')
                except Exception: pass
            # Fixed 6-10s random wait for the bank window to fully open.
            self._mine_press_wait_secs = random.uniform(6.0, 10.0)
            self._mine_press_log_sec = -1
            self._bank_ui_confirmed = False
            self._dbg(f'[BANK] waiting {self._mine_press_wait_secs:.1f}s for bank window before Mine1 click')
            try: self.gui.log_debug(f'🏦 Banker click sent — waiting {self._mine_press_wait_secs:.1f}s for bank UI')
            except Exception: pass
            self._bank_enter('CLICK_MINE_PRESET', reason='banker clicked')
            return True

        if self._banking_state == 'CLICK_MINE_PRESET':
            # FIXED random 6-10s wait for the bank window to fully open before clicking.
            wait_secs = getattr(self, '_mine_press_wait_secs', 8.0)
            if elapsed < wait_secs:
                if int(elapsed) != getattr(self, '_mine_press_log_sec', -1):
                    self._mine_press_log_sec = int(elapsed)
                    self._dbg(f'[BANK] waiting for bank UI… {elapsed:.1f}/{wait_secs:.1f}s')
                time.sleep(0.30)
                return True

            click_pt = None

            # PRIMARY: user-saved click coordinates. Window-relative offsets
            # follow the game window if user moves it. Falls back to legacy
            # absolute coords for old configs.
            #
            # Per-slot override: if this bot has its own Mine1 slot saved AND
            # bank_mine_mimic_master is False, use the slot's coords. Master
            # (client_id 0) always uses master config.
            rel = self.config.get('bank_mine_slot_xy_rel')
            abs_xy = self.config.get('bank_mine_slot_xy')
            try:
                _slots = self.config.get('clients', [])
                if (self.client_id is not None and 0 < self.client_id < len(_slots)):
                    _slot = _slots[self.client_id] or {}
                    if not _slot.get('bank_mine_mimic_master', True):
                        _own = _slot.get('bank_mine_slot_xy_rel')
                        if _own and len(_own) == 2:
                            rel = _own
                            self._dbg(f'[BANK] Bot{self.client_id+1} using own Mine1 coords {_own}')
            except Exception:
                pass
            if rel and len(rel) == 2:
                sx = int(rel[0]) + window_region['left'] + random.randint(-7, 7)
                sy = int(rel[1]) + window_region['top']  + random.randint(-7, 7)
                click_pt = (sx, sy)
                self._dbg(f'[BANK] mine preset via SAVED REL COORDS '
                          f'rel=({rel[0]},{rel[1]}) → screen=({sx},{sy})')
            elif abs_xy and len(abs_xy) == 2:
                sx = int(abs_xy[0]) + random.randint(-7, 7)
                sy = int(abs_xy[1]) + random.randint(-7, 7)
                click_pt = (sx, sy)
                self._dbg(f'[BANK] mine preset via SAVED ABS COORDS (legacy) ({sx},{sy})')
            else:
                # FALLBACK: template match Mine1.png / loadout_mining.png.
                f2 = self._bank_grab_frame(window_region) or frame
                _best_match = None
                _best_score = 0.0
                for _tname in ('Mine1.png', 'loadout_mining.png'):
                    try:
                        tm_ok, score, loc, wh = self._tm_match_multiscale(
                            f2, _tname, threshold=0.55)
                        self._dbg(f'[BANK] template {_tname} best={score:.2f}')
                        if score > _best_score:
                            _best_score = score
                            if tm_ok:
                                _best_match = (_tname, loc, wh, score)
                    except Exception as _te:
                        self._dbg(f'[BANK] template {_tname} err: {_te}')
                if _best_match is not None:
                    _tn, loc, wh, score = _best_match
                    sx = window_region['left'] + loc[0] + wh[0] // 2 + random.randint(-7, 7)
                    sy = window_region['top']  + loc[1] + wh[1] // 2 + random.randint(-7, 7)
                    click_pt = (sx, sy)
                    self._dbg(f'[BANK] mine preset via TEMPLATE {_tn} @ ({sx},{sy}) score={score:.2f}')

            if click_pt is None:
                # If polling hasn't found Mine1 within 5s, the banker click
                # missed (or banker walked off). Re-click banker — up to 3 times.
                if elapsed > 5.0 and self._banking_attempts < 3:
                    self._banking_attempts += 1
                    self._dbg(f'[BANK] Mine1 not visible after {elapsed:.1f}s '
                              f'— retrying banker click (attempt {self._banking_attempts}/3)')
                    try: self.gui.log_debug(f'🏦 Bank UI not open — retry banker {self._banking_attempts}/3')
                    except Exception: pass
                    self._bank_walk_arrived = True  # already arrived
                    # Skip settle on retries — player is already at the banker.
                    self._bank_first_sight_at = 1   # non-zero short-circuits settle
                    self._bank_settle_secs = 0
                    self._bank_enter('WALK_TO_BANK', reason=f'retry banker {self._banking_attempts}')
                    return True
                time.sleep(0.25)  # poll every 250ms
                return True

            # Found it — click + transition. From here through CLOSE_BANK we
            # hold the MC loop so loadout-click → ESC/close → walkto-train fire
            # back-to-back without other bots interleaving (set in MC loop via
            # the _bank_atomic_active flag).
            self._bank_atomic_active = True
            sx, sy = click_pt
            with MiningBot.MOUSE_LOCK:
                self.bring_window_to_front()
                self.mouse.move_and_click((sx, sy))
            self._dbg(f'[BANK] mine preset clicked @ ({sx},{sy})')
            print(f'[BANK] preset clicked — playing sound now')
            self._play_cash_register_sound()
            time.sleep(random.uniform(0.50, 0.90))  # let deposit animate
            self._bank_enter('CLOSE_BANK', reason='preset clicked')
            return True

        if self._banking_state == 'CLOSE_BANK':
            self._dbg('[BANK] CLOSE_BANK — closing bank UI')
            # Up to 3 attempts: template-X on first try (50%), then ESC.
            # After each attempt, check close_window_bank1.png to confirm
            # the UI actually closed before proceeding to ::walkto.
            _use_template = random.random() < 0.50
            for _close_attempt in range(3):
                # Lightweight close-button TM to check if UI is still open.
                # Skip check on first attempt (we haven't tried yet).
                if _close_attempt > 0:
                    _cf = self._bank_grab_frame(window_region)
                    if _cf is not None:
                        _still_open, _sc, _, _ = self._tm_match(
                            _cf, 'close_window_bank1.png', threshold=0.58)
                        if not _still_open:
                            self._dbg(f'[BANK] bank UI closed after attempt {_close_attempt}')
                            break
                    self._dbg(f'[BANK] bank UI still open — retry close ({_close_attempt+1}/3)')
                    try: self.gui.log_debug(f'⚠ Bank still open — retry ESC {_close_attempt+1}/3')
                    except Exception: pass

                if _use_template and _close_attempt == 0:
                    ok = self._bank_close_via_template(window_region)
                    if ok:
                        self._dbg('[BANK] close via template-X')
                    else:
                        self._bank_press_esc()
                        self._dbg('[BANK] template-X miss → ESC fallback')
                else:
                    self._bank_press_esc()
                    self._dbg(f'[BANK] ESC sent (attempt {_close_attempt+1})')

                time.sleep(0.40)  # give UI time to respond before re-checking

            settle = random.uniform(0.30, 0.80)
            self._dbg(f'[BANK] post-close settle {settle:.2f}s')
            time.sleep(settle)

            train = self._pick_walkto_train_destination()
            if not train:
                train = self._pick_walkto_destination()
            self._dbg(f'[BANK] picked train dest: {train!r}')
            if not train:
                self._dbg('[BANK] no train destination — stopping')
                self._bank_enter('IDLE', reason='no train dest')
                self._stop_bot('Banking done (no train dest)', [(1000, 200)])
                return True

            try:
                self._type_ingame_message(f'::walkto {train}')
                self._walkto_sent_at = time.time()
                self._dbg(f'[BANK] typed ::walkto {train}')
                try: self.gui.log_debug(f'✓ Bank closed — ::walkto {train}')
                except Exception: pass
            except Exception as e:
                self._dbg(f'[BANK] train walkto err: {e}')

            # walkto sent — release the atomic-hold so other bots can act
            # while this one walks back asynchronously.
            self._bank_atomic_active = False
            # Successful bank: count one full inventory deposited.
            self._banks_completed += 1
            self._dbg(f'[BANK] inventories banked: {self._banks_completed}')
            self._bank_enter('WALK_TO_TRAIN', reason=f'train={train!r}')
            return True

        if self._banking_state == 'WALK_TO_TRAIN':
            elapsed = time.time() - self._banking_state_at
            # Roll a per-run walk grace once so we don't check for ores until
            # the character has had time to actually reach the training area.
            # Checking immediately risks seeing stale pre-banking detections
            # (especially in MC mode where the inner YOLO loop is paused during
            # banking), making the FSM think it arrived before it even moved.
            _walk_grace = getattr(self, '_bank_walk_grace_s', None)
            if _walk_grace is None:
                self._bank_walk_grace_s = random.uniform(40.0, 55.0)
                _walk_grace = self._bank_walk_grace_s
                self._dbg(f'[BANK] WALK_TO_TRAIN grace = {_walk_grace:.1f}s — waiting before ore check')
            if elapsed < _walk_grace:
                # Still walking — yield control so other bots can act freely.
                time.sleep(0.20)
                return True
            # Grace expired — only trust frames captured AFTER this state was
            # entered to avoid acting on stale pre-banking detections.
            try:
                (latest_dets, _, _), buf_ts = self._det_buf.get()
            except Exception:
                latest_dets = []
                buf_ts = 0.0
            if buf_ts > self._banking_state_at:
                for d in (latest_dets or []):
                    cn = (d.get('class_name') or '')
                    if cn and cn != 'empty_ore_rock' and cn.endswith('_rock'):
                        self._dbg('[BANK] ore visible — banking complete')
                        try: self.gui.log_debug('✓ Banking complete — back to mining')
                        except Exception: pass
                        self._mine_count_at_bank_done = self._mine_count
                        self._bank_at_clicks = self._roll_bank_clicks()
                        self._dbg(f'[BANK] next bank scheduled at +{self._bank_at_clicks} clicks')
                        self._bank_walk_grace_s = None  # reset for next run
                        # Give the bot a post-bank grace window so the MC loop
                        # doesn't skip it for no-ore while it's still walking back.
                        _pg = random.uniform(30.0, 75.0)
                        self._post_bank_idle_until = time.time() + _pg
                        self._dbg(f'[BANK] post-bank grace {_pg:.0f}s')
                        self._bank_enter('IDLE', reason='ore visible')
                        return False  # hand control back to the mining loop
            # Fallback: if detection buffer is still stale 10s after grace ends
            # (MC mode — inner YOLO paused during banking), assume arrival and
            # hand control back rather than blocking indefinitely.
            if elapsed > _walk_grace + 10.0:
                self._dbg('[BANK] walk grace + 10s fallback — resuming mining (arrival assumed)')
                try: self.gui.log_debug('✓ Banking done — resuming (arrival assumed)')
                except Exception: pass
                self._mine_count_at_bank_done = self._mine_count
                self._bank_at_clicks = self._roll_bank_clicks()
                self._dbg(f'[BANK] next bank scheduled at +{self._bank_at_clicks} clicks')
                self._bank_walk_grace_s = None  # reset for next run
                _pg = random.uniform(30.0, 75.0)
                self._post_bank_idle_until = time.time() + _pg
                self._dbg(f'[BANK] post-bank grace {_pg:.0f}s (fallback)')
                self._bank_enter('IDLE', reason='walk timeout')
                return False
            time.sleep(0.20)
            return True

        # Unknown state — reset.
        self._bank_enter('IDLE', reason='unknown state')
        return False
