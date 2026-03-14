import math
import os
import cv2
import numpy as np
try:
    from .base import HudPanel
except ImportError:
    from ..base import HudPanel


class WhiteSpeedPanel(HudPanel):
    def __init__(self, config=None):
        super().__init__(config)
        self.config.update({
            "bg_image_path": os.path.join(os.path.dirname(__file__), "white.png"),
            "bg_clean_image_path": os.path.join(os.path.dirname(__file__), "white1.png"),
            "size_ratio": 0.32,
            "margin_left": 36,
            "margin_bottom": 80,
            "max_speed": 280.0,
            "start_angle": 225.0,
            "sweep_angle": 270.0,
            "needle_color": (0, 0, 220),
            "needle_outline_color": (0, 0, 120),
            "needle_len_mult": 1.7,
            "show_digital": False,
            "digital_color": (30, 30, 30),
            "unit_color": (80, 80, 80),
            "unit_text": "KM/H",
            "dial_left_center": (0.25, 0.5),
            "dial_right_center": (0.75, 0.5),
            "dial_radius_ratio": 0.40,
            "draw_right_needle": True,
            "digital_on_right": True,
            "auto_calibrate": True,
            "inpaint_enabled": True,
            "inpaint_wedge_width": 10.0,
            "inpaint_radius_ratio": 0.45,
            "inpaint_left_angle": 330.0,
            "inpaint_right_angle": 225.0,
        })
        self.bg_image = None
        self.bg_clean_image = None
        self.bg_cache = {}
        self._auto_done_key = None

    def _load_bg(self, target_h):
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
            out = np.zeros((target_h, target_h * 2, 4), dtype=np.uint8)
            return out

        h0, w0 = self.bg_image.shape[:2]
        target_w = max(1, int(round(target_h * (w0 / max(1, h0)))))
        key = (target_w, target_h)
        cached = self.bg_cache.get(key)
        if cached is not None:
            return cached

        resized = cv2.resize(self.bg_image, (target_w, target_h), interpolation=cv2.INTER_AREA)
        resized_clean = None
        if self.bg_clean_image is not None:
            resized_clean = cv2.resize(self.bg_clean_image, (target_w, target_h), interpolation=cv2.INTER_AREA)

        if resized.shape[2] == 4:
            bgr = resized[:, :, :3].copy()
            alpha = resized[:, :, 3].copy()
        else:
            bgr = resized.copy()
            alpha = np.full((target_h, target_w), 255, dtype=np.uint8)

        bgr_clean = None
        if resized_clean is not None:
            if resized_clean.shape[2] == 4:
                bgr_clean = resized_clean[:, :, :3]
            else:
                bgr_clean = resized_clean

        auto_key = (target_w, target_h)
        if bool(self.config.get("auto_calibrate", True)) and self._auto_done_key != auto_key:
            try:
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (7, 7), 1.5)
                def detect_center(approx_cx_ratio):
                    cx0 = int(target_w * float(approx_cx_ratio))
                    cy0 = int(target_h * float(self.config.get("dial_left_center", (0.25, 0.5))[1]))
                    win_w = int(target_w * 0.28)
                    win_h = int(target_h * 0.6)
                    x1 = max(0, cx0 - win_w // 2)
                    y1 = max(0, cy0 - win_h // 2)
                    x2 = min(target_w, x1 + win_w)
                    y2 = min(target_h, y1 + win_h)
                    roi = gray[y1:y2, x1:x2]
                    if roi.size == 0:
                        return None
                    rmin = max(4, int(min(roi.shape[:2]) * 0.05))
                    rmax = max(rmin + 1, int(min(roi.shape[:2]) * 0.16))
                    circles = cv2.HoughCircles(roi, cv2.HOUGH_GRADIENT, dp=1.2, minDist=int(min(roi.shape[:2]) * 0.8), param1=120, param2=18, minRadius=rmin, maxRadius=rmax)
                    if circles is not None and len(circles[0]) >= 1:
                        c = circles[0][0]
                        cx = int(c[0]) + x1
                        cy = int(c[1]) + y1
                        r = int(c[2])
                        return (cx, cy, r)
                    return None
                left_c = detect_center(self.config.get("dial_left_center", (0.25, 0.5))[0])
                right_c = detect_center(self.config.get("dial_right_center", (0.75, 0.5))[0])
                if left_c and right_c:
                    lx, ly, lr = left_c
                    rx, ry, rr = right_c
                    self.config["dial_left_center"] = (lx / float(target_w), ly / float(target_h))
                    self.config["dial_right_center"] = (rx / float(target_w), ry / float(target_h))
                    dial_r = max(lr, rr) * 5
                    self.config["dial_radius_ratio"] = max(0.1, min(0.7, dial_r / float(target_h)))
                    self._auto_done_key = auto_key
            except Exception:
                pass

        if bool(self.config.get("inpaint_enabled", True)):
            dial_r = int(target_h * float(self.config.get("dial_radius_ratio", 0.40)))
            radius = int(dial_r * float(self.config.get("inpaint_radius_ratio", 0.45)))
            wedge_w = float(self.config.get("inpaint_wedge_width", 10.0))

            def apply_clean(center_ratio, angle_deg):
                mask = np.zeros((target_h, target_w), dtype=np.uint8)
                cx = int(target_w * float(center_ratio[0]))
                cy = int(target_h * float(center_ratio[1]))
                ang1 = math.radians(angle_deg - wedge_w / 2.0)
                ang2 = math.radians(angle_deg + wedge_w / 2.0)
                p1 = (int(cx + radius * math.cos(ang1)), int(cy + radius * math.sin(ang1)))
                p2 = (int(cx + radius * math.cos(ang2)), int(cy + radius * math.sin(ang2)))
                cv2.fillConvexPoly(mask, np.array([(cx, cy), p1, p2], np.int32), 255, cv2.LINE_AA)
                cap_r = max(3, int(dial_r * 0.10))
                cv2.circle(mask, (cx, cy), cap_r, 255, -1)
                if bgr_clean is not None and bgr_clean.shape[:2] == bgr.shape[:2]:
                    m = mask.astype(bool)
                    bgr[m] = bgr_clean[m]
                else:
                    try:
                        bgr[:] = cv2.inpaint(bgr, mask, 2, cv2.INPAINT_TELEA)
                    except Exception:
                        pass

            apply_clean(self.config.get("dial_left_center", (0.25, 0.5)), float(self.config.get("inpaint_left_angle", 330.0)))
            apply_clean(self.config.get("dial_right_center", (0.75, 0.5)), float(self.config.get("inpaint_right_angle", 225.0)))

        final = np.dstack((bgr, alpha))
        self.bg_cache[key] = final
        return final

    @staticmethod
    def _draw_needle(roi, center, angle_deg, needle_len, needle_w, color, outline_color):
        cx, cy = center
        ang = math.radians(angle_deg)
        tip = (int(cx + needle_len * math.cos(ang)), int(cy + needle_len * math.sin(ang)))
        perp = ang + math.pi / 2.0
        p1 = (int(cx + needle_w * math.cos(perp)), int(cy + needle_w * math.sin(perp)))
        p2 = (int(cx - needle_w * math.cos(perp)), int(cy - needle_w * math.sin(perp)))
        needle_pts = np.array([p1, p2, tip], np.int32)
        cv2.fillConvexPoly(roi, needle_pts, color, cv2.LINE_AA)
        cv2.polylines(roi, [needle_pts.reshape((-1, 1, 2))], True, outline_color, 1, cv2.LINE_AA)

    def _draw_impl(self, frame, data_context):
        speed = float(data_context.get("speed", 0.0) or 0.0)
        h, w = frame.shape[:2]

        rect = data_context.get("rect")
        if rect:
            x, y, rw, rh = rect
            target_h = max(160, rh)
            target_h = int(min(target_h, rh))
        else:
            target_h = int(min(w, h) * float(self.config.get("size_ratio", 0.32)))
            target_h = max(180, min(target_h, 420))
            x = int(self.config.get("margin_left", 36))
            y = int(h - target_h - self.config.get("margin_bottom", 80))

        bg = self._load_bg(target_h)
        target_w = int(bg.shape[1])
        if rect:
            x = x + (rw - target_w) // 2
            y = y + (rh - target_h) // 2

        x = max(0, min(x, w - target_w))
        y = max(0, min(y, h - target_h))
        if target_h < 120 or target_w < 120:
            return

        roi = frame[y:y + target_h, x:x + target_w]
        if roi.size == 0:
            return

        alpha = bg[:, :, 3].astype(np.float32) / 255.0
        bgr = bg[:, :, :3].astype(np.float32)
        base = roi.astype(np.float32)
        roi[:] = np.clip(bgr * alpha[..., None] + base * (1.0 - alpha[..., None]), 0, 255).astype(np.uint8)

        max_speed = max(1.0, float(self.config.get("max_speed", 280.0)))
        start_angle = float(self.config.get("start_angle", 225.0))
        sweep_angle = float(self.config.get("sweep_angle", 270.0))
        ratio = max(0.0, min(1.0, speed / max_speed))
        needle_angle = start_angle + sweep_angle * ratio

        dial_r = int(target_h * float(self.config.get("dial_radius_ratio", 0.40)))
        needle_len = int(dial_r * 0.92 * float(self.config.get("needle_len_mult", 1.7)))
        needle_w = max(2, int(dial_r * 0.06))
        left_center_ratio = self.config.get("dial_left_center", (0.25, 0.5))
        right_center_ratio = self.config.get("dial_right_center", (0.75, 0.5))
        left_center = (int(target_w * float(left_center_ratio[0])), int(target_h * float(left_center_ratio[1])))
        right_center = (int(target_w * float(right_center_ratio[0])), int(target_h * float(right_center_ratio[1])))

        self._draw_needle(
            roi,
            left_center,
            needle_angle,
            needle_len,
            needle_w,
            self.config.get("needle_color", (0, 0, 220)),
            self.config.get("needle_outline_color", (0, 0, 120)),
        )
        if bool(self.config.get("draw_right_needle", True)):
            self._draw_needle(
                roi,
                right_center,
                needle_angle,
                needle_len,
                needle_w,
                self.config.get("needle_color", (0, 0, 220)),
                self.config.get("needle_outline_color", (0, 0, 120)),
            )

        cap_r = max(3, int(dial_r * 0.10))
        for cc in (left_center, right_center):
            cv2.circle(roi, cc, cap_r, (235, 235, 235), -1, cv2.LINE_AA)
            cv2.circle(roi, cc, cap_r, (120, 120, 120), 1, cv2.LINE_AA)

        # Optional digital display (disabled by default)
        if bool(self.config.get("show_digital", False)):
            font = cv2.FONT_HERSHEY_SIMPLEX
            sp_text = f"{int(round(speed))}"
            scale_val = max(0.8, target_h / 180.0) * float(self.config.get("font_scale", 1.0))
            thickness_val = max(2, int(scale_val * 2.2))
            (tw, th), _ = cv2.getTextSize(sp_text, font, scale_val, thickness_val)
            if bool(self.config.get("digital_on_right", True)):
                tx, ty = right_center[0] - tw // 2, right_center[1] + th // 2
            else:
                tx, ty = left_center[0] - tw // 2, left_center[1] + th // 2
            cv2.putText(roi, sp_text, (tx, ty), font, scale_val, self.config.get("digital_color", (30, 30, 30)), thickness_val, cv2.LINE_AA)
            unit = str(self.config.get("unit_text", "KM/H"))
            scale_unit = max(0.35, target_h / 420.0) * float(self.config.get("font_scale", 1.0))
            (uw, _), _ = cv2.getTextSize(unit, font, scale_unit, 1)
            if bool(self.config.get("digital_on_right", True)):
                ux, uy = right_center[0] - uw // 2, right_center[1] + th // 2 + int(target_h * 0.10)
            else:
                ux, uy = left_center[0] - uw // 2, left_center[1] + th // 2 + int(target_h * 0.10)
            cv2.putText(roi, unit, (ux, uy), font, scale_unit, self.config.get("unit_color", (80, 80, 80)), 1, cv2.LINE_AA)
