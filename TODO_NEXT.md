# TODO — Next Session Tasks

Captured 2026-04-30. Updated 2026-07-09.

## Done this session (2026-07-09)
- **Coal-only confidence 0.45 → 0.35** — detector.py coal-mode override now uses 0.35 when coal is the only ore selected.
- **Coal+Any (`any_ore`) feature removed entirely** — checkbox gone from master + slave bot tabs (main.py), all `any_ore` checks stripped from detector.py and bot.py, stale `any_ore` keys removed from config.json.

## In flight
- [ ] Test master-bot banking end-to-end (user is testing)
- [ ] Test hover-no-click fix — normal mode should now re-assert window focus between bezier move and SendInput click

## Banking triggers
- [ ] **Multi-trigger banking** — banking should fire on ANY of:
  1. OCR sees inventory at strict 30/30
  2. **Template match `30_30_fullinventory.png`** — already in `templates/`. Add a TM check in the OCR thread (cheaper than EasyOCR; can run more often and as a sanity confirmation)
  3. WalkTo-click threshold reached (`_mine_count >= _walkto_next_at`) — currently this fires walkto only; add an option to route it through banking instead when banking is enabled
  - All three should set `_banking_request = True` if `banking_enabled` is on. First trigger wins; subsequent ones are no-ops while FSM is active.

## Bot logic
- [ ] **Banking for Bot2/3/4** — wire FSM into MC loop so slave bots also bank + walkto train.
- [ ] **Universal standing-here walkto** — toggle: when any client detects "you have been standing here", ALL non-powermining clients fire their `::walkto` command. Powermining bots are exempt.
- [ ] **Pause-on-user-input** — toggle: while user moves mouse/keyboard, pause all bots; resume after 2s of no input.
- [ ] **Remove standing-here mouse nudge** — the 1px nudge doesn't reset the AFK timer (must actually walk to a new tile). Delete that branch.
- [ ] **Remove fatigue % OCR** — drop the top-left fatigue percentage OCR entirely + remove the fatigue % readout from GUI. Keep:
  - Template-match for "fatigue 100%" (templates `fatgiue100red.png` / `fatigue100red2.png` already in repo)
  - Bottom-chat OCR for "you are too tired to mine" (works well, leave alone)
- [x] **Per-bot state display** — STATE column in mini 4-bot panel shows each bot's real last_action text (truncated to 9 chars). FAT and INV columns removed as irrelevant.

## GUI cleanup
- [ ] **Split sections**: separate "Mining Mode" and "Mouse Settings" into distinct sections. Mouse Settings must sit BELOW Mining Mode.
- [ ] **Move into Mouse Settings**: Lazy idle pause, Park mouse outside, Hover mode, Direct to ore / Center window hop, Click Verification (currently in Experimental).
- [ ] **Hover Mode rename** — "Hover Mode" → "Hover mouse on next Ore". Drop the [experimental] tag.
- [ ] **WalkTo not experimental** — drop the [experimental] label, it works.
- [ ] **Click Verification not experimental** — move out of Experimental tab into Mouse Settings.
- [ ] **Mouse Profiles simplify** — show only `Profile Seed: ####` label + a `Random` button. Remove min/max/curve-strength controls.
- [ ] **WalkTo dedicated section** — give WalkTo its own section in each Bot tab with two subsections:
  - **WalktoBank / Destination**
  - **WalktoTrain / Area**
  - One-line note: *"Randomly picks one of the listed entries each time."*

## Banking destination integrity
- [ ] **Couple short + full names into one paired entry** — format: `shortname (full name)` e.g. `vw (varrock west bank)`. Short name and full name are intertwined so picking one city for the short name forces the matching full name. No mixing varrock east + falador west.

## Open questions / clarifications needed before coding
- For per-bot state display: DONE — STATE column in mini panel.

