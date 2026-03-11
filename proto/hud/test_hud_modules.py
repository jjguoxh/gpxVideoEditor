import cv2
import tkinter as tk
from tkinter import ttk
import numpy as np
import time
import math
import sys
from pathlib import Path
from PIL import Image, ImageTk
import importlib.util
import types

# Add HUD directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from hud.base import HudPanel
    import hud.base as hud_base_module
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

HUD_ROOT = Path(__file__).resolve().parent

class MockDataGenerator:
    def __init__(self, duration=600):
        self.duration = duration
        self.segments = []
        self.smoothed_segments = []
        self.lats = []
        self.lons = []
        self.eles = []
        self.grades = []
        
        # Generate a circular track
        center_lat = 40.0
        center_lon = 116.0
        radius_m = 1000.0
        
        # Approximate meters per degree
        m_per_deg_lat = 111320.0
        m_per_deg_lon = 111320.0 * math.cos(math.radians(center_lat))
        
        # Variable Speed Logic
        total_len = 2 * math.pi * radius_m
        current_dist = 0.0
        
        steps = duration
        for t in range(steps + 1):
            # Speed (km/h) varies 0 -> 120 -> 0 -> 120
            # Sine wave based on time
            speed_kph = 60.0 + 60.0 * math.sin(t / duration * 4 * math.pi - math.pi/2)
            speed_kph = max(0, speed_kph)
            speed_mps = speed_kph / 3.6
            
            dist_step = speed_mps * 1.0 # 1 sec per step
            current_dist += dist_step
            
            angle = (current_dist / total_len) * 2 * math.pi
            
            # Position
            d_lat = (math.sin(angle) * radius_m) / m_per_deg_lat
            d_lon = (math.cos(angle) * radius_m) / m_per_deg_lon
            
            lat = center_lat + d_lat
            lon = center_lon + d_lon
            
            # Elevation (sine wave)
            ele = 100.0 + 50.0 * math.sin(angle * 2)
            
            self.lats.append(lat)
            self.lons.append(lon)
            self.eles.append(ele)
            
            # Segment
            if t > 0:
                prev_lat = self.lats[-2]
                prev_lon = self.lons[-2]
                prev_ele = self.eles[-2]
                
                # Use calculated speed
                grade = (ele - prev_ele) / dist_step * 100 if dist_step > 0.1 else 0
                self.grades.append(grade)

                seg = {
                    'start': float(t-1),
                    'end': float(t),
                    'lat': lat,
                    'lon': lon,
                    'ele_start': prev_ele,
                    'ele_end': ele,
                    'speed': speed_kph,
                    'grade': grade,
                    'heading': (math.degrees(math.atan2(d_lon, d_lat)) + 360) % 360
                }
                self.segments.append(seg)
                self.smoothed_segments.append(seg)

    def get_context(self, current_time):
        idx = int(current_time)
        idx = max(0, min(idx, len(self.segments) - 1))
        
        seg = self.segments[idx]
        
        return {
            'gpx_data': {
                'segments': self.segments,
                'smoothed_segments': self.smoothed_segments
            },
            'video_duration': float(self.duration),
            'gpx_offset': 0.0,
            'current_seconds': current_time,
            'speed': seg['speed'], # Base speed from track
            'ele': self.eles[idx],
            'grade': seg['grade'],
            'current_state': (self.lats[idx], self.lons[idx], seg['heading']),
            'last_idx': idx,
            'smooth_lats': np.array(self.lats),
            'smooth_lons': np.array(self.lons)
        }

def _ensure_hud_subpackage(subdir_path: Path):
    pkg_name = f"hud.{subdir_path.name}"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(subdir_path)]
        sys.modules[pkg_name] = pkg
    sys.modules[f"{pkg_name}.base"] = hud_base_module
    return pkg_name

