"""Thread-safe shared state between detector and web server."""

import threading
from collections import deque
from typing import Optional

if __package__:
    from .config import Config
else:
    from config import Config


class SharedState:
    def __init__(self, config: Config, history_secs: float = 5.0):
        self.config = config
        self._lock = threading.Lock()
        self._history_maxlen = int(history_secs * config.sample_rate / config.hop_size)

        self.latest_flux: float = 0.0
        self.latest_threshold: float = 0.0
        self.latest_ratio: float = 0.0
        self.beat_count: int = 0
        self.flux_history: deque[float] = deque(maxlen=self._history_maxlen)

    def update(self, flux: float, threshold: float, is_beat: bool):
        with self._lock:
            self.latest_flux = flux
            self.latest_threshold = threshold
            self.latest_ratio = flux / (threshold + 1e-10)
            self.flux_history.append(flux)
            if is_beat:
                self.beat_count += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "flux": round(self.latest_flux, 1),
                "threshold": round(self.latest_threshold, 1),
                "ratio": round(self.latest_ratio, 3),
                "beat_count": self.beat_count,
                "history": list(self.flux_history),
                "config": {
                    "sensitivity": self.config.sensitivity,
                    "noise_floor": self.config.noise_floor,
                    "min_interval_ms": self.config.min_interval_ms,
                    "hop_size": self.config.hop_size,
                    "keybind": self.config.keybind,
                    "enabled": self.config.enabled,
                    "sample_rate": self.config.sample_rate,
                    "frame_size": self.config.frame_size,
                },
            }
