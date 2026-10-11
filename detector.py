import os
os.environ['YOLO_VERBOSE'] = 'False'

from ultralytics import YOLO
import torch
import numpy as np
import cv2

# Cap PyTorch CPU threads so YOLO inference doesn't saturate all cores and
# starve the Java RSC client.
try:
    torch.set_num_threads(4)
    torch.set_num_interop_threads(2)
except Exception:
    pass

# Class buckets — drives mode-aware filtering inside detect_with_vis.
ORE_CLASSES = {
    'adamantite_rock', 'mithril_rock', 'coal_rock', 'iron_rock',
    'tin_rock', 'copper_rock', 'empty_ore_rock',
}
# Anything in NPCS_TEST1.pt that's a hostile target.
NPC_CLASSES = {
    'chicken', 'ghost', 'spider', 'rat', 'ratL', 'skipper', 'man',
    'cow', 'goblin', 'imp', 'guard', 'spider_s',
}
# Static-NPC classes that are NOT combat targets but matter for banking/shopping.
INTERACTABLE_CLASSES = {'banker', 'shopkeeper'}
# Loot drops the bot may pick up.
LOOT_CLASSES = {'feather', 'bones', 'coins'}


class Detector:
    """One YOLO model per bot. Mode picks the model:
       'mining'  → best.pt        (ore rocks)
       'fight'   → NPCS_TEST1.pt  (NPCs + banker + loot)
       'banking' → NPCS_TEST1.pt  (banker)
    """

    def __init__(self, config):
        self.config = config
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'

        bot_mode = (config.get('bot_mode') or 'mining').lower().strip()
        if bot_mode not in ('mining', 'fight', 'banking'):
            bot_mode = 'mining'
        self.bot_mode = bot_mode

        model_settings = config.get("model_settings", {})
        self.use_adamantite_model = model_settings.get("use_adamantite_model", False)

        # Pick primary model based on mode.
        if bot_mode in ('fight', 'banking'):
            primary_path = "NPCS_TEST1.pt"
        else:
            primary_path = "best.pt"

        self.main_model = None
        if os.path.exists(primary_path):
            self.main_model = YOLO(primary_path, verbose=False)
            self.main_model.to(self.device)
            print(f"[MODEL] {primary_path} ({bot_mode}) classes: {self.main_model.names}")
        else:
            print(f"[MODEL] WARNING: {primary_path} not found — detector will produce no detections")

        # Adamantite secondary model is mining-only.
        self.adamantite_model = None
        adamantite_path = "adamantite.pt"
        if bot_mode == 'mining' and self.use_adamantite_model and os.path.exists(adamantite_path):
            self.adamantite_model = YOLO(adamantite_path, verbose=False)
            self.adamantite_model.to(self.device)
        else:
            self.use_adamantite_model = False

        # Coal-only mode uses a dedicated model (exp.pt) that performs better on
        # coal's low-contrast rocks. Loaded lazily the first time coal-only fires
        # so it costs nothing when mining anything else.
        self.coal_model = None
        self.coal_model_path = "exp.pt"

        # Coal-only adaptive confidence: normally 0.75, but the bot loop sets
        # coal_relax=True after a couple of empty rotation passes so we
        # temporarily drop to 0.60 and accept weaker coal candidates rather than
        # idle. Reset to False (back to 0.75) once coal is actually clicked.
        self.coal_relax = False
        self.COAL_CONF_NORMAL = 0.75
        self.COAL_CONF_RELAXED = 0.60

        self.conf_threshold = config.get("detection_settings", {}).get("confidence_threshold", 0.75)

    def _ensure_coal_model(self):
        """Lazy-load the coal-only model (exp.pt). Returns the model or None
        if the file is missing (caller falls back to the main model)."""
        if self.coal_model is None:
            if os.path.exists(self.coal_model_path):
                self.coal_model = YOLO(self.coal_model_path, verbose=False)
                self.coal_model.to(self.device)
                print(f"[MODEL] {self.coal_model_path} (coal-only) classes: {self.coal_model.names}")
            else:
                print(f"[MODEL] WARNING: coal model {self.coal_model_path} not found — "
                      f"using main model for coal")
        return self.coal_model

    def detect_with_vis(self, frame, window_region, ore_checkboxes=None, annotate=True):
        """Run inference and filter to selected targets.

        `ore_checkboxes` here is the GENERIC selection dict — in mining mode
        it holds ore picks, in fight mode it holds NPC picks. Banker / loot
        always pass through unfiltered.
        """
        selection = ore_checkboxes if ore_checkboxes is not None else self.config.get("ore_checkboxes", {})
        if self.bot_mode in ('fight', 'banking'):
            # In fight/banking, the user picks NPCs via npc_checkboxes.
            selection = self.config.get("npc_checkboxes", selection)

        # Read confidence threshold dynamically from config.
        self.conf_threshold = self.config.get("detection_settings", {}).get("confidence_threshold", 0.75)
        self.conf_threshold = max(0.01, min(1.0, self.conf_threshold))

        # Coal-only override: when coal is the ONLY ore selected, use the
        # dedicated coal model (exp.pt) at a fixed 0.75 confidence instead of
        # the main model / global threshold. exp.pt is tuned for coal, and 0.65
        # keeps out low-confidence false positives (e.g. depleted/empty rocks
        # mislabeled as coal). Falls back to the main model if exp.pt is missing.
        active_model = self.main_model
        if self.bot_mode == 'mining':
            _active_ores = [k for k in ('tin_rock', 'copper_rock', 'coal_rock',
                                         'iron_rock', 'mithril_rock', 'adamantite_rock')
                            if selection.get(k, False)]
            if _active_ores == ['coal_rock']:
                self.conf_threshold = (self.COAL_CONF_RELAXED if self.coal_relax
                                       else self.COAL_CONF_NORMAL)
                _coal = self._ensure_coal_model()
                if _coal is not None:
                    active_model = _coal

        all_detections = []

        results_main = []
        if active_model is not None:
            results_main = active_model(frame, conf=self.conf_threshold,
                                        device=self.device, verbose=False)

        for result in results_main:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                class_id = int(box.cls[0])
                class_name = active_model.names[class_id]

                # Mode-aware filtering.
                if self.bot_mode == 'mining':
                    if class_name == "empty_ore_rock":
                        if not self.config.get("show_empty_ore", False):
                            continue
                    elif class_name in ORE_CLASSES:
                        if not selection.get(class_name, False):
                            continue
                    else:
                        # Not an ore (shouldn't happen with best.pt) — skip.
                        continue
                    if class_name == "adamantite_rock" and self.use_adamantite_model:
                        continue
                else:
                    # fight / banking
                    if class_name in NPC_CLASSES:
                        if not selection.get(class_name, False):
                            continue
                    elif class_name in INTERACTABLE_CLASSES:
                        # banker / shopkeeper always pass — banking flow needs them.
                        pass
                    elif class_name in LOOT_CLASSES:
                        # Loot pickup is a future feature; pass through for now
                        # so the GUI overlay shows it, but the bot loop ignores it.
                        pass
                    else:
                        continue

                all_detections.append({
                    "box": (x1, y1, x2, y2),
                    "confidence": conf,
                    "class_id": class_id,
                    "class_name": class_name
                })

        # Adamantite secondary model — mining only.
        if self.adamantite_model is not None and selection.get("adamantite_rock", False):
            results_adam = self.adamantite_model(frame, conf=self.conf_threshold,
                                                 device=self.device, verbose=False)
            for result in results_adam:
                boxes = result.boxes
                if boxes is None:
                    continue
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    class_id = int(box.cls[0])
                    class_name = self.adamantite_model.names[class_id]
                    all_detections.append({
                        "box": (x1, y1, x2, y2),
                        "confidence": conf,
                        "class_id": class_id,
                        "class_name": class_name
                    })

        annotated_frame = None
        if annotate:
            annotated_frame = frame.copy()

            COLORS = {
                # ore
                'adamantite': (0,   0,   255),
                'mithril':    (200, 0,   200),
                'coal':       (140, 140, 140),
                'iron':       (220, 220, 220),
                'tin':        (255, 230,   0),
                'copper':     (0,  165,  255),
                'empty':      (0,  220,  220),
                # npc / interactable / loot
                'banker':     (0,   255, 255),
                'shopkeeper': (255, 255, 0),
                'feather':    (180, 180, 255),
                'bones':      (255, 255, 255),
                'coins':      (0,   215, 255),
            }
            LABELS = {
                'adamantite_rock': 'Addy', 'mithril_rock': 'Mith',
                'coal_rock': 'Coal', 'iron_rock': 'Iron',
                'tin_rock': 'Tin', 'copper_rock': 'Copper',
                'empty_ore_rock': 'Empty',
            }

            box_w = max(1, self.config.get('overlay_box_thickness', 2))
            for det in all_detections:
                x1, y1, x2, y2 = [int(v) for v in det["box"]]
                conf = det["confidence"]
                class_name = det["class_name"]

                color = next((v for k, v in COLORS.items() if k in class_name), (0, 255, 0))
                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, box_w)

                short = LABELS.get(class_name, class_name.replace('_rock', '').title())
                label = f'{short}  {conf:.0%}'
                cv2.putText(annotated_frame, label, (x1, max(y1 - 4, 10)),
                            cv2.FONT_HERSHEY_DUPLEX, 0.5, color, 1, cv2.LINE_AA)

        return all_detections, annotated_frame
