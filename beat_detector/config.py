"""Configuration management for beat detector."""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class FreqBand:
    name: str = "full"
    low: float = 0.0
    high: float = 22050.0
    weight: float = 1.0


@dataclass
class Config:
    sample_rate: int = 48000
    frame_size: int = 1024
    hop_size: int = 256
    sensitivity: float = 1.5
    noise_floor: float = 50.0
    min_interval_ms: int = 50
    enabled: bool = True
    history_window_s: float = 2.0
    keybind: str = "s"
    frequency_bands: list = field(default_factory=lambda: [
        {"name": "low", "low": 60, "high": 250, "weight": 1.2},
        {"name": "mid", "low": 150, "high": 2000, "weight": 1.0},
        {"name": "high", "low": 2000, "high": 8000, "weight": 0.7},
    ])
    device_name: Optional[str] = None
    show_debug: bool = False

    def save(self, path: str = "config.json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str = "config.json") -> "Config":
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            bands_raw = data.pop("frequency_bands", None)
            cfg = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            if bands_raw:
                cfg.frequency_bands = bands_raw
            return cfg
        return cls()

    @property
    def history_size(self) -> int:
        return int(self.history_window_s * self.sample_rate / self.hop_size)

    @property
    def min_interval_s(self) -> float:
        return self.min_interval_ms / 1000.0
