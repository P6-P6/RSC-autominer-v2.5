# CLAUDE.md — Bot Project Context for AI/LLM

Project: RSC Revolution 2 Mining Bot — V2.5 Banker Edition  
Working dir: `G:\My Drive\123_RSC_BOT\123_test11_sat4_25\Mining bot to universal 1.1\V2.2 Banker Edition- Current-Continue Testing - Good Copy v2.3\V2.2 Banker Edition- Current-Continue Testing - Good Copy v2.3\`  
Language: Python 3.11–3.14 | GUI: Tkinter | Detection: YOLO (ultralytics) + EasyOCR | Input: win32api + SendInput

---

## Key Files

| File | Role |
|---|---|
| `bot.py` (~205KB) | Core mining loop, banking FSM, camera, hover, multi-client orchestration |
| `main.py` (~265KB) | Tkinter GUI, config save/load, bot start/stop, live stats, mini HUD |
| `mouse.py` | HumanMouse class — bezier move, click via SendInput |
| `detector.py` | YOLO wrapper for ore detection |
| `banking.py` | Banking NPC interaction helpers |
| `autologin.py` | Auto-login sequence |
| `user_activity.py` | Detects real user mouse/keyboard input (pause-on-input feature) |
| `config.json` | All settings — persisted to disk on save |
| `runtime_save.json` | Persisted runtime clock (auto-created on first stop) |
| `TODO_NEXT.md` | Active task list — update this after every session |

---

## Architecture

- **Master bot** (`client_id=0`) runs the main action loop.
- **Slave bots** (`client_id=1–4`) run detection threads only; master's MC loop hops between all windows.
- **Banking FSM** states: `WALK_TO_BANK → FIND_BANKER → CLICK_MINE_PRESET → CLOSE_BANK → WALK_TO_TRAIN → IDLE`
- **Detection buffer** (`_det_buf`): thread-safe ring buffer; main loop reads latest detections from it.
- **MOUSE_LOCK**: class-level lock — only one bot can move/click at a time across all clients.
- **Speed modes**: `super_fast` (20–75ms post-click) | `fast` (0.8–1.2s) | `lazy` (1.2–2.4s) | `super_lazy` (1–30s)
- **Walkto destinations**: all bots (0–5) always read from master config (`_walkto_source_dict` returns `self.config` for all).

---

## Session Log — 2026-05-04

### Done this session

- **Mini HUD bank + train buttons** — each bot row in BOTH the main window panel AND the popout HUD (`_open_mini_hud`) has two icon buttons:
  - 🏦 (bank) → sets `_banking_request = True` on that bot instantly
  - ★ (train) → fires `::walkto <train_dest>` via `_pick_walkto_train_destination()` on that bot
  - Main window: closures `_force_bank(idx)` / `_force_train(idx)` inside `_build_ui`, main.py ~line 649
  - Popout HUD: closures `_hud_force_bank(idx)` / `_hud_force_train(idx)` inside `_open_mini_hud`, main.py ~line 4591
  - Buttons packed `side='right'` BEFORE the expanding state label so they don't get squeezed out

- **Hover-no-click fix (normal mode)** — `move_and_click` in mouse.py now accepts `focus_cb=` kwarg; called between `move_mouse` and `click()`. The ore click in bot.py passes `focus_cb=self.bring_window_to_front`. This re-asserts window focus after the bezier curve (which can take 200–500ms and lose focus) right before `SendInput` fires. Fast path: no-op if window already focused.

- **Click center ±3px** — `get_click_position` in bot.py changed from `random.randint(-10, 10)` to `random.randint(-3, 3)`.

- **Persistent runtime** — runtime clock accumulates across sessions:
  - Saved to `runtime_save.json` on every `stop_bot()` call
  - Loaded on GUI init and on each `start_bot()` call into `_runtime_saved_secs`
  - `update_live_stats` adds `_runtime_saved_secs` to current elapsed
  - Helper methods: `_load_saved_runtime()` / `_save_runtime()` in main.py near `stop_bot`

- **Cha-ching sound on bank complete** — 3-tone ascending beep (E→G→C, 80/80/220ms) plays when banking FSM transitions `WALK_TO_TRAIN → IDLE` on ore-visible confirm (bot.py ~line 4107).

- **Arrival beeps removed** — `_tm_check_autowalk` no longer beeps on arrival. `_schedule_walkto_beeps` is now a no-op (`pass`). Beeps that remain: stop/error pattern, standing-here template, fatigue 100% (these are intentional).

- **Walkto destination — all bots use master** — `_walkto_source_dict()` simplified to always return `self.config`. Slave `sub_cfg` is already a shallow copy of master config, so walkto keys are always master's. Per-slot override path removed (was causing wrong destinations).

- **Super_fast post-click delay** — changed from `0.050–0.100s` to `0.020–0.075s`.

- **Camera rotate-only toggle** — new config key `camera_rotate_only`. When True, `_zoom_out()` returns immediately. Toggle added to Anti-Ban tab in main.py. Saved in `save_config`.

- **post_click_delay in move_and_click** — fixed reversed args `random.uniform(0.5, 0.15)` → `random.uniform(0.15, 0.5)` (functionally same range but written correctly).

---

## Still Open (from TODO_NEXT.md)

- [ ] **Multi-trigger banking** — bank on ANY of: OCR 30/30, TM `30_30_fullinventory.png`, walkto-click threshold
- [ ] **Banking for Bot2/3/4** — wire FSM into MC loop so slave bots also bank + walkto train
- [ ] **Universal standing-here walkto** — all non-powermine clients fire `::walkto` when any client detects standing-here
- [ ] **Pause-on-user-input** — toggle: pause all bots while user moves mouse/keyboard, resume after 2s idle
- [ ] **Remove standing-here mouse nudge** — delete the 1px nudge branch (doesn't reset AFK timer)
- [ ] **Remove fatigue % OCR** — drop top-left fatigue % OCR + GUI readout. Keep: fatigue-100% TM + bottom-chat OCR
- [ ] **GUI split sections** — "Mining Mode" and "Mouse Settings" into distinct sections; Mouse Settings below Mining Mode
- [ ] **Move into Mouse Settings** — Lazy idle pause, Park mouse outside, Hover mode, Direct to ore / Center window hop, Click Verification
- [ ] **Hover Mode rename** — "Hover Mode" → "Hover mouse on next Ore", drop [experimental]
- [ ] **WalkTo / Click Verification** — drop [experimental] labels, move to proper tabs
- [ ] **Mouse Profiles simplify** — show only `Profile Seed: ####` + `Random` button. Remove min/max/curve-strength controls
- [ ] **WalkTo dedicated section** — give WalkTo its own section per Bot tab: WalktoBank/Destination + WalktoTrain/Area
- [ ] **Banking destination pairing** — couple short + full names: `shortname (full name)` format, no mixing cities

