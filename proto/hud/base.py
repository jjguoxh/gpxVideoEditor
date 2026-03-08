# Base class for HUD panels

class HudPanel:
    def __init__(self, config=None):
        self.config = config or {}
        # 默认配置
        self.default_config = {
            'bg_color': (200, 200, 200),
            'text_color': (255, 255, 255),
            'font_scale': 1.0,
            'line_thickness': 2,
            'visible': True
        }
        # 合并配置
        for k, v in self.default_config.items():
            if k not in self.config:
                self.config[k] = v
    
    def update_config(self, new_config):
        """Update configuration properties"""
        # Ensure colors are tuples for hashability and consistency
        sanitized = {}
        for k, v in new_config.items():
            if 'color' in k and isinstance(v, list):
                sanitized[k] = tuple(v)
            else:
                sanitized[k] = v
        self.config.update(sanitized)

    def draw(self, frame, data_context):
        """
        Draw the HUD panel on the frame.
        :param frame: The video frame (numpy array) to draw on.
        :param data_context: A dictionary containing data needed for drawing (e.g., speed, elevation, gpx_data).
        """
        if not self.config.get('visible', True):
            return
        self._draw_impl(frame, data_context)
        
    def _draw_impl(self, frame, data_context):
        """Implementation of drawing logic. To be overridden by subclasses."""
        raise NotImplementedError
