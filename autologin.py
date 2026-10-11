"""
autologin.py — RSC Auto-Login module (no GUI, no standalone App class).
Import RSCBot and helpers from here; the GUI lives in main.py.
"""

import sys
import time
import threading
import random
import logging

# ── Optional dependency imports (graceful degradation) ───────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE    = 0.1
    _HAS_PYAUTOGUI = True
except ImportError:
    pyautogui = None
    _HAS_PYAUTOGUI = False

try:
    import pytesseract
    _HAS_TESSERACT = True
except ImportError:
    pytesseract = None
    _HAS_TESSERACT = False

try:
    from PIL import ImageGrab, Image
    _HAS_PIL = True
except ImportError:
    ImageGrab = None
    Image = None
    _HAS_PIL = False

try:
    import keyboard
    _HAS_KEYBOARD = True
except ImportError:
    keyboard = None
    _HAS_KEYBOARD = False

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    psutil = None
    _HAS_PSUTIL = False

try:
    import win32gui
    import win32process
    WINDOWS = True
except ImportError:
    win32gui = None
    win32process = None
    WINDOWS = False

# ── Constants ─────────────────────────────────────────────────────────────────
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if _HAS_TESSERACT and pytesseract is not None:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

WINDOW_TITLES = ["RSCRevolution", "RSCRevolution2"]
PROC_NAMES    = ["java.exe", "javaw.exe"]
AFK_PHRASES   = ["you have been standing", "standing here for",
                 "been standing", "walk around"]
LOGIN_HINTS   = {
    "existing_user": (0.50, 0.45),
    "ok_button":     (0.50, 0.65),
}

log = logging.getLogger("RSCBot")

# ── Helper functions ──────────────────────────────────────────────────────────

def find_game_window():
    """Return (hwnd, rect) for the first visible RSC window, or None."""
    if not WINDOWS:
        return None
    if not _HAS_PSUTIL:
        return None
    result = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not any(t.lower() in title.lower() for t in WINDOW_TITLES):
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if psutil.Process(pid).name().lower() not in PROC_NAMES:
                return
        except Exception:
            return
        result.append((hwnd, win32gui.GetWindowRect(hwnd)))

    win32gui.EnumWindows(_cb, None)
    return result[0] if result else None


def bring_to_front(hwnd):
    """Bring the given window to the foreground."""
    try:
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.25)
    except Exception:
        pass


def grab_window(rect):
    """Screenshot the region defined by rect (l, t, r, b)."""
    if not _HAS_PIL:
        return None
    return ImageGrab.grab(bbox=rect)


def ocr_region(img, box_rel, rect):
    """
    OCR a relative sub-region of *img*.
    box_rel = (x0_frac, y0_frac, x1_frac, y1_frac)
    rect    = absolute (l, t, r, b) of the window
    """
    if not _HAS_TESSERACT or not _HAS_PIL or img is None:
        return ""
    l, t, r, b = rect
    W, H = r - l, b - t
    x0, y0 = int(box_rel[0] * W), int(box_rel[1] * H)
    x1, y1 = int(box_rel[2] * W), int(box_rel[3] * H)
    crop = img.crop((x0, y0, x1, y1))
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
    return pytesseract.image_to_string(crop, config="--psm 6").lower().strip()


def click_rel(rect, rx, ry):
    """Click at a relative position inside *rect*."""
    if not _HAS_PYAUTOGUI:
        return
    l, t, r, b = rect
    ax, ay = int(l + rx * (r - l)), int(t + ry * (b - t))
    pyautogui.click(ax, ay)


