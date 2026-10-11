"""User-input vs bot-input discriminator.

Windows's GetLastInputInfo() returns the most recent input event tick — but
that includes synthetic input from the bot itself (SendInput, SetCursorPos).
We can't tell raw user input from bot input via that API alone.

Trick: the bot calls record_bot_input() right after EVERY synthetic input
action. That records the current GetTickCount(). When the watcher reads
GetLastInputInfo() and the dwTime is GREATER than our recorded bot tick by
more than a small grace (250ms), the input must have come from the user.

Used by bot.py main action loop to pause when the user is doing something.
"""
import ctypes
from ctypes import wintypes
import time

# Mutable container so all importers see updates in-place.
_BOT_INPUT_TICK  = [0]
_LAST_USER_TS    = [0.0]
_BOT_BUSY_DEPTH  = [0]    # >0 means bot is actively performing input — ignore Windows' tick
_LAST_SEEN_TICK  = [0]    # last dwTime we observed — only flag user input when tick changes


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_uint),
                ('dwTime', ctypes.c_uint)]


_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def _tick_now():
    try:
        return _kernel32.GetTickCount()
    except Exception:
        return 0


def record_bot_input():
    """Stamp the current tick — call after every synthetic mouse/key action."""
    _BOT_INPUT_TICK[0] = _tick_now()


def begin_bot_input():
    """Mark the start of a bot input action. While busy depth > 0 the watcher
    treats ALL OS-reported input as bot input. Reentrant via depth counter."""
    _BOT_BUSY_DEPTH[0] += 1


def end_bot_input():
    """Mark end of a bot input action. Stamps tick + decrements busy depth."""
    record_bot_input()
    if _BOT_BUSY_DEPTH[0] > 0:
        _BOT_BUSY_DEPTH[0] -= 1


def update_user_activity(grace_ms=250):
    """Poll GetLastInputInfo and update _LAST_USER_TS if a real user input
    happened (i.e. last input tick > our last recorded bot tick + grace),
    AND the bot isn't currently in the middle of a synthetic input action.
    Call from a background thread on a short interval (80–120ms)."""
    if _BOT_BUSY_DEPTH[0] > 0:
        return  # bot is currently moving — every tick is the bot's, ignore
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not _user32.GetLastInputInfo(ctypes.byref(lii)):
        return
    last_input_tick = int(lii.dwTime)
    # Only register user input when the tick actually changed (new event).
    # Without this check, a stale tick from before the bot started would keep
    # refreshing _LAST_USER_TS every 100ms, preventing the bot from ever resuming.
    if last_input_tick != _LAST_SEEN_TICK[0]:
        _LAST_SEEN_TICK[0] = last_input_tick
        if last_input_tick > _BOT_INPUT_TICK[0] + grace_ms:
            _LAST_USER_TS[0] = time.time()


def seconds_since_user_input():
    """Wall-clock seconds since last detected real user input.
    Returns a large number if none ever recorded."""
    if _LAST_USER_TS[0] == 0.0:
        return 1e9
    return time.time() - _LAST_USER_TS[0]


def is_user_active(window_secs=2.0):
    """True if real user input happened within the last `window_secs` seconds."""
    return seconds_since_user_input() < window_secs


def _patch_win32_keybd_event():
    """Monkey-patch win32api.keybd_event so bot typing also stamps the bot
    input tick. Without this, typing ::walkto would look like 'user input'
    to the watcher and we'd pause ourselves. Idempotent."""
    if getattr(_patch_win32_keybd_event, '_done', False):
        return
    try:
        import win32api
        _orig = win32api.keybd_event
        def _wrapped(*args, **kwargs):
            r = _orig(*args, **kwargs)
            record_bot_input()
            return r
        win32api.keybd_event = _wrapped
        _patch_win32_keybd_event._done = True
    except Exception:
        pass


def start_watcher_thread(poll_interval=0.10):
    """Idempotent — starts a daemon background thread that calls
    update_user_activity() every `poll_interval` seconds."""
    import threading
    if getattr(start_watcher_thread, '_started', False):
        return
    start_watcher_thread._started = True

    # Seed with current tick so prior OS input (from before bot started)
    # isn't misread as live user input and causes an immediate permanent pause.
    _BOT_INPUT_TICK[0] = _tick_now()

    _patch_win32_keybd_event()

    def _loop():
        while True:
            try:
                update_user_activity()
            except Exception:
                pass
            time.sleep(poll_interval)

    t = threading.Thread(target=_loop, daemon=True, name='user-input-watcher')
    t.start()
