import math
import os
import cv2
import numpy as np
try:
    from .base import HudPanel
except ImportError:
    from ..base import HudPanel


class BlackSpeedPanel(HudPanel):
    def __init__(self, config=None):
        super().__init__(config)
        self.config.update({
            "bg_image_path": os.path.join(os.path.dirname(__file__), "black.png"),
            "bg_clean_image_path": os.path.join(os.path.dirname(__file__), "black.png"),
            "size_ratio": 0.32,
            "margin_left": 36,
            "margin_bottom": 80,
            "max_speed": 240.0,
            "start_angle": 140.0,
            "sweep_angle": 260.0,
            "needle_color": (25, 25, 150),
            "needle_outline_color": (10, 10, 90),
            "digital_color": (245, 245, 245),
            "unit_color": (180, 180, 180),
            "inpaint_enabled": False,
            "inpaint_angle": 135.0,
            "inpaint_radius_ratio": 0.35,
            "inpaint_wedge_width": 6.0,
        })
        self.bg_image = None
        self.bg_clean_image = None
        self.bg_cache = {}

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
        if self.bg_clean_image is None:
            clean_path = self.config.get("bg_clean_image_path")
            if clean_path and os.path.exists(clean_path):
                img = cv2.imread(clean_path, cv2.IMREAD_UNCHANGED)
                if img is not None:
                    self.bg_clean_image = img

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
        crop_clean = None
        if self.bg_clean_image is not None:
            hc, wc = self.bg_clean_image.shape[:2]
            crop_clean = self.bg_clean_image
            if hc != wc:
                sc = min(hc, wc)
                cyc, cxc = hc // 2, wc // 2
                y1c = max(0, cyc - sc // 2)
                x1c = max(0, cxc - sc // 2)
                crop_clean = self.bg_clean_image[y1c:y1c + sc, x1c:x1c + sc]

        resized = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
        resized_clean = None
        if crop_clean is not None and crop_clean.size > 0:
            resized_clean = cv2.resize(crop_clean, (size, size), interpolation=cv2.INTER_AREA)
        if resized.shape[2] == 4:
            bgr = resized[:, :, :3].copy()
            alpha = resized[:, :, 3].copy()
        else:
            bgr = resized.copy()
            alpha = None
        bgr_clean = None
        if resized_clean is not None:
            if resized_clean.shape[2] == 4:
                bgr_clean = resized_clean[:, :, :3]
            else:
                bgr_clean = resized_clean

        if self.config.get("inpaint_enabled", False):
            mask = np.zeros((size, size), dtype=np.uint8)
            center = (size // 2, size // 2)
            radius = int(size * float(self.config.get("inpaint_radius_ratio", 0.35)))
            angle = float(self.config.get("inpaint_angle", 135.0))
            wedge_w = float(self.config.get("inpaint_wedge_width", 6.0))
            ang1 = math.radians(angle - wedge_w / 2.0)
            ang2 = math.radians(angle + wedge_w / 2.0)
            p1 = (int(center[0] + radius * math.cos(ang1)), int(center[1] + radius * math.sin(ang1)))
            p2 = (int(center[0] + radius * math.cos(ang2)), int(center[1] + radius * math.sin(ang2)))
            cv2.fillConvexPoly(mask, np.array([center, p1, p2], np.int32), 255, cv2.LINE_AA)
            cap_r = int(size * 0.1)
            cv2.circle(mask, center, cap_r, 255, -1)
            if bgr_clean is not None and bgr_clean.shape[:2] == bgr.shape[:2]:
                m = mask.astype(bool)
                bgr[m] = bgr_clean[m]
            else:
                try:
                    bgr = cv2.inpaint(bgr, mask, 2, cv2.INPAINT_TELEA)
                except Exception:
                    pass

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

        ang = math.radians(start_angle + sweep_angle * ratio)
        needle_len = int(size * 0.40)
        needle_w = max(2, int(size * 0.018))
        tip = (int(cx + needle_len * math.cos(ang)), int(cy + needle_len * math.sin(ang)))
        perp = ang + math.pi / 2.0
        p1 = (int(cx + needle_w * math.cos(perp)), int(cy + needle_w * math.sin(perp)))
        p2 = (int(cx - needle_w * math.cos(perp)), int(cy - needle_w * math.sin(perp)))
        needle_pts = np.array([p1, p2, tip], np.int32)
        cv2.fillConvexPoly(roi, needle_pts, self.config.get("needle_color", (25, 25, 150)), cv2.LINE_AA)
        cv2.polylines(roi, [needle_pts.reshape((-1, 1, 2))], True, self.config.get("needle_outline_color", (10, 10, 90)), 1, cv2.LINE_AA)

        cap_r = max(3, int(size * 0.04))
        cv2.circle(roi, (cx, cy), cap_r, (30, 30, 30), -1, cv2.LINE_AA)
        cv2.circle(roi, (cx, cy), cap_r, (90, 90, 90), 1, cv2.LINE_AA)

        font = cv2.FONT_HERSHEY_SIMPLEX
        sp_text = f"{int(round(speed))}"
        scale_val = max(0.8, size / 180.0) * float(self.config.get("font_scale", 1.0))
        thickness_val = max(2, int(scale_val * 2.2))
        (tw, th), _ = cv2.getTextSize(sp_text, font, scale_val, thickness_val)
        cv2.putText(
            roi,
            sp_text,
            (cx - tw // 2, cy + th // 2 + int(size * 0.14)),
            font,
            scale_val,
            self.config.get("digital_color", (245, 245, 245)),
            thickness_val,
            cv2.LINE_AA,
        )

        unit = "KM/H"
        scale_unit = max(0.35, size / 420.0) * float(self.config.get("font_scale", 1.0))
        (uw, _), _ = cv2.getTextSize(unit, font, scale_unit, 1)
        cv2.putText(
            roi,
            unit,
            (cx - uw // 2, cy + th // 2 + int(size * 0.22)),
            font,
            scale_unit,
            self.config.get("unit_color", (180, 180, 180)),
            1,
            cv2.LINE_AA,
        )
