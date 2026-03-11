import math
import cv2
from .base import HudPanel


class SpeedometerPanel(HudPanel):
    def __init__(self, config=None):
        super().__init__(config)
        self.config.update({
            'bg_color': (18, 18, 18),
            'ring_color': (245, 245, 245),
            'inactive_color': (80, 80, 80),
            'accent_color': (50, 74, 244),
            'text_color': (245, 245, 245),
            'sub_text_color': (180, 180, 180),
            'bg_alpha': 0.68,
            'size_ratio': 0.24,
            'margin_left': 24,
            'margin_bottom': 140,
            'max_speed': 60.0
        })

    def _draw_impl(self, frame, data_context):
        speed = float(data_context.get('speed', 0.0) or 0.0)
        h, w = frame.shape[:2]

        rect = data_context.get('rect')
        if rect:
            x, y, rw, rh = rect
            size = max(120, min(rw, rh))
            # Center in the provided rect
            x += (rw - size) // 2
            y += (rh - size) // 2
        else:
            size = int(min(w, h) * self.config.get('size_ratio', 0.24))
            size = max(150, min(size, 320))
            x = int(self.config.get('margin_left', 24))
            y = int(h - size - self.config.get('margin_bottom', 140))

        x = max(0, min(x, w - size))
        y = max(0, min(y, h - size))
        if size < 120:
            return

        roi = frame[y:y + size, x:x + size]
        if roi.size == 0:
            return

        overlay = roi.copy()
        cx = size // 2
        cy = size // 2
        outer_r = int(size * 0.48)
        ring_r = int(size * 0.41)
        inner_r = int(size * 0.30)

        cv2.circle(overlay, (cx, cy), outer_r, self.config['bg_color'], -1, cv2.LINE_AA)
        alpha = float(self.config.get('bg_alpha', 0.68))
        cv2.addWeighted(overlay, alpha, roi, 1.0 - alpha, 0, roi)

        start_angle = 150.0
        sweep = 240.0
        max_speed = max(1.0, float(self.config.get('max_speed', 60.0)))
        ratio = max(0.0, min(1.0, speed / max_speed))
        active_angle = start_angle + sweep * ratio

        ring_thickness = max(2, int(size * 0.045))
        cv2.ellipse(
            roi,
            (cx, cy),
            (ring_r, ring_r),
            0,
            start_angle,
            start_angle + sweep,
            self.config['inactive_color'],
            ring_thickness,
            cv2.LINE_AA
        )
        cv2.ellipse(
            roi,
            (cx, cy),
            (ring_r, ring_r),
            0,
            start_angle,
            active_angle,
            self.config['accent_color'],
            ring_thickness,
            cv2.LINE_AA
        )

        tick_count = 30
        for i in range(tick_count + 1):
            t = i / tick_count
            ang = math.radians(start_angle + sweep * t)
            is_major = (i % 5 == 0)
            r1 = ring_r - (int(size * (0.055 if is_major else 0.03)))
            r2 = ring_r + (int(size * 0.018))
            x1 = int(cx + r1 * math.cos(ang))
            y1 = int(cy + r1 * math.sin(ang))
            x2 = int(cx + r2 * math.cos(ang))
            y2 = int(cy + r2 * math.sin(ang))
            color = self.config['ring_color'] if t <= ratio else self.config['inactive_color']
            th = 2 if is_major else 1
            cv2.line(roi, (x1, y1), (x2, y2), color, th, cv2.LINE_AA)

        # Draw red pointer
        pointer_angle = math.radians(start_angle + sweep * ratio)
        pointer_len = int(ring_r * 0.9)
        px = int(cx + pointer_len * math.cos(pointer_angle))
        py = int(cy + pointer_len * math.sin(pointer_angle))
        cv2.line(roi, (cx, cy), (px, py), (0, 0, 255), max(2, int(size * 0.02)), cv2.LINE_AA)

        cv2.circle(roi, (cx, cy), inner_r, (36, 36, 36), -1, cv2.LINE_AA)
        cv2.circle(roi, (cx, cy), inner_r, (110, 110, 110), 1, cv2.LINE_AA)

        speed_text = f"{int(round(speed))}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale_main = max(0.9, size / 155.0) * self.config.get('font_scale', 1.0)
        thickness_main = max(2, int(scale_main * 2.4))
        (tw, th), _ = cv2.getTextSize(speed_text, font, scale_main, thickness_main)
        tx = cx - tw // 2
        ty = cy + th // 2 - int(size * 0.02)
        cv2.putText(roi, speed_text, (tx, ty), font, scale_main, self.config['text_color'], thickness_main, cv2.LINE_AA)

        unit_text = "KM/H"
        scale_sub = max(0.35, size / 420.0) * self.config.get('font_scale', 1.0)
        (uw, uh), _ = cv2.getTextSize(unit_text, font, scale_sub, 1)
        ux = cx - uw // 2
        uy = ty + int(size * 0.11)
        cv2.putText(roi, unit_text, (ux, uy), font, scale_sub, self.config['sub_text_color'], 1, cv2.LINE_AA)

        min_text = "0"
        max_text = f"{int(max_speed)}"
        min_ang = math.radians(start_angle)
        max_ang = math.radians(start_angle + sweep)
        label_r = ring_r + int(size * 0.08)
        min_pos = (int(cx + label_r * math.cos(min_ang)) - 8, int(cy + label_r * math.sin(min_ang)) + 5)
        max_pos = (int(cx + label_r * math.cos(max_ang)) - 12, int(cy + label_r * math.sin(max_ang)) + 5)
        cv2.putText(roi, min_text, min_pos, font, scale_sub, self.config['sub_text_color'], 1, cv2.LINE_AA)
        cv2.putText(roi, max_text, max_pos, font, scale_sub, self.config['sub_text_color'], 1, cv2.LINE_AA)
