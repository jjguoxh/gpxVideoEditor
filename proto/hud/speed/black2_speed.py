import math
import os
import cv2
import numpy as np
try:
    from .base import HudPanel
except ImportError:
    from ..base import HudPanel


class Black2SpeedPanel(HudPanel):
    def __init__(self, config=None):
        super().__init__(config)
        self.config.update({
            "bg_image_path": os.path.join(os.path.dirname(__file__), "black2.png"),
            "size_ratio": 0.32,
            "margin_left": 36,
            "margin_bottom": 80,
            "max_speed": 240.0,
            "start_angle": 140.0,
            "sweep_angle": 260.0,
            "digital_color": (245, 245, 245),
            "unit_color": (180, 180, 180),
            "led_color_low": (90, 255, 140),
            "led_color_mid": (0, 165, 255),
            "led_color_high": (0, 0, 255),
            "led_mid_ratio": 0.7,
            "led_inactive_brightness": 0.14,
            "led_active_brightness_min": 0.55,
            "led_active_brightness_max": 1.0,
            "led_trail_count": 14,
            "led_count": 72,
            "led_ring_radius_ratio": 0.42,
            "led_radius_ratio": 0.014
        })
        self.bg_image = None
        self.bg_cache = {}

    @staticmethod
    def _lerp_color(c1, c2, a):
        a = float(a)
        return (
            int(round(c1[0] + (c2[0] - c1[0]) * a)),
            int(round(c1[1] + (c2[1] - c1[1]) * a)),
            int(round(c1[2] + (c2[2] - c1[2]) * a)),
        )

    def _led_color_for_ratio(self, t):
        c0 = self.config.get("led_color_low", (90, 255, 140))
        c1 = self.config.get("led_color_mid", (0, 165, 255))
        c2 = self.config.get("led_color_high", (0, 0, 255))
        mid = float(self.config.get("led_mid_ratio", 0.7))
        if mid <= 0.0:
            return self._lerp_color(c0, c2, t)
        if t <= mid:
            a = t / mid
            return self._lerp_color(c0, c1, a)
        a = (t - mid) / max(1e-6, (1.0 - mid))
        return self._lerp_color(c1, c2, a)

    @staticmethod
    def _scale_color(color_bgr, brightness):
        b = max(0.0, min(1.0, float(brightness)))
        return (
            int(max(0, min(255, round(color_bgr[0] * b)))),
            int(max(0, min(255, round(color_bgr[1] * b)))),
            int(max(0, min(255, round(color_bgr[2] * b)))),
        )

    def _load_bg(self, size):
        cached = self.bg_cache.get(size)
        if cached is not None:
            return cached
        if self.bg_image is None:
            path = self.config.get("bg_image_path")
            if path and os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                if img is not None:
                    self.bg_image = img
        if self.bg_image is None:
            out = np.zeros((size, size, 4), dtype=np.uint8)
            self.bg_cache[size] = out
            return out
        h, w = self.bg_image.shape[:2]
        crop = self.bg_image
        if h != w:
            s = min(h, w)
            cy, cx = h // 2, w // 2
            y1 = max(0, cy - s // 2)
            x1 = max(0, cx - s // 2)
            crop = self.bg_image[y1:y1 + s, x1:x1 + s]
        resized = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
        if resized.shape[2] == 4:
            bgr = resized[:, :, :3].copy()
            alpha = resized[:, :, 3].copy()
        else:
            bgr = resized.copy()
            alpha = None
        mask_circle = np.zeros((size, size), dtype=np.uint8)
        cv2.circle(mask_circle, (size // 2, size // 2), int(size * 0.49), 255, -1)
        if alpha is None:
            alpha = mask_circle
        else:
            alpha = cv2.bitwise_and(alpha, mask_circle)
        final = np.dstack((bgr, alpha))
        self.bg_cache[size] = final
        return final

    def _draw_impl(self, frame, data_context):
        speed = float(data_context.get("speed", 0.0) or 0.0)
        h, w = frame.shape[:2]
        rect = data_context.get("rect")
        if rect:
            x, y, rw, rh = rect
            size = max(160, min(rw, rh))
            x += (rw - size) // 2
            y += (rh - size) // 2
        else:
            size = int(min(w, h) * float(self.config.get("size_ratio", 0.32)))
            size = max(180, min(size, 420))
            x = int(self.config.get("margin_left", 36))
            y = int(h - size - self.config.get("margin_bottom", 80))
        x = max(0, min(x, w - size))
        y = max(0, min(y, h - size))
        if size < 120:
            return
        roi = frame[y:y + size, x:x + size]
        if roi.size == 0:
            return
        bg = self._load_bg(size)
        alpha = bg[:, :, 3].astype(np.float32) / 255.0
        bgr = bg[:, :, :3].astype(np.float32)
        base = roi.astype(np.float32)
        roi[:] = np.clip(bgr * alpha[..., None] + base * (1.0 - alpha[..., None]), 0, 255).astype(np.uint8)
        cx, cy = size // 2, size // 2
        max_speed = max(1.0, float(self.config.get("max_speed", 240.0)))
        start_angle = float(self.config.get("start_angle", 140.0))
        sweep_angle = float(self.config.get("sweep_angle", 260.0))
        ratio = max(0.0, min(1.0, speed / max_speed))
        led_count = int(self.config.get("led_count", 72))
        ring_r = int(size * float(self.config.get("led_ring_radius_ratio", 0.42)))
        led_r = max(1, int(size * float(self.config.get("led_radius_ratio", 0.014))))
        active_n = int(round(ratio * led_count))
        inactive_b = float(self.config.get("led_inactive_brightness", 0.14))
        bmin = float(self.config.get("led_active_brightness_min", 0.55))
        bmax = float(self.config.get("led_active_brightness_max", 1.0))
        trail_n = max(1, int(self.config.get("led_trail_count", 14)))
        for i in range(led_count):
            t = i / max(1, led_count - 1)
            ang = math.radians(start_angle + sweep_angle * t)
            px = int(cx + ring_r * math.cos(ang))
            py = int(cy + ring_r * math.sin(ang))
            base_color = self._led_color_for_ratio(t)
            if i < active_n:
                edge = max(0, active_n - 1)
                d = edge - i
                if d <= trail_n:
                    bright = bmax - (bmax - bmin) * (d / float(trail_n))
                else:
                    bright = bmin
                color = self._scale_color(base_color, bright)
            else:
                color = self._scale_color(base_color, inactive_b)
            cv2.circle(roi, (px, py), led_r, color, -1, cv2.LINE_AA)
        font = cv2.FONT_HERSHEY_SIMPLEX
        sp_text = f"{int(round(speed))}"
        scale_val = max(0.8, size / 180.0) * float(self.config.get("font_scale", 1.0))
        thickness_val = max(2, int(scale_val * 2.2))
        (tw, th), _ = cv2.getTextSize(sp_text, font, scale_val, thickness_val)
        cv2.putText(roi, sp_text, (cx - tw // 2, cy + th // 2), font, scale_val, self.config.get("digital_color", (245, 245, 245)), thickness_val, cv2.LINE_AA)
        unit = "KM/H"
        scale_unit = max(0.35, size / 420.0) * float(self.config.get("font_scale", 1.0))
        (uw, _), _ = cv2.getTextSize(unit, font, scale_unit, 1)
        cv2.putText(roi, unit, (cx - uw // 2, cy + th // 2 + int(size * 0.10)), font, scale_unit, self.config.get("unit_color", (180, 180, 180)), 1, cv2.LINE_AA)
