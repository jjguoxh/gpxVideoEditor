# Elevation Profile Panel

import numpy as np
import cv2
from ..base import HudPanel

class ElevationPanel(HudPanel):
    def __init__(self, config=None):
        super().__init__(config)
        self.config.update({
            'bg_color': (255, 255, 255),
            'bg_alpha': 0.4,
            'fill_color': (220, 220, 220),
            'line_color': (60, 60, 60),
            'cursor_color': (80, 80, 80),
            'point_color': (0, 0, 255),
            'text_color': (80, 80, 80)
        })
        self._ele_profile_cache = {}

    def _draw_impl(self, frame, data_context):
        """
        Draw elevation profile HUD.
        data_context needs: 'rect', 'current_seconds', 'gpx_data', 'video_duration', 'gpx_offset'
        """
        gpx_data = data_context.get('gpx_data')
        if not gpx_data or 'segments' not in gpx_data:
            return

        video_duration = data_context.get('video_duration', 0)
        if video_duration <= 0:
            return

        gpx_offset = data_context.get('gpx_offset', 0.0)
        h, w = frame.shape[:2]
        x_start, y_start, panel_w, panel_h = data_context.get('rect', (0, 0, 0, 0))
        
        if panel_w < 50 or panel_h < 20:
            return
        
        # Check cache (v2 version key)
        # Include config in cache key to invalidate on style change
        config_key = str(self.config)
        cache_key = (id(gpx_data), gpx_offset, video_duration, panel_w, panel_h, 'v2', config_key)
        
        if self._ele_profile_cache.get('key') != cache_key:
            # Generate cache image
            overlay_bgr = np.full((panel_h, panel_w, 3), self.config['bg_color'], dtype=np.uint8)
            overlay_alpha = np.zeros((panel_h, panel_w), dtype=np.float32)
            
            # Background transparency
            overlay_alpha[:] = self.config['bg_alpha']
            
            segments = gpx_data['segments']
            start_t = gpx_offset
            end_t = gpx_offset + video_duration
            
            # Collect points (relative time, elevation)
            raw_pts = [] 
            min_ele = float('inf')
            max_ele = float('-inf')
            
            for s in segments:
                t1, t2 = s['start'], s['end']
                e1, e2 = s['ele_start'], s['ele_end']
                
                # Completely to the left
                if t2 < start_t:
                    continue
                # Completely to the right
                if t1 > end_t:
                    break
                    
                # Handle intersection
                # Start interpolation
                if t1 < start_t <= t2:
                    ratio = (start_t - t1) / (t2 - t1)
                    e_start = e1 + (e2 - e1) * ratio
                    raw_pts.append((0.0, e_start))
                    min_ele = min(min_ele, e_start)
                    max_ele = max(max_ele, e_start)
                
                # Points within segment
                if t1 >= start_t:
                    rel_t = t1 - start_t
                    raw_pts.append((rel_t, e1))
                    min_ele = min(min_ele, e1)
                    max_ele = max(max_ele, e1)
                    
                # End interpolation
                if t1 <= end_t < t2:
                    ratio = (end_t - t1) / (t2 - t1)
                    e_end = e1 + (e2 - e1) * ratio
                    raw_pts.append((video_duration, e_end))
                    min_ele = min(min_ele, e_end)
                    max_ele = max(max_ele, e_end)
                elif t2 <= end_t:
                    rel_t = t2 - start_t
                    raw_pts.append((rel_t, e2))
                    min_ele = min(min_ele, e2)
                    max_ele = max(max_ele, e2)

            if not raw_pts:
                self._ele_profile_cache = {'key': cache_key, 'valid': False}
                return

            # Normalize and draw
            ele_range = max(10.0, max_ele - min_ele)
            
            pts_px = []
            for t, ele in raw_pts:
                px = int((t / video_duration) * panel_w)
                norm_h = (ele - min_ele) / ele_range
                py = int(panel_h - 10 - norm_h * (panel_h - 20))
                pts_px.append([px, py])
            
            pts_px = np.array(pts_px, np.int32)
            
            if len(pts_px) > 1:
                # Construct closed polygon for filling
                poly_pts = pts_px.tolist()
                poly_pts.append([pts_px[-1][0], panel_h]) 
                poly_pts.append([pts_px[0][0], panel_h])   
                
                poly_pts = np.array(poly_pts, np.int32)
                poly_pts = poly_pts.reshape((-1, 1, 2))
                
                # Draw fill
                cv2.fillPoly(overlay_bgr, [poly_pts], self.config['fill_color'])
                
                # Increase opacity of filled area
                mask = np.zeros((panel_h, panel_w), dtype=np.uint8)
                cv2.fillPoly(mask, [poly_pts], 255)
                overlay_alpha[mask > 0] = 0.5
                
                # Draw lines
                cv2.polylines(overlay_bgr, [pts_px.reshape((-1, 1, 2))], False, self.config['line_color'], 2, cv2.LINE_AA)
                
                # Make lines opaque (dilate mask)
                line_mask = np.zeros((panel_h, panel_w), dtype=np.uint8)
                cv2.polylines(line_mask, [pts_px.reshape((-1, 1, 2))], False, 255, 2)
                overlay_alpha[line_mask > 0] = 0.8

            self._ele_profile_cache = {
                'key': cache_key,
                'valid': True,
                'bgr': overlay_bgr,
                'alpha': overlay_alpha,
                'min_ele': min_ele,
                'max_ele': max_ele,
                'ele_range': ele_range
            }
            
        if not self._ele_profile_cache.get('valid', False):
            return
            
        # 3. Blend Layer
        overlay_bgr = self._ele_profile_cache['bgr']
        overlay_alpha = self._ele_profile_cache['alpha']
        
        roi = frame[y_start:y_start+panel_h, x_start:x_start+panel_w]
        
        alpha_3c = np.dstack([overlay_alpha] * 3)
        blended = (overlay_bgr * alpha_3c + roi * (1.0 - alpha_3c)).astype(np.uint8)
        frame[y_start:y_start+panel_h, x_start:x_start+panel_w] = blended
        
        # 4. Draw Cursor
        min_ele = self._ele_profile_cache['min_ele']
        ele_range = self._ele_profile_cache['ele_range']
        
        current_seconds = data_context.get('current_seconds', 0.0)
        cx = int((current_seconds / video_duration) * panel_w)
        cx = max(0, min(cx, panel_w - 1))
        
        # Vertical Line
        cv2.line(frame, (x_start + cx, y_start), (x_start + cx, y_start + panel_h), self.config['cursor_color'], 1)
        
        # Current Point
        ele = data_context.get('ele')
        if ele is not None:
            norm_h = (ele - min_ele) / ele_range
            cy = int(panel_h - 10 - norm_h * (panel_h - 20))
            cy = max(0, min(cy, panel_h - 1))
            
            center = (x_start + cx, y_start + cy)
            cv2.circle(frame, center, 4, self.config['point_color'], -1)
            cv2.circle(frame, center, 5, self.config['cursor_color'], 1)
            
            text = f"{ele:.0f}m"
            cv2.putText(frame, text, (x_start + cx + 8, y_start + cy), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5 * self.config.get('font_scale', 1.0), (0, 0, 0), 1, cv2.LINE_AA)
            
            cv2.putText(frame, "Elevation", (x_start + 5, y_start + 15), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4 * self.config.get('font_scale', 1.0), self.config['text_color'], 1, cv2.LINE_AA)
