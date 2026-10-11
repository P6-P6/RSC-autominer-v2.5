"""Banking state machine — drives the deposit-and-return cycle.

States:
    IDLE              – not banking; main mining loop owns the bot
    WALKING_TO_BANK   – ::walkto <bank> issued; waiting for arrival
    AT_BANK           – banker detected nearby; click it
    DEPOSITING        – bank UI open; click "Deposit all"
    CLOSING           – click X on bank UI
    WALKING_TO_MINE   – ::walkto <mine>; waiting for arrival
    DONE              – mining spot reached; FSM hands control back

YOLO classes / templates required for full operation (NOT yet shipped):
    - YOLO class: 'banker'  (detected near bank counter)
    - Template:   'bank_ui_open.png'   (deposit-all interface visible)
    - Template:   'deposit_all_btn.png'
    - Template:   'close_x_btn.png'

Until those land, the FSM logs and times out gracefully. The mining bot can
still rely on it as the structural framework — when assets exist, hook them
into the marked locations below.
"""
import time


class BankingState:
    IDLE = 'IDLE'
    WALKING_TO_BANK = 'WALKING_TO_BANK'
    AT_BANK = 'AT_BANK'
    DEPOSITING = 'DEPOSITING'
    CLOSING = 'CLOSING'
    WALKING_TO_MINE = 'WALKING_TO_MINE'
    DONE = 'DONE'


# Per-state max wall-clock seconds before forcing a stop.
TIMEOUT_S = {
    BankingState.WALKING_TO_BANK: 90.0,
    BankingState.AT_BANK: 15.0,
    BankingState.DEPOSITING: 10.0,
    BankingState.CLOSING: 6.0,
    BankingState.WALKING_TO_MINE: 90.0,
}


class BankingFSM:
    def __init__(self, bot):
        self.bot = bot              # MiningBot owner
        self.state = BankingState.IDLE
        self._state_entered_at = 0.0
        self._enabled_walkto_back = True

    def is_idle(self):
        return self.state == BankingState.IDLE

    def is_active(self):
        return self.state not in (BankingState.IDLE, BankingState.DONE)

    def _enter(self, new_state, reason=''):
        self.state = new_state
        self._state_entered_at = time.time()
        try:
            self.bot._set_action(f'Banking: {new_state}'
                                 + (f' ({reason})' if reason else ''))
            self.bot._dbg(f'[BANK] -> {new_state} {reason}')
        except Exception:
            pass

    def begin_bank_run(self, walkto_destination):
        """Called by main loop when inventory full / walkto threshold reached."""
        if self.is_active():
            return
        self._enter(BankingState.WALKING_TO_BANK,
                    reason=f'dest={walkto_destination!r}')
        try:
            self.bot._type_ingame_message(f'::walkto {walkto_destination}')
        except Exception as e:
            self.bot._dbg(f'[BANK] walkto type err: {e}')

    def tick(self, detections, frame):
        """Called once per main-loop iteration when active. Drives transitions
        based on detections + frame. Returns True if the FSM consumed the tick
        (mining loop should skip its normal click cycle)."""
        if self.is_idle():
            return False

        # Per-state timeout — gracefully bail out of hung states.
        elapsed = time.time() - self._state_entered_at
        timeout = TIMEOUT_S.get(self.state, 0.0)
        if timeout and elapsed > timeout:
            self.bot._dbg(f'[BANK] {self.state} timed out after {elapsed:.1f}s')
            self._enter(BankingState.IDLE, reason='timeout')
            try:
                self.bot._stop_bot(f'Banking {self.state} timeout',
                                   [(1500, 200), (900, 200), (1200, 400)])
            except Exception:
                pass
            return True

        if self.state == BankingState.WALKING_TO_BANK:
            # TODO: detect banker class in `detections` to transition.
            # For now: if walkto stops moving (signaled by inventory still full
            # AND no movement) we'd advance — but without a banker class we
            # just hand back to the loop and rely on the timeout.
            if self._banker_visible(detections):
                self._enter(BankingState.AT_BANK)
            return True

        if self.state == BankingState.AT_BANK:
            # TODO: click the banker NPC (use detection bbox).
            if not self._click_banker(detections, frame):
                return True
            self._enter(BankingState.DEPOSITING)
            return True

        if self.state == BankingState.DEPOSITING:
            # TODO: wait for bank UI template, then click "Deposit all".
            if not self._click_deposit_all(frame):
                return True
            self._enter(BankingState.CLOSING)
            return True

        if self.state == BankingState.CLOSING:
            # TODO: click the X to close bank.
            if not self._close_bank_ui(frame):
                return True
            if self._enabled_walkto_back:
                # Pick the user's training/back destination — falls back to
                # the same bank string if no training spot is configured.
                back = (self.bot.config.get('walkto_back_destination') or
                        self.bot.config.get('walkto_dest_a') or
                        self.bot.config.get('walkto_destination', '')).strip()
                if back:
                    try:
                        self.bot._type_ingame_message(f'::walkto {back}')
                    except Exception:
                        pass
                    self._enter(BankingState.WALKING_TO_MINE,
                                reason=f'back={back!r}')
                    return True
            self._enter(BankingState.DONE)
            return True

        if self.state == BankingState.WALKING_TO_MINE:
            # TODO: detect ores in detections to confirm arrival.
            if any(d.get('class_name') and d['class_name'] != 'empty_ore_rock'
                   for d in (detections or [])):
                self._enter(BankingState.DONE, reason='ores visible')
            return True

        if self.state == BankingState.DONE:
            # Hand control back to the mining loop on the next tick.
            self._enter(BankingState.IDLE)
            return False

        return True

    # ── Detection / action stubs (replace with real YOLO + template logic) ──

    def _banker_visible(self, detections):
        for d in detections or []:
            cn = (d.get('class_name') or '').lower()
            if 'banker' in cn:
                return True
        return False

    def _click_banker(self, detections, frame):
        """Click the banker NPC. Returns True on success, False to retry."""
        for d in detections or []:
            cn = (d.get('class_name') or '').lower()
            if 'banker' in cn:
                try:
                    pos = self.bot.get_click_position(d['box'])
                    # TODO: convert to screen coords and click — same path as
                    # main click site. Stubbed until banker class lands.
                    self.bot._dbg(f'[BANK] (stub) would click banker at {pos}')
                    return True
                except Exception:
                    return False
        return False

    def _click_deposit_all(self, frame):
        """Detect bank UI + click "Deposit all". TODO: use cv2.matchTemplate
        against templates/bank_ui_open.png and templates/deposit_all_btn.png."""
        self.bot._dbg('[BANK] (stub) deposit-all template not yet implemented')
        return False  # never advances until the template is added

    def _close_bank_ui(self, frame):
        """Click the X to close bank. TODO: template match for close_x_btn.png."""
        self.bot._dbg('[BANK] (stub) close-bank template not yet implemented')
        return False