## Done this session (2026-05-04)
- **Mini HUD bank + train buttons** — 🏦 button forces banking, ★ button fires ::walkto train. One per bot row (Master + Bot 2–5). Defined as `_force_bank(idx)` / `_force_train(idx)` closures in `_build_ui` (main.py).
- **Hover-no-click fix (normal mode)** — `move_and_click` in mouse.py now accepts `focus_cb=` kwarg; ore click in bot.py passes `focus_cb=self.bring_window_to_front` so window focus is re-asserted after bezier curve, right before SendInput fires.
- **Click center ±3px** — `get_click_position` changed from `±10px` to `±3px` randomization.
- **Persistent runtime** — runtime saves to `runtime_save.json` on stop, resumes on next start. `_runtime_saved_secs` loaded in `__init__` + `start_bot`. `_save_runtime()` / `_load_saved_runtime()` helpers in main.py near `stop_bot`.
- **Cha-ching on bank complete** — 3-tone ascending beep (E→G→C) when FSM sees ore after walking back to train (WALK_TO_TRAIN → IDLE). bot.py ~line 4107.
- **Arrival beeps removed** — `_tm_check_autowalk` silent. `_schedule_walkto_beeps` is now `pass`. Remaining beeps: stop/error, standing-here, fatigue 100%.
- **Walkto destinations — all bots use master** — `_walkto_source_dict()` always returns `self.config`. Per-slot override path removed.
- **Super_fast post-click delay** — 50–100ms → 20–75ms.
- **Camera rotate-only toggle** — new `camera_rotate_only` config key. Toggle in Anti-Ban tab. `_zoom_out()` skips if enabled.
- **post_click_delay args** — fixed reversed `random.uniform(0.5, 0.15)` → `random.uniform(0.15, 0.5)` in mouse.py (same range, written correctly).

## Done this session (2026-05-02)
- **WALK_TO_TRAIN grace period** — 20–35s random wait after ::walkto train before checking for ores. Only trusts frames timestamped after state entry. Grace + 10s fallback for MC stale-buffer. Resets per bank run.
- **Banker confidence raised** 0.55 → 0.78 → 0.88
- **Banker picked by proximity to frame center** — stops it clicking shop/guard NPCs in corners. Debug log shows `dist=XXpx`.
- **GUI: FAT + INV columns removed** from mini 4-bot status panel (header, widgets, live update calls)
- **GUI: TOTAL ORES EST → Red X Clicks:** label rename
- **GUI: Stats box split** — Banked Ore (inv×28) + Inv's Banked (raw count) as separate rows
- **GUI: Runtime clock** moved from top bar into stats box (Runtime: row)
- **GUI: Mouse X/Y + Last Click ms** moved from top bar into stats box (Mouse: / Last Click: rows)
- **GUI: Status dot** shows `● RUNNING  MM:SS` and ticks live
- **GUI: Footer pack order fixed** — footer packed before notebook so START/STOP/SAVE/OVERLAY always visible at any window size / DPI
- **GUI: Window geometry** set to `960×720`, minsize `760×600`
- **GUI: Debug log** shrunk `height=12 → 5`, drag-to-resize bar added (3–20 lines)
- **GUI: Titlebar height** tightened `44 → 38px`, footer `54 → 44px`

## Already done (prior session — PerfFixattempt)
- DPI awareness (PER_MONITOR_AWARE_V2)
- SendInput-based clicks (replaced mouse_event)
- Fresh pre-click rescan + empty-at-target tracking → click_attempts bump
- Missed-box failsafe (single-client + MC)
- Click Verification toggle (red-X marker, in Experimental — pending move to Mouse Settings)
- Priority-tier sort for ore selection (single + MC paths)
- MC standing-here far-ore powermine logic
- Banking FSM master-bot path: walkto bank → click banker (NPCS_TEST1.pt lazy-load) → wait UI (`bank_ui_bar.png`) → click `loadout_mining.png` → 50/50 ESC vs `close_window_bank1.png` → walkto train