---

## Important Patterns / Gotchas

- **`_walkto_source_dict` always returns `self.config`** — do not re-add per-slot override logic without checking with user first; it was causing slaves to use wrong destinations.
- **Banking FSM cha-ching fires at `WALK_TO_TRAIN → IDLE`** (ore visible, line ~4107), not at bank-close. Do not move it to CLOSE_BANK — that's too early.
- **`bring_window_to_front()` has a fast path** — returns immediately if window already focused. Safe to call multiple times per click cycle.
- **`_schedule_walkto_beeps` is intentionally a no-op** — user removed arrival beeps. Do not restore them.
- **`runtime_save.json`** is created automatically; do not add it to .gitignore unless user asks.
- **File paths have spaces** — use PowerShell with quoted paths. Read/Edit tools handle it natively.
- **Google Drive sync** — files are on G:\My Drive\... — edits take effect immediately but sync to cloud.
- **Speed mode delays** — super_fast: 20–75ms | fast: 0.8–1.2s | lazy: 1.2–2.4s | super_lazy: 1–30s (triangular, biased high).
- **YOLO models** — `best.pt` (ores, ~6MB), `NPCS_TEST1.pt` (banker NPCs, lazy-loaded), `exp.pt` (coal-only model, lazy-loaded). All in project root.
- **Coal-only mode** — when `coal_rock` is the ONLY selected ore (mining mode), `detector.py` swaps to `exp.pt` and hard-sets confidence to **0.75** (was previously best.pt @ 0.27; 0.75 avoids clicking empty/depleted rocks mislabeled as coal). Any other/multi ore selection uses `best.pt` + the global threshold. Logic in `Detector.detect_with_vis` (`_active_ores == ['coal_rock']` branch) + `_ensure_coal_model()`.
- **Coal adaptive confidence** — after **2** empty rotation passes with no coal, the bot drops the coal-only threshold from **0.75 → 0.60** (sets `detector.coal_relax = True`) so weaker coal gets picked up; restored to 0.75 when coal is found again. Wired into BOTH rotation paths so master AND slaves behave the same:
  - **Single/master path** — `_no_red_x_rotation_count >= 2` sets `self.detector.coal_relax`; reset in `_note_registered_click` (confirmed click).
  - **MC hop loop** — `_inner_no_ore >= 6` (rotate fires every 3rd miss, so 2 rotations) sets `cur.detector.coal_relax`; reset at the "Ore found — click" line (`_inner_no_ore = 0`).
  - Flag lives on the Detector object (NOT config) because slave bots hold a config copy while the detector holds the original.
- **Bot labels in mini HUD** — `['Master', 'Bot 2', 'Bot 3', 'Bot 4', 'Bot 5']` → `client_id` 0–4.
