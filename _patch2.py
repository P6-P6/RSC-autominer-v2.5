with open('main.py', encoding='utf-8') as f:
    src = f.read()

changes = 0

# 1. Window wider: 660 -> 780
old = "self.root.geometry('660x680')"
new = "self.root.geometry('780x680')"
if old in src:
    src = src.replace(old, new); changes += 1; print('Window width OK')
else:
    print('ERROR: geometry not found')

# 2. Remove multi-client from powermine row (keep only powermine + no-fatigue)
old2 = (
    "        # Disable fatigue \u2014 inline mini toggle to the right of powermine\n"
    "        tk.Frame(_pm_row, bg=SURFACE, width=10).pack(side='left')\n"
    "        Toggle(_pm_row, self.pm_no_fatigue_var, bg=SURFACE).pack(side='left', padx=(0, 4))\n"
    "        tk.Label(_pm_row, text='No fatigue', bg=SURFACE, fg=MUTED,\n"
    "                 font=(FONT_UI[0], 8), anchor='w').pack(side='left')\n"
    "        # Multi-client \u2014 inline on the same row, right side\n"
    "        tk.Frame(_pm_row, bg=SURFACE, width=16).pack(side='left')\n"
    "        Toggle(_pm_row, self.multi_client_var, bg=SURFACE).pack(side='left', padx=(0, 6))\n"
    "        tk.Label(_pm_row, text='Multi-Client', bg=SURFACE, fg=FG,\n"
    "                 font=FONT_UI, anchor='w').pack(side='left')\n"
    "        tk.Label(_pm_row, text='(1-4 clients)', bg=SURFACE, fg=MUTED,\n"
    "                 font=(FONT_UI[0], 8), anchor='w').pack(side='left', padx=(2, 0))"
)
new2 = (
    "        # Disable fatigue \u2014 inline mini toggle to the right of powermine\n"
    "        tk.Frame(_pm_row, bg=SURFACE, width=10).pack(side='left')\n"
    "        Toggle(_pm_row, self.pm_no_fatigue_var, bg=SURFACE).pack(side='left', padx=(0, 4))\n"
    "        tk.Label(_pm_row, text='No fatigue', bg=SURFACE, fg=MUTED,\n"
    "                 font=(FONT_UI[0], 8), anchor='w').pack(side='left')"
)
if old2 in src:
    src = src.replace(old2, new2); changes += 1; print('Powermine row trimmed OK')
else:
    print('ERROR: powermine row multi-client block not found')

# 3. Replace standalone multi-client note with proper toggle row (placed after speed buttons)
old3 = (
    "        # Multi-client note (var already declared above with powermine row)\n"
    "        tk.Label(c, text='Multi-Client: Enable Bot2/3/4 tabs, assign windows. Disables park-mouse & hover.',\n"
    "                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),\n"
    "                 wraplength=380, justify='left').pack(anchor='w', padx=8, pady=(0, 4))"
)
new3 = (
    "        # Multi-client \u2014 below speed buttons\n"
    "        _mc_row = tk.Frame(c, bg=SURFACE)\n"
    "        _mc_row.pack(anchor='w', padx=8, pady=(4, 2))\n"
    "        Toggle(_mc_row, self.multi_client_var, bg=SURFACE).pack(side='left', padx=(0, 8))\n"
    "        tk.Label(_mc_row, text='Multi-Client  (1-4 clients)', bg=SURFACE, fg=FG,\n"
    "                 font=FONT_UI, anchor='w').pack(side='left')\n"
    "        tk.Label(c, text='Enable Bot2/3/4 tabs and assign windows. Disables park-mouse & hover.',\n"
    "                 bg=SURFACE, fg=MUTED, font=(FONT_UI[0], 8, 'italic'),\n"
    "                 wraplength=440, justify='left').pack(anchor='w', padx=22, pady=(0, 4))"
)
if old3 in src:
    src = src.replace(old3, new3); changes += 1; print('Multi-client toggle row OK')
else:
    print('ERROR: multi-client note block not found')

# 4. Remove WalkTo interlock that disables powermine
old4 = (
    "        def _on_walkto_toggle(*_):\n"
    "            if self.walkto_enabled_var.get():\n"
    "                self.powermine_var.set(False)\n"
    "                self._powermine_toggle.set_disabled(True)\n"
    "            else:\n"
    "                self._powermine_toggle.set_disabled(False)\n"
    "        self.walkto_enabled_var.trace_add('write', _on_walkto_toggle)\n"
    "        _on_walkto_toggle()  # apply initial state"
)
new4 = "        # (no interlock between WalkTo and Powermine)"
if old4 in src:
    src = src.replace(old4, new4); changes += 1; print('WalkTo interlock removed OK')
else:
    print('ERROR: WalkTo interlock not found')

print(f'\n{changes}/4 changes applied')
with open('main.py', 'w', encoding='utf-8') as f:
    f.write(src)
print('Written.')
