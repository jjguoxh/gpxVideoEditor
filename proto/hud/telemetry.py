# Telemetry Panel (Speed, Elevation, Slope) with futuristic design

import math
import numpy as np
import cv2
from .base import HudPanel

class TelemetryPanel(HudPanel):
    def __init__(self, config=None):
        super().__init__(config)
        self.config.update({
            'bg_color': (200, 200, 200),  # Hexagon fill
            'line_color': (255, 255, 255), # Hexagon border
            'text_color_val': (255, 255, 255),
            'text_color_lbl': (220, 220, 220),
            'shadow_color': (0, 0, 0),
            'speed_color': (255, 255, 255),
            'bar_color_active': (255, 255, 255),
            'bar_color_inactive': (100, 100, 100),
            'max_speed': 60.0
        })

    def _draw_impl(self, frame, data_context):
        """
        Draw futuristic HUD panel.
        data_context needs: 'rect', 'current_seconds', 'speed', 'ele', 'grade'
        """
        h, w = frame.shape[:2]
        x, y, ww, hh = data_context.get('rect', (0, 0, 0, 0))
        
        if ww < 50 or hh < 50:
            return

        # Get data
        speed = data_context.get('speed', 0.0)
        ele = data_context.get('ele', 0.0)
        grade = data_context.get('grade', 0.0)
        
        if ele is None: ele = 0.0
        if grade is None: grade = 0.0
        
        # --- Layout Calculation ---
        # Vertical split: Top 60% for speed, Bottom 40% for hexagons
        split_y = y + int(hh * 0.6)
        
        # --- 1. Speed Area (Top) ---
        speed_center_y = y + int((split_y - y) * 0.4)
        
        font = cv2.FONT_HERSHEY_SIMPLEX
        # Font size dynamic adjustment
        font_scale_speed = min(ww, hh) / 100.0 * 0.9 * self.config.get('font_scale', 1.0)
        speed_str = f"{int(speed)}"
        (tw, th), base = cv2.getTextSize(speed_str, font, font_scale_speed, 3)
        
        # Speed value position (centered right)
        tx = x + ww // 2 - tw // 2 + int(ww * 0.1) 
        ty = speed_center_y + th // 2
        
        # Shadow/Outline (bold effect)
        cv2.putText(frame, speed_str, (tx+2, ty+2), font, font_scale_speed, self.config['shadow_color'], 6, cv2.LINE_AA)
        cv2.putText(frame, speed_str, (tx, ty), font, font_scale_speed, self.config['speed_color'], 3, cv2.LINE_AA)
        
        # Unit KM/H (left of speed)
        unit_str = "KM/H"
        font_scale_unit = font_scale_speed * 0.3
        (uw, uh), _ = cv2.getTextSize(unit_str, font, font_scale_unit, 1)
        ux = tx - uw - 15
        uy = ty
        cv2.putText(frame, unit_str, (ux+1, uy+1), font, font_scale_unit, self.config['shadow_color'], 2, cv2.LINE_AA)
        cv2.putText(frame, unit_str, (ux, uy), font, font_scale_unit, self.config['bg_color'], 1, cv2.LINE_AA)
        
        # Decorative lines (Top Left)
        line_color = self.config['bg_color']
        cv2.line(frame, (ux - 10, uy - uh), (ux - 10, uy + 5), line_color, 2, cv2.LINE_AA)
        cv2.line(frame, (ux - 10, uy - uh), (ux + 20, uy - uh), line_color, 2, cv2.LINE_AA)
        
        # --- Speed Bar (Bottom of Speed Area) ---
        bar_y_start = ty + 15
        bar_area_h = split_y - bar_y_start - 5
        if bar_area_h < 10: bar_area_h = 10
        
        bar_area_w = int(ww * 0.9)
        bar_x_start = x + (ww - bar_area_w) // 2
        
        num_bars = 20
        gap = 3
        bar_w = (bar_area_w - (num_bars - 1) * gap) / num_bars
        
        max_speed_disp = self.config['max_speed']
        ratio = min(1.0, speed / max_speed_disp)
        active_bars = int(num_bars * ratio)
        
        # Speed Bar Frame Decoration
        # Left Bracket
        cv2.line(frame, (bar_x_start - 5, bar_y_start), (bar_x_start - 5, bar_y_start + bar_area_h), line_color, 2, cv2.LINE_AA)
        cv2.line(frame, (bar_x_start - 5, bar_y_start + bar_area_h), (bar_x_start + 10, bar_y_start + bar_area_h), line_color, 2, cv2.LINE_AA)
        # Right Bracket
        cv2.line(frame, (bar_x_start + bar_area_w + 5, bar_y_start), (bar_x_start + bar_area_w + 5, bar_y_start + bar_area_h), line_color, 2, cv2.LINE_AA)
        cv2.line(frame, (bar_x_start + bar_area_w + 5, bar_y_start + bar_area_h), (bar_x_start + bar_area_w - 10, bar_y_start + bar_area_h), line_color, 2, cv2.LINE_AA)

        for i in range(num_bars):
            bx = int(bar_x_start + i * (bar_w + gap))
            by = bar_y_start
            
            pt1 = (bx, by)
            pt2 = (int(bx + bar_w), by + bar_area_h)
            
            if i < active_bars:
                # Active (Filled)
                cv2.rectangle(frame, pt1, pt2, self.config['bar_color_active'], -1)
            else:
                # Inactive (Outline)
                cv2.rectangle(frame, pt1, pt2, self.config['bar_color_inactive'], 1)

        # --- 2. Bottom Area: Hexagons (Elevation & Slope) ---
        hex_y_center = split_y + (y + hh - split_y) // 2
        hex_radius = int(min((y + hh - split_y) * 0.45, ww * 0.22))
        
        # Calculate horizontal join distance
        # Hex width = 2 * radius * cos(30) = sqrt(3) * radius
        # Join distance = sqrt(3) * radius
        hex_dist = int(hex_radius * math.sqrt(3))
        
        # Two hexagon centers
        hex1_cx = x + ww // 2 - hex_dist // 2 + 1  # +1 to cover gap
        hex2_cx = x + ww // 2 + hex_dist // 2 - 1
        
        # Draw Hexagon 1 (Elevation)
        self._draw_hex_stat(frame, (hex1_cx, hex_y_center), hex_radius, f"{int(ele)}", "ALT m")
        
        # Draw Hexagon 2 (Slope)
        self._draw_hex_stat(frame, (hex2_cx, hex_y_center), hex_radius, f"{grade:.1f}", "SLOPE %")

    def _draw_hex_stat(self, frame, center, radius, value, label):
        """Draw hexagon status display (HUD component)"""
        cx, cy = center
        # Generate hexagon vertices (point up)
        pts = []
        for i in range(6):
            angle_deg = 60 * i + 30
            angle_rad = math.radians(angle_deg)
            px = int(cx + radius * math.cos(angle_rad))
            py = int(cy + radius * math.sin(angle_rad))
            pts.append([px, py])
            
        pts = np.array(pts, np.int32).reshape((-1, 1, 2))
        
        # 1. Semi-transparent fill
        overlay = frame.copy()
        cv2.fillPoly(overlay, [pts], self.config['bg_color']) 
        # Blend mode: overlay * 0.3 + frame * 0.7
        cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
        
        # 2. Border
        cv2.polylines(frame, [pts], True, self.config['line_color'], 2, cv2.LINE_AA)
        
        # 3. Text
        font = cv2.FONT_HERSHEY_SIMPLEX
        
        # Value (Centered)
        # Dynamic font size (smaller, /45 instead of /30)
        font_scale_val = radius / 45.0 * self.config.get('font_scale', 1.0)
        if font_scale_val < 0.35: font_scale_val = 0.35
        
        thickness = max(1, int(font_scale_val * 2))
        (tw, th), base = cv2.getTextSize(str(value), font, font_scale_val, thickness)
        cv2.putText(frame, str(value), (int(cx - tw/2), int(cy + th/2)), font, font_scale_val, self.config['text_color_val'], thickness, cv2.LINE_AA)
        
        # Label (Bottom)
        font_scale_lbl = radius / 50.0 * self.config.get('font_scale', 1.0)
        if font_scale_lbl < 0.3: font_scale_lbl = 0.3
        
        (tw2, th2), base2 = cv2.getTextSize(label, font, font_scale_lbl, 1)
        cv2.putText(frame, label, (int(cx - tw2/2), int(cy + radius*0.6)), font, font_scale_lbl, self.config['text_color_lbl'], 1, cv2.LINE_AA)
