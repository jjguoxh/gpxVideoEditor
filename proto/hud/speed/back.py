import math
import cv2
import numpy as np
import os
from ..base import HudPanel

class BackPanel(HudPanel):
    def __init__(self, config=None):
        super().__init__(config)
        default_path = os.path.join(os.path.dirname(__file__), 'back.png')
        fallback_path = os.path.join(os.path.dirname(__file__), 'black.png')
        if not os.path.exists(default_path) and os.path.exists(fallback_path):
            default_path = fallback_path
        self.config.update({
            'bg_image_path': default_path,
            'size_ratio': 0.32,
            'margin_left': 36,
            'margin_bottom': 80,
            'max_speed': 240.0,
            'start_angle': 140.0,
            'sweep_angle': 260.0,
            'needle_color': (220, 40, 40),
            'digital_color': (245, 245, 245),
            'unit_color': (180, 180, 180),
            'inpaint_enabled': True,
            'inpaint_angle': 135.0,
            'inpaint_radius_ratio': 0.9,
            'inpaint_thickness_ratio': 0.08
        })
        self.bg_image = None
        self.bg_cache = {}

    def _load_bg(self, size):
        if size in self.bg_cache:
            return self.bg_cache[size]
        if self.bg_image is None:
            path = self.config.get('bg_image_path')
            if path and os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                if img is not None:
                    self.bg_image = img
        if self.bg_image is None:
            out = np.zeros((size, size, 3), dtype=np.uint8)
            self.bg_cache[size] = out
            return out
        h, w = self.bg_image.shape[:2]
        crop = self.bg_image
        if h != w:
            s = min(h, w)
            cy, cx = h // 2, w // 2
            y1 = max(0, cy - s // 2)
            x1 = max(0, cx - s // 2)
            crop = self.bg_image[y1:y1+s, x1:x1+s]
        resized = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
        if resized.shape[2] == 4:
            bgr = resized[:, :, :3].copy()
            alpha = resized[:, :, 3]
        else:
            bgr = resized.copy()
            alpha = None

        if self.config.get('inpaint_enabled', True):
            mask = np.zeros((size, size), dtype=np.uint8)
            cx, cy = size // 2, size // 2
            r = int(size * float(self.config.get('inpaint_radius_ratio', 0.9)) * 0.49 / 0.49)
            ang = math.radians(float(self.config.get('inpaint_angle', 135.0)))
            tx = int(cx + r * math.cos(ang))
            ty = int(cy + r * math.sin(ang))
            thickness = max(3, int(size * float(self.config.get('inpaint_thickness_ratio', 0.08))))
            cv2.line(mask, (cx, cy), (tx, ty), 255, thickness)
            cv2.circle(mask, (cx, cy), max(6, thickness // 2), 255, -1)
            try:
                bgr = cv2.inpaint(bgr, mask, 3, cv2.INPAINT_TELEA)
            except Exception:
                pass
        if alpha is None:
            mask = np.zeros((size, size), dtype=np.uint8)
            cv2.circle(mask, (size//2, size//2), int(size*0.49), 255, -1)
            final = np.dstack((bgr, mask))
        else:
            mask = np.zeros((size, size), dtype=np.uint8)
            cv2.circle(mask, (size//2, size//2), int(size*0.49), 255, -1)
            alpha = cv2.bitwise_and(alpha, mask)
            final = np.dstack((bgr, alpha))
        self.bg_cache[size] = final
        return final

    def _draw_impl(self, frame, data_context):
        speed = float(data_context.get('speed', 0.0) or 0.0)
        h, w = frame.shape[:2]
        rect = data_context.get('rect')
        if rect:
            x, y, rw, rh = rect
            size = max(160, min(rw, rh))
            x += (rw - size) // 2
            y += (rh - size) // 2
        else:
            size = int(min(w, h) * self.config.get('size_ratio', 0.32))
            size = max(180, min(size, 420))
            x = int(self.config.get('margin_left', 36))
            y = int(h - size - self.config.get('margin_bottom', 80))
        x = max(0, min(x, w - size))
        y = max(0, min(y, h - size))
        if size < 120:
            return
        roi = frame[y:y+size, x:x+size]
        if roi.size == 0:
            return
        bg = self._load_bg(size)
        if bg.shape[2] == 4:
            alpha = bg[:, :, 3].astype(np.float32) / 255.0
            bgr = bg[:, :, :3].astype(np.float32)
            base = roi.astype(np.float32)
            blended = bgr * alpha[..., None] + base * (1.0 - alpha[..., None])
            roi[:] = np.clip(blended, 0, 255).astype(np.uint8)
        else:
            roi[:] = bg
        cx, cy = size // 2, size // 2
        r = int(size * 0.44)
        max_speed = max(1.0, float(self.config.get('max_speed', 240.0)))
        start_angle = float(self.config.get('start_angle', 140.0))
        sweep_angle = float(self.config.get('sweep_angle', 260.0))
        ratio = max(0.0, min(1.0, speed / max_speed))
        ang = math.radians(start_angle + sweep_angle * ratio)
        nx = int(cx + r * 0.86 * math.cos(ang))
        ny = int(cy + r * 0.86 * math.sin(ang))
        cv2.line(roi, (cx, cy), (nx, ny), self.config.get('needle_color', (220, 40, 40)), max(2, int(size*0.018)), cv2.LINE_AA)
        cv2.circle(roi, (cx, cy), max(2, int(size*0.03)), (200, 200, 200), -1, cv2.LINE_AA)
        font = cv2.FONT_HERSHEY_SIMPLEX
        sp_text = f"{int(round(speed))}"
        scale_val = max(0.8, size / 180.0) * self.config.get('font_scale', 1.0)
        (tw, th), _ = cv2.getTextSize(sp_text, font, scale_val, max(2, int(scale_val*2.2)))
        cv2.putText(roi, sp_text, (cx - tw//2, cy + th//2 + int(size*0.14)), font, scale_val, self.config.get('digital_color', (245, 245, 245)), max(2, int(scale_val*2.2)), cv2.LINE_AA)
        unit = "KM/H"
        scale_unit = max(0.35, size / 420.0) * self.config.get('font_scale', 1.0)
        (uw, uh), _ = cv2.getTextSize(unit, font, scale_unit, 1)
        cv2.putText(roi, unit, (cx - uw//2, cy + th//2 + int(size*0.22)), font, scale_unit, self.config.get('unit_color', (180, 180, 180)), 1, cv2.LINE_AA)
