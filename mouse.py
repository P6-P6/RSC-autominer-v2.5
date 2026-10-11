import win32api
import win32con
import time
import random
import math
import ctypes
from ctypes import wintypes

try:
    import user_activity as _ua
except Exception:
    _ua = None

def _stamp_bot_input():
    if _ua is not None:
        try: _ua.record_bot_input()
        except Exception: pass

def _begin_bot_input():
    if _ua is not None:
        try: _ua.begin_bot_input()
        except Exception: pass

def _end_bot_input():
    if _ua is not None:
        try: _ua.end_bot_input()
        except Exception: pass

# SendInput structures — modern, reliable input injection (mouse_event is legacy)
_PUL = ctypes.POINTER(ctypes.c_ulong)

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _PUL)]

class _INPUT_I(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]

class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ii", _INPUT_I)]

_INPUT_MOUSE = 0
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004

def _send_mouse_flag(flag):
    extra = ctypes.c_ulong(0)
    ii = _INPUT_I()
    ii.mi = _MOUSEINPUT(0, 0, 0, flag, 0, ctypes.pointer(extra))
    inp = _INPUT(_INPUT_MOUSE, ii)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

class HumanMouse:
    def __init__(self, settings):
        self.settings = settings
        self.min_delay = settings["min_delay_ms"] / 1000.0
        self.max_delay = settings["max_delay_ms"] / 1000.0
        self.curve_strength = settings["human_curve_strength"]
        # When True: skip bezier/overshoot/hesitation in move_mouse and just
        # teleport to the target. Click timing (pre-click pause + hold) is
        # unaffected — those stay randomized so individual clicks still vary.
        self.instant_movement = bool(settings.get("instant_movement", False))
        self._apply_profile(settings.get("mouse_seed", None))

    def _apply_profile(self, seed=None):
        """Generate a randomized mouse personality from a seed."""
        rng = random.Random(seed)  # seeded RNG — reproducible per session
        # Overshoot: how far past the target the mouse goes (5–30%)
        self.overshoot_min = rng.uniform(1.03, 1.10)
        self.overshoot_max = rng.uniform(1.12, 1.30)
        # Speed: step size divisor (smaller = more steps = slower)
        self.step_divisor = rng.uniform(7, 14)
        # Jitter: probability and magnitude of mid-movement wobble
        self.jitter_prob = rng.uniform(0.15, 0.45)
        self.jitter_mag = rng.uniform(1.0, 3.5)
        # Hesitation: pause probability mid-movement
        self.hesitation_prob = rng.uniform(0.05, 0.25)
        # Correction: steps to snap back from overshoot
        self.correction_min = rng.randint(2, 5)
        self.correction_max = rng.randint(6, 12)
        # Click hold duration range
        self.click_hold_min = rng.uniform(0.04, 0.08)
        self.click_hold_max = rng.uniform(0.09, 0.18)
        # Post-target hesitation before click
        self.pre_click_pause_min = rng.uniform(0.03, 0.06)
        self.pre_click_pause_max = rng.uniform(0.07, 0.15)
    
    def move_mouse(self, target_x, target_y):
        """
        Move mouse with realistic human behavior:
        - Overshoots target then corrects
        - Small jerky movements
        - Non-linear acceleration
        - Random pauses and hesitations
        """
        _begin_bot_input()
        try:
            return self._move_mouse_impl(target_x, target_y)
        finally:
            _end_bot_input()

    def _move_mouse_impl(self, target_x, target_y):
        if self.instant_movement:
            # Direct teleport — no curve, no overshoot, no hesitation.
            win32api.SetCursorPos((int(target_x), int(target_y)))
            _stamp_bot_input()
            return
        current_x, current_y = win32api.GetCursorPos()
        dx = target_x - current_x
        dy = target_y - current_y
        distance = math.sqrt(dx*dx + dy*dy)
        if distance < 1:
            return

        # Phase 1: Bezier curve toward overshoot point
        overshoot_factor = random.uniform(self.overshoot_min, self.overshoot_max)
        overshoot_x = target_x + dx * (overshoot_factor - 1)
        overshoot_y = target_y + dy * (overshoot_factor - 1)
        inv_dist = 1.0 / max(distance, 1)
        drift = random.uniform(-0.25, 0.25) * distance * self.curve_strength
        ctrl_x = current_x + dx * 0.5 + (-dy * inv_dist) * drift
        ctrl_y = current_y + dy * 0.5 + ( dx * inv_dist) * drift
        steps = max(int(distance / self.step_divisor), 5)

        # Pre-compute all path points and per-step randoms before the hot loop.
        # Same distributions as before — just avoids per-step attribute lookups,
        # Bezier math, and random calls inside the timed sleep loop.
        _inv  = 1.0 / max(steps - 1, 1)
        _jp, _jm, _hp = self.jitter_prob, self.jitter_mag, self.hesitation_prob
        path = []
        for i in range(steps):
            t  = i * _inv
            te = self._ease_in_out_cubic(t)
            tm = 1.0 - te
            bx = tm*tm*current_x + 2.0*tm*te*ctrl_x + te*te*overshoot_x
            by = tm*tm*current_y + 2.0*tm*te*ctrl_y + te*te*overshoot_y
            nx = random.uniform(-_jm, _jm) if random.random() < _jp else 0.0
            ny = random.uniform(-_jm, _jm) if random.random() < _jp else 0.0
            slp = (random.uniform(0.002, 0.006) if (t < 0.2 or t > 0.8)
                   else random.uniform(0.0005, 0.003))
            path.append((int(bx + nx), int(by + ny), slp, random.random() < _hp))

        # Execute phase 1 — skip SetCursorPos when consecutive points land on the
        # same integer pixel (common at eased start/end); still sleep as normal.
        prev_px = prev_py = None
        for px, py, slp, hes in path:
            if hes:
                time.sleep(random.uniform(0.01, 0.03))
            if px != prev_px or py != prev_py:
                win32api.SetCursorPos((px, py))
                prev_px, prev_py = px, py
            time.sleep(slp)

        # Phase 2: land on overshoot, brief pause
        win32api.SetCursorPos((int(overshoot_x), int(overshoot_y)))
        time.sleep(random.uniform(0.04, 0.12))

        # Phase 3: correction back to target — pre-compute to keep loop lean
        correction_steps = random.randint(self.correction_min, self.correction_max)
        _inv3 = 1.0 / max(correction_steps - 1, 1)
        ox, oy = overshoot_x, overshoot_y
        dtx, dty = target_x - ox, target_y - oy
        corr = []
        for i in range(correction_steps):
            t = i * _inv3
            corr.append((
                int(ox + dtx*t + random.uniform(-0.8, 0.8)),
                int(oy + dty*t + random.uniform(-0.8, 0.8)),
                random.uniform(0.003, 0.009),
            ))
        prev_cx = prev_cy = None
        for cx, cy, slp in corr:
            if cx != prev_cx or cy != prev_cy:
                win32api.SetCursorPos((cx, cy))
                prev_cx, prev_cy = cx, cy
            time.sleep(slp)

        # Final position — land exactly on target
        win32api.SetCursorPos((int(target_x), int(target_y)))
        _stamp_bot_input()
        time.sleep(random.uniform(0.04, 0.11))
    
    @staticmethod
    def _ease_in_out_cubic(t):
        """Smooth easing function for more natural acceleration"""
        if t < 0.5:
            return 4 * t * t * t
        else:
            return 1 - pow(-2 * t + 2, 3) / 2
    
    def click(self):
        """Human-like click with realistic timing"""
        _begin_bot_input()
        try:
            return self._click_impl()
        finally:
            _end_bot_input()

    def _click_impl(self):
        # Small random jitter before click (aiming)
        current_x, current_y = win32api.GetCursorPos()
        jitter_x = current_x + random.randint(-1, 1)
        jitter_y = current_y + random.randint(-1, 1)
        win32api.SetCursorPos((jitter_x, jitter_y))
        
        # Slight pause before pressing
        time.sleep(random.uniform(self.pre_click_pause_min, self.pre_click_pause_max))

        # Mouse down, brief tap hold, then up
        _send_mouse_flag(_MOUSEEVENTF_LEFTDOWN)
        time.sleep(random.uniform(0.015, 0.050))
        _send_mouse_flag(_MOUSEEVENTF_LEFTUP)
        _stamp_bot_input()
    
    def teleport(self, target_x, target_y):
        """Instantly warp the cursor to a position — no movement animation."""
        win32api.SetCursorPos((int(target_x), int(target_y)))

    def move_and_click(self, target_pos, focus_cb=None):
        """Move to target and click with human-like behavior and post-click wait.
        focus_cb: optional callable invoked between move and click to re-assert window focus."""
        self.move_mouse(target_pos[0], target_pos[1])
        if focus_cb:
            try: focus_cb()
            except Exception: pass
        self.click()
        post_click_delay = random.uniform(0.15, 0.5)
        time.sleep(post_click_delay)