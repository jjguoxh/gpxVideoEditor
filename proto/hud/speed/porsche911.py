import math
import cv2
import numpy as np
import os
from .base import HudPanel

class Porsche911Panel(HudPanel):
    def __init__(self, config=None):
        super().__init__(config)
        self.config.update({
            'bg_image_path': os.path.join(os.path.dirname(__file__), '911.png'),
            'bg_clean_image_path': os.path.join(os.path.dirname(__file__), '911x.png'),
            'size_ratio': 0.35,
            'margin_left': 40,
            'margin_bottom': 60,
            'max_speed': 300.0,
            # Needle config
            'needle_color_light': (240, 240, 240), # Silver needle light side
            'needle_color_dark': (160, 160, 160),  # Silver needle dark side
            # Inpainting config (to hide original needle)
            'inpaint_enabled': True,
            # Keep inpaint within inner area to avoid blurring the silver ring
            'inpaint_radius_ratio': 0.35,  # Reduce extent so ring area stays untouched
            'inpaint_angle': 135.0,        # Assumed resting angle of static needle
            'inpaint_wedge_width': 6.0,    # Narrower wedge
        })
        
        self.bg_image = None
        self.bg_clean_image = None
        self.bg_cache = {} # Key: size_tuple, Value: processed_image

    def _load_and_process_bg(self, size):
        if size in self.bg_cache:
            return self.bg_cache[size]

        if self.bg_image is None:
            path = self.config.get('bg_image_path')
            if path and os.path.exists(path):
                try:
                    # Read image with alpha channel if possible, but cv2.imread usually reads BGR
                    # We assume the image is a standard photo/scan (BGR)
                    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                    if img is not None:
                        self.bg_image = img
                except Exception as e:
                    print(f"Error loading 911 HUD image: {e}")

        if self.bg_clean_image is None:
            clean_path = self.config.get('bg_clean_image_path')
            if clean_path and os.path.exists(clean_path):
                try:
                    img = cv2.imread(clean_path, cv2.IMREAD_UNCHANGED)
                    if img is not None:
                        self.bg_clean_image = img
                except Exception:
                    pass

        if self.bg_image is None:
            # Fallback to black square if image missing
            fallback = np.zeros((size, size, 3), dtype=np.uint8)
            self.bg_cache[size] = fallback
            return fallback

        # Process image
        h, w = self.bg_image.shape[:2]
        
        # 1. Crop to center square (assuming the dial is in the center)
        crop_size = min(h, w)
        cx, cy = w // 2, h // 2
        x1 = cx - crop_size // 2
        y1 = cy - crop_size // 2
        crop = self.bg_image[y1:y1+crop_size, x1:x1+crop_size]
        crop_clean = None
        if self.bg_clean_image is not None:
            hc, wc = self.bg_clean_image.shape[:2]
            crop_size_c = min(hc, wc)
            cxc, cyc = wc // 2, hc // 2
            x1c = cxc - crop_size_c // 2
            y1c = cyc - crop_size_c // 2
            crop_clean = self.bg_clean_image[y1c:y1c+crop_size_c, x1c:x1c+crop_size_c]
        
        # 2. Resize to target size
        resized = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
        resized_clean = None
        if crop_clean is not None and crop_clean.size > 0:
            resized_clean = cv2.resize(crop_clean, (size, size), interpolation=cv2.INTER_AREA)
        
        # Handle Alpha if present
        if resized.shape[2] == 4:
            # If transparent, keep it, but for inpainting we might need BGR
            # Let's split alpha
            bgr = resized[:, :, :3]
            alpha = resized[:, :, 3]
        else:
            bgr = resized
            alpha = None
        bgr_clean = None
        if resized_clean is not None:
            if resized_clean.shape[2] == 4:
                bgr_clean = resized_clean[:, :, :3]
            else:
                bgr_clean = resized_clean

        # 3. Inpaint the static needle if enabled
        if self.config.get('inpaint_enabled', True):
            # Create a mask for the needle position
            # Assuming needle is at 'inpaint_angle' (e.g., 0 speed position)
            mask = np.zeros((size, size), dtype=np.uint8)
            
            center = (size // 2, size // 2)
            # Limit radius so we don't touch the bright metallic ring
            radius = int(size * self.config.get('inpaint_radius_ratio', 0.35))
            angle = self.config.get('inpaint_angle', 135.0)
            wedge_w = self.config.get('inpaint_wedge_width', 6.0)
            
            # Draw a narrow wedge (two lines at +/- wedge_w/2) with small thickness
            # Use a poly to better control covered area
            ang1 = math.radians(angle - wedge_w / 2.0)
            ang2 = math.radians(angle + wedge_w / 2.0)
            p1 = (int(center[0] + radius * math.cos(ang1)), int(center[1] + radius * math.sin(ang1)))
            p2 = (int(center[0] + radius * math.cos(ang2)), int(center[1] + radius * math.sin(ang2)))
            cv2.fillConvexPoly(mask, np.array([center, p1, p2], np.int32), 255, cv2.LINE_AA)
            
            # Also cover the center cap area slightly more
            cap_r = int(size * 0.1)
            cv2.circle(mask, center, cap_r, 255, -1)
            
            if bgr_clean is not None and bgr_clean.shape[:2] == bgr.shape[:2]:
                m = mask.astype(bool)
                bgr[m] = bgr_clean[m]
            else:
                try:
                    bgr = cv2.inpaint(bgr, mask, 2, cv2.INPAINT_TELEA)
                except Exception:
                    pass # Inpainting might fail if libraries missing

        # Recombine alpha if existed
        if alpha is not None:
            # Create masked circular output
            # Mask outside circle to transparent
            mask_circle = np.zeros((size, size), dtype=np.uint8)
            cv2.circle(mask_circle, (size//2, size//2), int(size*0.49), 255, -1)
            alpha = cv2.bitwise_and(alpha, mask_circle)
            
            final_img = np.dstack((bgr, alpha))
        else:
            # Create alpha channel based on circle
            mask_circle = np.zeros((size, size), dtype=np.uint8)
            cv2.circle(mask_circle, (size//2, size//2), int(size*0.49), 255, -1)
            final_img = np.dstack((bgr, mask_circle))
            
        self.bg_cache[size] = final_img
        return final_img

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

        # 1. Prepare and Blit Background Image
        bg_img = self._load_and_process_bg(size)
        
        # Overlay bg_img onto roi (handling alpha)
        if bg_img.shape[2] == 4:
            b_alpha = bg_img[:, :, 3] / 255.0
            b_bgr = bg_img[:, :, :3]
            
            for c in range(3):
                roi[:, :, c] = (1.0 - b_alpha) * roi[:, :, c] + b_alpha * b_bgr[:, :, c]
        else:
            roi[:] = bg_img

        # 2. Draw Needle (Silver, 3D Metallic)
        cx, cy = size // 2, size // 2
        start_angle = 135.0
        sweep_angle = 270.0
        max_speed = max(1.0, float(self.config.get('max_speed', 300.0)))
        
        speed_clamped = max(0, min(speed, max_speed))
        needle_ratio = speed_clamped / max_speed
        needle_angle_deg = start_angle + sweep_angle * needle_ratio
        needle_angle_rad = math.radians(needle_angle_deg)
        
        needle_len = int(size * 0.42) 
        needle_w = int(size * 0.03)
        
        # Tip
        tip_x = int(cx + needle_len * math.cos(needle_angle_rad))
        tip_y = int(cy + needle_len * math.sin(needle_angle_rad))
        
        # Base points
        base_angle_rad = needle_angle_rad + math.pi / 2
        bx1 = int(cx + needle_w * math.cos(base_angle_rad))
        by1 = int(cy + needle_w * math.sin(base_angle_rad))
        bx2 = int(cx - needle_w * math.cos(base_angle_rad))
        by2 = int(cy - needle_w * math.sin(base_angle_rad))
        
        # Draw Needle
        # Left half (lighter)
        pts_light = np.array([[cx, cy], [bx1, by1], [tip_x, tip_y]], np.int32)
        cv2.fillConvexPoly(roi, pts_light, self.config['needle_color_light'], cv2.LINE_AA)
        
        # Right half (darker)
        pts_dark = np.array([[cx, cy], [bx2, by2], [tip_x, tip_y]], np.int32)
        cv2.fillConvexPoly(roi, pts_dark, self.config['needle_color_dark'], cv2.LINE_AA)
        
        # 3. Center Cap (Chrome/Silver)
        cap_r = int(size * 0.08)
        # Outer rim of cap
        cv2.circle(roi, (cx, cy), cap_r, (180, 180, 180), -1, cv2.LINE_AA)
        # Inner part
        cv2.circle(roi, (cx, cy), int(cap_r * 0.8), (230, 230, 230), -1, cv2.LINE_AA)
        # Center dot
        cv2.circle(roi, (cx, cy), int(cap_r * 0.2), (100, 100, 100), -1, cv2.LINE_AA)
