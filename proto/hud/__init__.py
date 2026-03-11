# __init__.py for HUD package (robust exports for old/new layout)
from .base import HudPanel

# Elevation
try:
    from .altitude.elevation import ElevationPanel  # new layout
except Exception:
    try:
        from .elevation import ElevationPanel  # legacy layout
    except Exception:
        ElevationPanel = None

# Telemetry
try:
    from .combine.telemetry import TelemetryPanel  # new layout
except Exception:
    try:
        from .telemetry import TelemetryPanel  # legacy layout
    except Exception:
        TelemetryPanel = None

# Track
try:
    from .track.track import TrackPanel  # new layout
except Exception:
    try:
        from .track import TrackPanel  # legacy layout (flat)
    except Exception:
        TrackPanel = None

# Speedometer
try:
    from .speed.speedometer import SpeedometerPanel  # new layout
except Exception:
    try:
        from .speedometer import SpeedometerPanel  # legacy layout
    except Exception:
        SpeedometerPanel = None

# Porsche 911
try:
    from .speed.porsche911 import Porsche911Panel  # new layout
except Exception:
    try:
        from .porsche911 import Porsche911Panel  # legacy layout
    except Exception:
        Porsche911Panel = None
