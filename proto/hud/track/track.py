# Local Track View Panel

import math
import numpy as np
import cv2
from ..base import HudPanel

class TrackPanel(HudPanel):
    def __init__(self, config=None):
        super().__init__(config)
        self.config.update({
            'bg_color': (0, 0, 0, 0), # Transparent
            'track_color': (0, 255, 0, 200),
            'curr_point_color': (0, 0, 255, 255),
            'curr_point_outline': (255, 255, 255, 255),
            'border_color': (255, 255, 255),
            'text_color': (255, 255, 255),
            'view_size_ratio': 0.3, # relative to width
            'cam_behind_m': 100.0,
            'scale_factor': 1.0,
            'margin_top': 20,
            'margin_right': 20
        })
        self._smooth_cache = {}

    def _draw_impl(self, frame, data_context):
        """
        Draw local track view HUD.
        data_context needs: 'gpx_data', 'current_seconds', 'gpx_offset', 'rect' (optional override)
        """
        gpx_data = data_context.get('gpx_data')
        if not gpx_data or 'smoothed_segments' not in gpx_data:
            return

        current_seconds = data_context.get('current_seconds', 0.0)
        gpx_offset = data_context.get('gpx_offset', 0.0)
        t = current_seconds + gpx_offset
        
        # Get smoothed state (passed in context or calculated?)
        # Better to pass smooth_lats/lons if available for performance
        smooth_lats = data_context.get('smooth_lats')
        smooth_lons = data_context.get('smooth_lons')
        
        # We need current state (lat, lon, heading)
        # Assuming data_context provides 'current_state' tuple: (lat, lon, heading)
        state = data_context.get('current_state')
        if not state:
            return
            
        cur_lat, cur_lon, cur_heading = state
        
        h, w = frame.shape[:2]
        
        # Dynamic view size logic from original code, unless overridden by config or rect
        # Original logic: min(w*0.3, h*0.4), clamped [150, 300]
        # But here we might have a rect from the editor
        rect = data_context.get('rect')
        if rect:
            x_offset, y_offset, view_w, view_h = rect
            view_size = min(view_w, view_h) # Keep it square?
        else:
            # Fallback to dynamic calculation
            view_size = min(int(w * 0.3), int(h * 0.4))
            view_size = max(150, min(view_size, 300))
            x_offset = w - view_size - self.config.get('margin_right', 20)
            y_offset = self.config.get('margin_top', 20)
        
        scale_factor = float(self.config.get('scale_factor', 1.0))
        if scale_factor > 10.0:
            scale = view_size / scale_factor
        else:
            scale = (view_size / 350.0) * max(scale_factor, 0.05)
        cam_behind_m = self.config['cam_behind_m']
        
        # Create transparent overlay
        overlay = np.zeros((view_size, view_size, 4), dtype=np.uint8)
        
        cx, cy = view_size // 2, view_size - 30
        
        segs = gpx_data['smoothed_segments']
        
        # Optimization: Use passed numpy arrays or fallback to list
        last_idx = data_context.get('last_idx', 0)
        start_idx = max(0, last_idx - 300)
        end_idx = min(len(segs), last_idx + 300)
        
        if start_idx >= end_idx:
            return

        if smooth_lats is not None and smooth_lons is not None:
            lats = smooth_lats[start_idx:end_idx]
            lons = smooth_lons[start_idx:end_idx]
        else:
            lats = np.array([s['lat'] for s in segs[start_idx:end_idx]])
            lons = np.array([s['lon'] for s in segs[start_idx:end_idx]])
            
        rad_heading = math.radians(cur_heading)
        cos_h = math.cos(rad_heading)
        sin_h = math.sin(rad_heading)
        
        # Vectorized calculation
        dys = (lats - cur_lat) * 111320
        dxs = (lons - cur_lon) * 111320 * math.cos(math.radians(cur_lat))
        
        local_ys = dys * cos_h + dxs * sin_h
        local_xs = dxs * cos_h - dys * sin_h
        
        sxs = cx + local_xs * scale
        sys = cy - (local_ys + cam_behind_m) * scale
        
        pts_screen = np.stack((sxs, sys), axis=1).astype(np.int32)

        if len(pts_screen) > 1:
            cv2.polylines(overlay, [pts_screen], False, self.config['track_color'], 2, cv2.LINE_AA)
            
        # Draw current point
        curr_sx = int(cx)
        curr_sy = int(cy - cam_behind_m * scale)
        cv2.circle(overlay, (curr_sx, curr_sy), 5, self.config['curr_point_color'], -1, cv2.LINE_AA)
        cv2.circle(overlay, (curr_sx, curr_sy), 7, self.config['curr_point_outline'], 1, cv2.LINE_AA)
        
        # Blend
        roi = frame[y_offset:y_offset+view_size, x_offset:x_offset+view_size]
        
        ov_bgr = overlay[:, :, :3].astype(np.int32)
        ov_alpha = overlay[:, :, 3].astype(np.int32)[:, :, np.newaxis]
        
        roi_int = roi.astype(np.int32)
        blended = (ov_bgr * ov_alpha + roi_int * (255 - ov_alpha)) // 255
        blended = blended.astype(np.uint8)
        
        frame[y_offset:y_offset+view_size, x_offset:x_offset+view_size] = blended
        
        # Draw border
        cv2.rectangle(frame, (x_offset, y_offset), (x_offset+view_size, y_offset+view_size), self.config['border_color'], 1)
        cv2.putText(frame, "Follow Cam", (x_offset + 5, y_offset + 15), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4 * self.config.get('font_scale', 1.0), self.config['text_color'], 1)