def ocr_click_or_fallback(img, rect, hwnd, keyword, fallback_rel):
    """
    Try to find *keyword* in *img* via OCR and click it.
    Falls back to clicking *fallback_rel* if the keyword is not found.
    """
    if not _HAS_TESSERACT or not _HAS_PYAUTOGUI or not _HAS_PIL or img is None:
        click_rel(rect, *fallback_rel)
        return
    data = pytesseract.image_to_data(
        img.resize((img.width * 2, img.height * 2), Image.LANCZOS),
        output_type=pytesseract.Output.DICT,
    )
    l, t = rect[0], rect[1]
    for i, word in enumerate(data["text"]):
        if keyword.lower() in word.lower() and int(data["conf"][i]) > 30:
            cx = (data["left"][i] + data["width"][i] // 2) // 2
            cy = (data["top"][i]  + data["height"][i] // 2) // 2
            bring_to_front(hwnd)
            pyautogui.click(l + cx, t + cy)
            return
    click_rel(rect, *fallback_rel)


def attempt_login(rect, hwnd, instant=False):
    """Attempt to log in by clicking through the RSC login screens."""
    if not _HAS_PYAUTOGUI:
        return
    bring_to_front(hwnd)
    time.sleep(0.4)
    img  = grab_window(rect)
    full = ocr_region(img, (0, 0, 1, 1), rect)

    if instant:
        if "existing" in full:
            ocr_click_or_fallback(img, rect, hwnd, "existing",
                                  LOGIN_HINTS["existing_user"])
            time.sleep(random.uniform(0.6, 1.8))
            img  = grab_window(rect)
            full = ocr_region(img, (0, 0, 1, 1), rect)
        if random.random() < 0.5:
            bring_to_front(hwnd)
            pyautogui.press("enter")
        else:
            ocr_click_or_fallback(grab_window(rect), rect, hwnd,
                                  "ok", LOGIN_HINTS["ok_button"])
        return

    if "existing" in full:
        ocr_click_or_fallback(img, rect, hwnd, "existing",
                              LOGIN_HINTS["existing_user"])
        time.sleep(0.8)
        img  = grab_window(rect)
        full = ocr_region(img, (0, 0, 1, 1), rect)

    if any(k in full for k in ("username", "password", "login", "enter your")):
        bring_to_front(hwnd)
        pyautogui.press("enter")
        time.sleep(0.8)
        img  = grab_window(rect)
        full = ocr_region(img, (0, 0, 1, 1), rect)

    if any(k in full for k in ("ok", "play", "confirm", "welcome back")):
        ocr_click_or_fallback(img, rect, hwnd, "ok",
                              LOGIN_HINTS["ok_button"])
        time.sleep(0.6)

    bring_to_front(hwnd)
    pyautogui.press("enter")
    time.sleep(0.3)
    pyautogui.press("enter")


def ensure_logged_in(rect, hwnd, instant=False, timeout=60.0, poll=1.5,
                     max_attempts=5):
    """Block until the game window is no longer on the login/disconnect screen.

    Runs attempt_login, then polls check_logged_out until it returns False or
    the timeout expires OR max_attempts failed logins have been made. No other
    bot input should be dispatched while this is running — caller must gate
    its own threads until this returns.
    Returns True if logged in, False otherwise (timeout or max attempts hit).
    """
    if not _HAS_PYAUTOGUI:
        return False
    deadline = time.time() + timeout
    if not check_logged_out(rect):
        return True
    attempts = 0
    while time.time() < deadline and attempts < max_attempts:
        attempt_login(rect, hwnd, instant=instant)
        attempts += 1
        time.sleep(poll)
        if not check_logged_out(rect):
            return True
    return not check_logged_out(rect)


def check_afk_warning(rect):
    """Return True if the AFK warning banner is visible in the chat area."""
    img  = grab_window(rect)
    text = ocr_region(img, (0.0, 0.82, 0.45, 1.0), rect)
    return any(p in text for p in AFK_PHRASES)


def check_logged_out(rect):
    """Return True if the screen looks like the login/disconnect screen."""
    img  = grab_window(rect)
    text = ocr_region(img, (0, 0, 1, 1), rect)
    return any(k in text for k in (
        "existing user", "new user", "login",
        "welcome to runescape", "runescape classic",
        "disconnected", "connection lost",
    ))


# ── RSCBot class ──────────────────────────────────────────────────────────────

class RSCBot:
    """
    Headless auto-login bot.

    Callbacks
    ---------
    status_cb(msg: str)          — called with human-readable status strings
    timer_cb(session_s, next_s)  — called periodically with elapsed / countdown
    """

    def __init__(self):
        self.running        = False
        self.kick_mode      = "5min"   # "5min" or "20min"
        self.instant_mode   = False
        self.delay_min      = 5
        self.delay_max      = 15
        self.status_cb      = None
        self.timer_cb       = None
        self._thread        = None
        self._session_start = None
        self._last_ingame   = None
        self._next_login_at = None
        self._waiting_delay = False

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def kick_seconds(self):
        return 4 * 60 if self.kick_mode == "5min" else 19 * 60

    # ── Control ───────────────────────────────────────────────────────────────

    def start(self):
        self.running         = True
        self._session_start  = time.time()
        self._last_ingame    = time.time()
        self._next_login_at  = None
        self._waiting_delay  = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        self._status("Bot stopped")

    # ── Internals ─────────────────────────────────────────────────────────────

    def _status(self, msg):
        log.info(msg)
        if self.status_cb:
            self.status_cb(msg)

    def _pick_delay(self):
        if self.instant_mode:
            return random.uniform(1, 5)
        return random.uniform(self.delay_min, self.delay_max)

    def _loop(self):
        self._status("Searching for game window…")
        while self.running:
            win = find_game_window()
            if not win:
                self._status("Window not found – retrying in 5s…")
                self._tick(0)
                time.sleep(5)
                continue

            hwnd, rect = win

            # AFK warning check
            if check_afk_warning(rect):
                self._status("AFK warning – re-logging…")
                d = self._pick_delay()
                self._next_login_at = time.time() + d
                self._sleep_countdown(d)
                if not self.running:
                    break
                attempt_login(rect, hwnd, self.instant_mode)
                self._last_ingame    = time.time()
                self._next_login_at  = None
                continue

            # Logged-out check
            if check_logged_out(rect):
                if not self._waiting_delay:
                    d = self._pick_delay()
                    self._next_login_at = time.time() + d
                    self._waiting_delay = True
                    self._status(f"Logged out – waiting {d:.0f}s…")
                remaining = self._next_login_at - time.time()
                if remaining <= 0:
                    self._status("Logging in now…")
                    attempt_login(rect, hwnd, self.instant_mode)
                    self._last_ingame    = time.time()
                    self._next_login_at  = None
                    self._waiting_delay  = False
                else:
                    self._tick(remaining)
                time.sleep(2)
                continue

            # In-game — track time until pre-emptive re-login
            self._waiting_delay = False
            elapsed   = time.time() - self._last_ingame
            remaining = max(0, self.kick_seconds - elapsed)
            if remaining <= 0:
                self._status("Pre-emptive re-login…")
                d = self._pick_delay()
                self._next_login_at = time.time() + d
                self._sleep_countdown(d)
                if not self.running:
                    break
                attempt_login(rect, hwnd, self.instant_mode)
                self._last_ingame    = time.time()
                self._next_login_at  = None
                continue

            self._status(
                f"In-game | {self.kick_mode} | re-login ~{int(remaining)}s"
            )
            self._tick(remaining)
            time.sleep(4)

    def _sleep_countdown(self, seconds):
        end = time.time() + seconds
        while self.running and time.time() < end:
            self._tick(max(0, end - time.time()))
            time.sleep(0.5)

    def _tick(self, next_secs):
        if self.timer_cb and self._session_start:
            self.timer_cb(time.time() - self._session_start, next_secs)
