import tkinter as tk
from tkinter import ttk, colorchooser, messagebox
import ast

class HudSettingsDialog(tk.Toplevel):
    def __init__(self, parent, hud_panels, on_apply_callback=None):
        super().__init__(parent)
        self.title("HUD Configuration")
        self.geometry("600x600")
        self.hud_panels = hud_panels
        self.on_apply_callback = on_apply_callback
        self.current_panel_key = None
        self.entries = {}
        self.panel_keys = []
        
        self._create_widgets()
        
    def _create_widgets(self):
        # Main layout: Left list of panels, Right properties
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Left Panel: Listbox
        left_frame = ttk.LabelFrame(main_frame, text="Panels", padding="5")
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        self.panel_listbox = tk.Listbox(left_frame, width=20)
        self.panel_listbox.pack(fill=tk.BOTH, expand=True)
        self.panel_listbox.bind('<<ListboxSelect>>', self._on_panel_select)
        self.panel_listbox.bind('<Button-1>', self._on_panel_click)
        self._refresh_panel_list()
            
        # Right Panel: Properties Scrollable Frame
        right_frame = ttk.LabelFrame(main_frame, text="Properties", padding="5")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Canvas for scrolling
        self.canvas = tk.Canvas(right_frame)
        self.scrollbar = ttk.Scrollbar(right_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # Bottom Buttons
        btn_frame = ttk.Frame(self, padding="10")
        btn_frame.pack(fill=tk.X)
        
        ttk.Button(btn_frame, text="Apply & Save", command=self._on_apply).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=10)
        if self.panel_keys:
            self.panel_listbox.selection_set(0)
            self.current_panel_key = self.panel_keys[0]
            self._load_properties(self.current_panel_key)

    def _format_panel_item(self, panel_key):
        panel = self.hud_panels[panel_key]
        visible = bool(panel.config.get('visible', True))
        mark = "☑" if visible else "☐"
        return f"{mark} {panel_key}"

    def _refresh_panel_list(self, selected_key=None):
        self.panel_keys = list(self.hud_panels.keys())
        self.panel_listbox.delete(0, tk.END)
        for key in self.panel_keys:
            self.panel_listbox.insert(tk.END, self._format_panel_item(key))
        if selected_key and selected_key in self.panel_keys:
            idx = self.panel_keys.index(selected_key)
            self.panel_listbox.selection_set(idx)
            self.panel_listbox.activate(idx)

    def _on_panel_click(self, event):
        idx = self.panel_listbox.nearest(event.y)
        if idx < 0 or idx >= len(self.panel_keys):
            return "break"

        panel_key = self.panel_keys[idx]
        if self.current_panel_key and self.current_panel_key != panel_key:
            self._save_current_panel()

        self.panel_listbox.selection_clear(0, tk.END)
        self.panel_listbox.selection_set(idx)
        self.panel_listbox.activate(idx)

        if event.x <= 24:
            panel = self.hud_panels[panel_key]
            visible = bool(panel.config.get('visible', True))
            panel.update_config({'visible': not visible})
            self._refresh_panel_list(selected_key=panel_key)

        self.current_panel_key = panel_key
        self._load_properties(panel_key)
        return "break"
        
    def _on_panel_select(self, event):
        # Save previous if any
        if self.current_panel_key:
            self._save_current_panel()
            
        selection = self.panel_listbox.curselection()
        if not selection:
            return
            
        panel_key = self.panel_keys[selection[0]]
        self.current_panel_key = panel_key
        self._load_properties(panel_key)
        
    def _load_properties(self, panel_key):
        # Clear existing widgets
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.entries = {}
        
        panel = self.hud_panels[panel_key]
        config = panel.config
        
        row = 0
        for key, value in config.items():
            ttk.Label(self.scrollable_frame, text=key).grid(row=row, column=0, sticky="w", pady=2)
            
            # Determine type and create appropriate widget
            if isinstance(value, bool):
                var = tk.BooleanVar(value=value)
                chk = ttk.Checkbutton(self.scrollable_frame, variable=var)
                chk.grid(row=row, column=1, sticky="w", pady=2)
                self.entries[key] = (var, 'bool')
            elif isinstance(value, (list, tuple)) and len(value) in (3, 4) and all(isinstance(v, (int, float)) for v in value):
                # Likely a color
                frame = ttk.Frame(self.scrollable_frame)
                frame.grid(row=row, column=1, sticky="ew", pady=2)
                
                var = tk.StringVar(value=str(value))
                entry = ttk.Entry(frame, textvariable=var)
                entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
                
                btn = ttk.Button(frame, text="Pick", width=4, 
                               command=lambda v=var: self._pick_color(v))
                btn.pack(side=tk.RIGHT, padx=2)
                
                self.entries[key] = (var, 'color')
            else:
                # Default text entry
                var = tk.StringVar(value=str(value))
                entry = ttk.Entry(self.scrollable_frame, textvariable=var)
                entry.grid(row=row, column=1, sticky="ew", pady=2)
                
                # Tag type for conversion
                if isinstance(value, int):
                    type_tag = 'int'
                elif isinstance(value, float):
                    type_tag = 'float'
                else:
                    type_tag = 'str'
                self.entries[key] = (var, type_tag)
                
            row += 1
            
    def _pick_color(self, var):
        # Try to parse current value for initial color
        try:
            curr = ast.literal_eval(var.get())
            # Convert to #RRGGBB
            if len(curr) >= 3:
                color = f"#{int(curr[0]):02x}{int(curr[1]):02x}{int(curr[2]):02x}"
            else:
                color = None
        except:
            color = None
            
        rgb, hex_color = colorchooser.askcolor(color=color, parent=self)
        if rgb:
            # Preserve alpha if it existed
            try:
                old_val = ast.literal_eval(var.get())
                if len(old_val) == 4:
                    new_val = (int(rgb[0]), int(rgb[1]), int(rgb[2]), old_val[3])
                else:
                    new_val = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            except:
                new_val = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            var.set(str(new_val))

    def _on_apply(self):
        if self.current_panel_key:
            self._save_current_panel()
        
        if self.on_apply_callback:
            self.on_apply_callback()
            
        messagebox.showinfo("Success", "Configuration applied and saved.")
        
    def _save_current_panel(self):
        if not self.current_panel_key:
            return
            
        panel = self.hud_panels[self.current_panel_key]
        new_config = {}
        
        for key, (var, type_tag) in self.entries.items():
            val_str = str(var.get())
            try:
                if type_tag == 'bool':
                    new_config[key] = var.get()
                elif type_tag == 'int':
                    new_config[key] = int(val_str)
                elif type_tag == 'float':
                    new_config[key] = float(val_str)
                elif type_tag == 'color':
                    # Use ast.literal_eval for safe tuple parsing
                    new_config[key] = ast.literal_eval(val_str)
                else:
                    new_config[key] = val_str
            except Exception as e:
                print(f"Error parsing {key}: {e}")
                # Keep old value on error? or warn?
                pass
                
        panel.update_config(new_config)
