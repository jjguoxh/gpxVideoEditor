import math
import cv2
import numpy as np
from .base import HudPanel

class Porsche911Panel(HudPanel):
    def __init__(self, config=None):
        super().__init__(config)
        self.config.update({
            'bg_color_outer': (10, 10, 10),    # Black outer ring
            'bg_color_inner': (220, 220, 220), # Silver inner dial
            'ring_color': (80, 80, 80),        # Dark bezel
            'tick_color': (240, 240, 240),     # White ticks (on outer ring)
            'text_color': (10, 10, 10),        # Black numbers (on silver dial)
            'needle_color_light': (240, 240, 240), # Silver needle light side
            'needle_color_dark': (160, 160, 160),  # Silver needle dark side
            'bg_alpha': 0.95,                  # High opacity
            'size_ratio': 0.35,
            'margin_left': 40,
            'margin_bottom': 60,
            'max_speed': 300.0
        })

    def _draw_impl(self, frame, data_context):
        speed = float(data_context.get('speed', 0.0) or 0.0)
        h, w = frame.shape[:2]

        rect = data_context.get('rect')
        if rect:
            x, y, rw, rh = rect
            size = max(150, min(rw, rh))
            # Center in rect
            x += (rw - size) // 2
            y += (rh - size) // 2
        else:
            # Default placement (bottom left)
            size = int(min(w, h) * self.config.get('size_ratio', 0.35))
            size = max(180, min(size, 400))
            x = int(self.config.get('margin_left', 40))
            y = int(h - size - self.config.get('margin_bottom', 60))

        # Clamp to frame
        x = max(0, min(x, w - size))
        y = max(0, min(y, h - size))

        if size < 100:
            return

        roi = frame[y:y + size, x:x + size]
        if roi.size == 0:
            return

        overlay = roi.copy()
        cx, cy = size // 2, size // 2
        
        # Radii definitions
        outer_r = int(size * 0.48)      # Total radius
        tick_ring_start_r = int(size * 0.36) # Where black ring starts
        inner_dial_r = int(size * 0.36) # Silver dial radius
        
        # 1. Outer Ring Background (Black)
        cv2.circle(overlay, (cx, cy), outer_r, self.config['bg_color_outer'], -1, cv2.LINE_AA)
        
        # 2. Inner Dial Background (Silver)
        cv2.circle(overlay, (cx, cy), inner_dial_r, self.config['bg_color_inner'], -1, cv2.LINE_AA)
        
        # 3. Outer Bezel Border (Dark Grey)
        bezel_thickness = max(2, int(size * 0.015))
        cv2.circle(overlay, (cx, cy), outer_r, self.config['ring_color'], bezel_thickness, cv2.LINE_AA)
        
        # Separator ring (between silver and black)
        cv2.circle(overlay, (cx, cy), inner_dial_r, (100, 100, 100), 1, cv2.LINE_AA)

        # Blend background transparency
        alpha = float(self.config.get('bg_alpha', 0.95))
        cv2.addWeighted(overlay, alpha, roi, 1.0 - alpha, 0, roi)

        # 4. Ticks (On Outer Black Ring) and Numbers (On Inner Silver Dial)
        start_angle = 135.0
        sweep_angle = 270.0
        max_speed = max(1.0, float(self.config.get('max_speed', 300.0)))
        
        tick_step_major = 50
        tick_step_minor = 10
        
        # Ticks are in the outer ring (between inner_dial_r and outer_r)
        tick_outer_r = int(size * 0.46)
        tick_len_major = int(size * 0.08)
        tick_len_minor = int(size * 0.05)
        
        steps = int(max_speed / tick_step_minor)
        
        for i in range(steps + 1):
            val = i * tick_step_minor
            ratio = val / max_speed
            angle_deg = start_angle + sweep_angle * ratio
            angle_rad = math.radians(angle_deg)
            
            is_major = (val % tick_step_major == 0)
            
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            
            # Draw Ticks (White on Black Ring)
            r_start = tick_outer_r
            r_end = r_start - (tick_len_major if is_major else tick_len_minor)
            
            p1 = (int(cx + r_start * cos_a), int(cy + r_start * sin_a))
            p2 = (int(cx + r_end * cos_a), int(cy + r_end * sin_a))
            
            thickness = 2 if is_major else 1
            cv2.line(roi, p1, p2, self.config['tick_color'], thickness, cv2.LINE_AA)
            
            # Draw Numbers (Black on Silver Dial)
            if is_major:
                # Text position (inside the silver area)
                r_text = int(size * 0.26) 
                tx = int(cx + r_text * cos_a)
                ty = int(cy + r_text * sin_a)
                
                text = str(val)
                font_scale = size / 420.0
                font = cv2.FONT_HERSHEY_DUPLEX
                thickness_text = 1
                
                (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness_text)
                
                # Center text
                tx -= tw // 2
                ty += th // 2
                
                cv2.putText(roi, text, (tx, ty), font, font_scale, self.config['text_color'], thickness_text, cv2.LINE_AA)

        # 5. "km/h" label (On Silver Dial)
        label = "km/h"
        font_scale_label = size / 550.0
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale_label, 1)
        cv2.putText(roi, label, (cx - lw // 2, cy + int(size * 0.15)), cv2.FONT_HERSHEY_SIMPLEX, font_scale_label, (50, 50, 50), 1, cv2.LINE_AA)

        # 6. Needle (Silver, 3D Metallic)
        speed_clamped = max(0, min(speed, max_speed))
        needle_ratio = speed_clamped / max_speed
        needle_angle_deg = start_angle + sweep_angle * needle_ratio
        needle_angle_rad = math.radians(needle_angle_deg)
        
        needle_len = int(size * 0.42) # Extends into the ticks area
        needle_w = int(size * 0.03)   # Slightly wider for 3D effect
        
        # Tip
        tip_x = int(cx + needle_len * math.cos(needle_angle_rad))
        tip_y = int(cy + needle_len * math.sin(needle_angle_rad))
        
        # Base points
        base_angle_rad = needle_angle_rad + math.pi / 2
        bx1 = int(cx + needle_w * math.cos(base_angle_rad))
        by1 = int(cy + needle_w * math.sin(base_angle_rad))
        bx2 = int(cx - needle_w * math.cos(base_angle_rad))
        by2 = int(cy - needle_w * math.sin(base_angle_rad))
        
        # Center point for split (slightly offset from actual center towards tip for 3D look?)
        # Actually just splitting the triangle into two halves
        
        # Left half (lighter)
        pts_light = np.array([[cx, cy], [bx1, by1], [tip_x, tip_y]], np.int32)
        cv2.fillConvexPoly(roi, pts_light, self.config['needle_color_light'], cv2.LINE_AA)
        
        # Right half (darker)
        pts_dark = np.array([[cx, cy], [bx2, by2], [tip_x, tip_y]], np.int32)
        cv2.fillConvexPoly(roi, pts_dark, self.config['needle_color_dark'], cv2.LINE_AA)
        
        # 7. Center Cap (Chrome/Silver)
        cap_r = int(size * 0.08)
        # Outer rim of cap
        cv2.circle(roi, (cx, cy), cap_r, (180, 180, 180), -1, cv2.LINE_AA)
        # Inner part
        cv2.circle(roi, (cx, cy), int(cap_r * 0.8), (230, 230, 230), -1, cv2.LINE_AA)
        # Center dot
        cv2.circle(roi, (cx, cy), int(cap_r * 0.2), (100, 100, 100), -1, cv2.LINE_AA)
