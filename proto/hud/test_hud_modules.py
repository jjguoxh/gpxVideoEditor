import cv2
import tkinter as tk
from tkinter import ttk
import numpy as np
import time
import math
import sys
from pathlib import Path
from PIL import Image, ImageTk

# Add HUD directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load HUD modules
try:
    from hud.base import HudPanel
    from hud.elevation import ElevationPanel
    from hud.telemetry import TelemetryPanel
    from hud.speedometer import SpeedometerPanel
    from hud.track import TrackPanel
    from hud.porsche911 import Porsche911Panel
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

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
        
        # Initialize HUD panels
        self.hud_panels = {
            'speedometer': SpeedometerPanel(),
            'porsche911': Porsche911Panel(),
            'elevation': ElevationPanel(),
            'telemetry': TelemetryPanel(),
            'track': TrackPanel()
        }
        
        # Create UI
        self.create_ui()
        
        # Start loop
        self.last_update_time = time.time()
        self.update_loop()
        
    def create_ui(self):
        # Top control frame
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Panel Selection
        ttk.Label(control_frame, text="Active Panel:").pack(side=tk.LEFT)
        self.panel_var = tk.StringVar(value='speedometer')
        
        for name in self.hud_panels.keys():
            rb = ttk.Radiobutton(control_frame, text=name.capitalize(), 
                               variable=self.panel_var, value=name)
            rb.pack(side=tk.LEFT, padx=5)
            
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
        
        # Canvas for preview
        self.canvas_frame = ttk.Frame(self.root)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.canvas = tk.Canvas(self.canvas_frame, bg='black')
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Bind resize event
        self.canvas.bind('<Configure>', self.on_resize)
        
    def toggle_play(self):
        self.is_playing = not self.is_playing
        self.play_btn.config(text="Pause" if self.is_playing else "Play")
        
    def on_resize(self, event):
        # Just store the size, the update loop will handle scaling
        self.canvas_width = event.width
        self.canvas_height = event.height
        
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
        
        # Draw selected panel
        panel_name = self.panel_var.get()
        panel = self.hud_panels.get(panel_name)
        
        if panel:
            # We can define a rect for the panel to simulate layout
            # For testing, let's give it a reasonable area or full screen depending on panel
            # Some panels use 'rect' from context, others use internal config
            
            # Let's try to simulate the layout rect used in the main app
            # Center the panel
            margin = 50
            w = self.frame_width - 2 * margin
            h = self.frame_height - 2 * margin
            
            # Update context with rect
            context['rect'] = (margin, margin, w, h)
            
            try:
                panel.draw(frame, context)
            except Exception as e:
                print(f"Error drawing {panel_name}: {e}")
                import traceback
                traceback.print_exc()

        # Convert to ImageTk
        # Resize to fit canvas
        c_w = self.canvas.winfo_width()
        c_h = self.canvas.winfo_height()
        
        if c_w > 1 and c_h > 1:
            scale = min(c_w / self.frame_width, c_h / self.frame_height)
            new_w = int(self.frame_width * scale)
            new_h = int(self.frame_height * scale)
            
            resized = cv2.resize(frame, (new_w, new_h))
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            self.photo = ImageTk.PhotoImage(image=img)
            
            self.canvas.delete("all")
            # Center image
            x = (c_w - new_w) // 2
            y = (c_h - new_h) // 2
            self.canvas.create_image(x, y, anchor=tk.NW, image=self.photo)
            
            # Draw debug info
            self.canvas.create_text(10, 10, anchor=tk.NW, fill='white', 
                                  text=f"Time: {self.current_time:.1f}s / {self.mock_data.duration:.1f}s\n"
                                       f"Speed: {context['speed']:.1f} km/h\n"
                                       f"Ele: {context['ele']:.1f} m\n"
                                       f"Grade: {context['grade']:.1f} %")
        
        # Schedule next update (30 FPS)
        self.root.after(33, self.update_loop)

if __name__ == "__main__":
    root = tk.Tk()
    app = HUDTestApp(root)
    root.mainloop()
