"""Real-time beat detection via spectral flux with adaptive thresholding."""

import logging
import threading
import time
from collections import deque

import numpy as np

if __package__:
    from .config import Config
    from .ringbuffer import RingBuffer
    from .key_sender import press_key
else:
    from config import Config
    from ringbuffer import RingBuffer
    from key_sender import press_key

logger = logging.getLogger(__name__)


class BeatDetector:
    """Processes audio frames from a ring buffer, detects onsets, and triggers key presses."""

    def __init__(self, ring_buffer: RingBuffer, config: Config, state=None):
        self._ring = ring_buffer
        self._cfg = config
        self._state = state

        n_bins = config.frame_size // 2 + 1
        self._hann = np.hanning(config.frame_size).astype(np.float32)
        self._prev_spectrum = np.zeros(n_bins, dtype=np.float32)
        self._history: deque[float] = deque(maxlen=config.history_size)
        self._last_onset = 0.0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Pre-compute frequency bin indices for each band
        self._band_bins = []
        freq_per_bin = config.sample_rate / config.frame_size
        for band in config.frequency_bands:
            lo = max(0, int(band["low"] / freq_per_bin))
            hi = min(n_bins, int(band["high"] / freq_per_bin) + 1)
            self._band_bins.append((lo, hi, band["weight"]))

        logger.info("Detector initialized: frame=%d hop=%d sensitivity=%.1f history=%d",
                     config.frame_size, config.hop_size,
                     config.sensitivity, config.history_size)

    def _process_frame(self, frame: np.ndarray) -> tuple[float, float, bool]:
        """Process one frame. Returns (flux, threshold, is_beat)."""
        # Hann window
        windowed = frame * self._hann

        # FFT -> magnitude spectrum
        spectrum = np.abs(np.fft.rfft(windowed))

        # Spectral flux: sum of positive differences (onset = energy increase)
        diff = spectrum - self._prev_spectrum
        diff[diff < 0] = 0

        # Weighted multi-band flux
        flux = 0.0
        for lo, hi, weight in self._band_bins:
            flux += weight * np.sum(diff[lo:hi])

        self._prev_spectrum = spectrum

        # Adaptive threshold — resize history if config changed
        target_size = self._cfg.history_size
        if self._history.maxlen != target_size:
            self._history = deque(self._history, maxlen=target_size)
        self._history.append(flux)
        if len(self._history) < 4:
            return flux, float("inf"), False

        mean = np.mean(self._history)
        std = np.std(self._history) + 1e-10
        threshold = mean + self._cfg.sensitivity * std

        noise_floor = max(threshold, self._cfg.noise_floor)
        is_beat = False
        if flux > noise_floor:
            now = time.perf_counter()
            if now - self._last_onset >= self._cfg.min_interval_s:
                self._last_onset = now
                is_beat = True

        return flux, threshold, is_beat

    def _run(self):
        """Main processing loop. Reads from ring buffer, processes frames, triggers keys."""
        logger.info("Detector loop started.")
        frame_size = self._cfg.frame_size
        last_write_pos = self._ring.write_pos

        # Wait for the ring buffer to fill with at least one frame of data
        while not self._stop_event.is_set():
            time.sleep(0.01)
            frame = self._ring.read(frame_size, advance=0)
            if np.count_nonzero(frame) > 0:
                break

        try:
            while not self._stop_event.is_set():
                # Wait for new audio data to arrive
                current_pos = self._ring.write_pos
                if current_pos == last_write_pos:
                    time.sleep(0.001)
                    continue

                last_write_pos = current_pos

                frame = self._ring.read(frame_size, advance=0)
                flux, threshold, is_beat = self._process_frame(frame)

                if self._state:
                    self._state.update(flux, threshold, is_beat)

                if self._cfg.show_debug:
                    ratio = flux / (threshold + 1e-10)
                    ts = time.strftime("%H:%M:%S", time.localtime())
                    if is_beat:
                        print(f"[{ts}] >>> KEY '{self._cfg.keybind}' SENT <<< "
                              f"FLUX: {flux:.0f} THR: {threshold:.0f} RATIO: {ratio:.2f}")
                    else:
                        print(f"[{ts}]     FLUX: {flux:6.0f} THR: {threshold:6.0f} RATIO: {ratio:.2f}")

                if is_beat and self._cfg.enabled:
                    threading.Thread(target=press_key, args=(self._cfg.keybind, 15),
                                     daemon=True).start()

        except Exception:
            logger.exception("Detector loop error")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="beat-detector")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Detector stopped.")
