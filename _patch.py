with open('main.py', encoding='utf-8') as f:
    src = f.read()

# 1. Default font: Consolas -> Segoe UI (no-config fallback)
src = src.replace(
    "    font_name = 'Consolas'\n    if os.path.exists('config.json'):",
    "    font_name = 'Segoe UI'\n    if os.path.exists('config.json'):"
)
# 2. Default font in config.get fallback
src = src.replace(
    "            font_name = cfg.get('font', 'Consolas')",
    "            font_name = cfg.get('font', 'Segoe UI')"
)
# 3. Fallback if font not in FONT_CHOICES
src = src.replace(
    "        font_name = 'Consolas'\n    FONT_UI",
    "        font_name = 'Segoe UI'\n    FONT_UI"
)

# 4. Rename powermine label
src = src.replace(
    "'Powermine (never stop)'",
    "'Powermine (indefinitely)'"
)

# 5. Remove Detection card from Settings, keep hidden IntVar
OLD = '''        # Detection (box thickness only \u2014 confidence is in the Ore Selection panel)
        co, c = card(body, padx=0, pady=6)
        co.pack(fill='x', padx=8, pady=(6, 6))
        section_label(c, 'Detection')
        self.overlay_thickness_var = tk.IntVar(
            value=self.config.get('overlay_box_thickness', 2))
        trow = tk.Frame(c, bg=SURFACE)
        trow.pack(fill='x', padx=8, pady=(4, 4))
        tk.Label(trow, text='Box thickness', bg=SURFACE, fg=MUTED,
                 font=FONT_UI, width=11, anchor='w').pack(side='left')
        self.overlay_thickness_label = tk.Label(
            trow, textvariable=self.overlay_thickness_var,
            bg=BORDER, fg=ACCENT, font=('Consolas', 8, 'bold'), width=3)
        self.overlay_thickness_label.pack(side='right', padx=4)
        ttk.Scale(trow, from_=1, to=6, orient='horizontal',
                  variable=self.overlay_thickness_var,
                  command=lambda v: self.overlay_thickness_var.set(int(float(v)))
                  ).pack(side='left', fill='x', expand=True)'''
NEW = "        self.overlay_thickness_var = tk.IntVar(value=1)  # fixed at 1, no UI"

if OLD in src:
    src = src.replace(OLD, NEW)
    print('Detection card removed OK')
else:
    print('ERROR: Detection card not found')

# 6. Add WalkTo interlock note near powermine toggle
OLD2 = "        self._powermine_toggle = Toggle(_pm_row, self.powermine_var, bg=SURFACE)\n        self._powermine_toggle.pack(side='left', padx=(0, 6))\n        tk.Label(_pm_row, text='Powermine (indefinitely)', bg=SURFACE, fg=FG,"
NEW2 = "        self._powermine_toggle = Toggle(_pm_row, self.powermine_var, bg=SURFACE)\n        self._powermine_toggle.pack(side='left', padx=(0, 6))\n        tk.Label(_pm_row, text='Powermine (indefinitely)', bg=SURFACE, fg=FG,"
# NOTE: label is already renamed above, just check it's there
if OLD2 in src or NEW2 in src:
    print('Powermine label OK')
else:
    print('WARNING: powermine label line not found as expected')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(src)

print('All changes written.')