def _load_module_from_file(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {module_name} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

def _find_panel_classes(module):
    panel_classes = []
    for obj in module.__dict__.values():
        if isinstance(obj, type) and issubclass(obj, HudPanel) and obj is not HudPanel:
            panel_classes.append(obj)
    panel_classes.sort(key=lambda c: c.__name__)
    return panel_classes

def discover_hud_panels():
    discovered = []
    for subdir in sorted([p for p in HUD_ROOT.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
        if subdir.name.startswith('__'):
            continue
        if subdir.name in ('.git', '.venv'):
            continue

        py_files = sorted(
            [p for p in subdir.glob("*.py") if p.is_file() and p.name not in ("__init__.py", "base.py")],
            key=lambda p: p.name.lower()
        )
        if not py_files:
            continue

        pkg_name = _ensure_hud_subpackage(subdir)
        for py_file in py_files:
            module_name = f"{pkg_name}.{py_file.stem}"
            try:
                module = _load_module_from_file(module_name, py_file)
                panel_classes = _find_panel_classes(module)
                if not panel_classes:
                    discovered.append({
                        'group': subdir.name,
                        'module': py_file.stem,
                        'panel_name': None,
                        'panel': None,
                        'error': f"No HudPanel subclass found in {py_file.name}"
                    })
                    continue
                panel_cls = panel_classes[0]
                panel = panel_cls()
                discovered.append({
                    'group': subdir.name,
                    'module': py_file.stem,
                    'panel_name': panel_cls.__name__,
                    'panel': panel,
                    'error': None
                })
            except Exception as e:
                discovered.append({
                    'group': subdir.name,
                    'module': py_file.stem,
                    'panel_name': None,
                    'panel': None,
                    'error': str(e)
                })
    return discovered

class HUDTestApp:
    def __init__(self, root):
        self.root = root
        self.root.title("HUD Module Test")
        self.root.geometry("1000x800")
        
        # Initialize mock data
        self.mock_data = MockDataGenerator()
        
        # Simulation state
        self.current_time = 0.0
        self.is_playing = True
        self.speed_multiplier = 1.0 # Simulation speed
        self.simulated_speed_factor = 1.0 # Factor to adjust displayed speed
        
        # Frame buffer (1280x720)
        self.frame_width = 1280
        self.frame_height = 720
        self.bg_color = (50, 50, 50) # Dark gray background

        self.hud_entries = discover_hud_panels()
        self._ui_pages = {}
        self._active_canvas = None
        self._active_panel = None
        self._active_error = None
        
        # Create UI
        self.create_ui()
        
        # Start loop
        self.last_update_time = time.time()
        self.update_loop()
        
    def create_ui(self):
        # Top control frame
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
            
        # Simulation Controls
        sim_frame = ttk.LabelFrame(self.root, text="Simulation Control")
        sim_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Play/Pause
        self.play_btn = ttk.Button(sim_frame, text="Pause", command=self.toggle_play)
        self.play_btn.pack(side=tk.LEFT, padx=5)
        
        # Speed Multiplier (Simulation Speed)
        ttk.Label(sim_frame, text="Time Speed:").pack(side=tk.LEFT, padx=5)
        self.time_speed_scale = ttk.Scale(sim_frame, from_=0.1, to=10.0, value=1.0, 
                                        command=lambda v: setattr(self, 'speed_multiplier', float(v)))
        self.time_speed_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Simulated Speed Factor (Effect on HUD Speed value)
        ttk.Label(sim_frame, text="Speed Factor:").pack(side=tk.LEFT, padx=5)
        self.speed_factor_scale = ttk.Scale(sim_frame, from_=0.0, to=2.0, value=1.0,
                                          command=lambda v: setattr(self, 'simulated_speed_factor', float(v)))
        self.speed_factor_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        groups = {}
        for entry in self.hud_entries:
            groups.setdefault(entry['group'], []).append(entry)

        for group_name in sorted(groups.keys(), key=lambda s: s.lower()):
            group_frame = ttk.Frame(self.notebook)
            self.notebook.add(group_frame, text=group_name)

            inner = ttk.Notebook(group_frame)
            inner.pack(fill=tk.BOTH, expand=True)

            for entry in sorted(groups[group_name], key=lambda e: e['module'].lower()):
                tab_title = entry['module']
                tab_frame = ttk.Frame(inner)
                inner.add(tab_frame, text=tab_title)

                canvas = tk.Canvas(tab_frame, bg='black')
                canvas.pack(fill=tk.BOTH, expand=True)
                canvas.bind('<Configure>', self.on_resize)

                error_label = ttk.Label(tab_frame, text="", foreground="red")
                error_label.pack(anchor=tk.W, padx=8, pady=6)

                self._ui_pages[(group_name, entry['module'])] = {
                    'canvas': canvas,
                    'image_item': None,
                    'photo': None,
                    'panel': entry['panel'],
                    'error': entry['error'],
                    'error_label': error_label
                }

            inner.bind("<<NotebookTabChanged>>", lambda e: self._refresh_active_page())

        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._refresh_active_page())
        self.root.after(0, self._refresh_active_page)
        
    def toggle_play(self):
        self.is_playing = not self.is_playing
        self.play_btn.config(text="Pause" if self.is_playing else "Play")
        
    def on_resize(self, event):
        pass

    def _refresh_active_page(self):
        try:
            group_tab_id = self.notebook.select()
            if not group_tab_id:
                return
            group_frame = self.root.nametowidget(group_tab_id)
            inner = None
            for child in group_frame.winfo_children():
                if isinstance(child, ttk.Notebook):
                    inner = child
                    break
            if inner is None:
                return
            module_tab_id = inner.select()
            if not module_tab_id:
                return
            module_title = inner.tab(module_tab_id, "text")
            group_title = self.notebook.tab(group_tab_id, "text")
            page = self._ui_pages.get((group_title, module_title))
            if not page:
                return
            self._active_canvas = page['canvas']
            self._active_panel = page['panel']
            self._active_error = page['error']
            page['error_label'].config(text=page['error'] or "")
        except Exception:
            pass
        
    def update_loop(self):
        now = time.time()
        dt = now - self.last_update_time
        self.last_update_time = now
        
        if self.is_playing:
            self.current_time += dt * self.speed_multiplier
            if self.current_time >= self.mock_data.duration:
                self.current_time = 0
                
        # Get context
        context = self.mock_data.get_context(self.current_time)
        
        # Apply manual speed factor simulation
        context['speed'] *= self.simulated_speed_factor
        
        # Prepare frame
        frame = np.full((self.frame_height, self.frame_width, 3), self.bg_color, dtype=np.uint8)
        
        canvas = self._active_canvas
        panel = self._active_panel
        if panel is not None and canvas is not None and not self._active_error:
            margin = 50
            w = self.frame_width - 2 * margin
            h = self.frame_height - 2 * margin
            context['rect'] = (margin, margin, w, h)
            try:
                panel.draw(frame, context)
            except Exception:
                pass

        # Convert to ImageTk
        # Resize to fit canvas
        c_w = canvas.winfo_width() if canvas is not None else 0
        c_h = canvas.winfo_height() if canvas is not None else 0
        
        if c_w > 1 and c_h > 1:
            scale = min(c_w / self.frame_width, c_h / self.frame_height)
            new_w = int(self.frame_width * scale)
            new_h = int(self.frame_height * scale)
            
            resized = cv2.resize(frame, (new_w, new_h))
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            photo = ImageTk.PhotoImage(image=img)
            x = (c_w - new_w) // 2
            y = (c_h - new_h) // 2

            page = None
            try:
                group_tab_id = self.notebook.select()
                group_title = self.notebook.tab(group_tab_id, "text") if group_tab_id else None
                group_frame = self.root.nametowidget(group_tab_id) if group_tab_id else None
                inner = None
                if group_frame is not None:
                    for child in group_frame.winfo_children():
                        if isinstance(child, ttk.Notebook):
                            inner = child
                            break
                module_tab_id = inner.select() if inner is not None else None
                module_title = inner.tab(module_tab_id, "text") if module_tab_id else None
                if group_title and module_title:
                    page = self._ui_pages.get((group_title, module_title))
            except Exception:
                page = None

            if page is not None:
                page['photo'] = photo
                if page['image_item'] is None:
                    page['image_item'] = canvas.create_image(x, y, anchor=tk.NW, image=photo)
                else:
                    canvas.coords(page['image_item'], x, y)
                    canvas.itemconfig(page['image_item'], image=photo)
        
        # Schedule next update (30 FPS)
        self.root.after(33, self.update_loop)

if __name__ == "__main__":
    root = tk.Tk()
    app = HUDTestApp(root)
    root.mainloop()
