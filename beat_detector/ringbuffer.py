"""Thread-safe ring buffer for audio samples."""

import threading
import numpy as np


class RingBuffer:
    """Lock-protected circular buffer backed by a numpy array."""

    def __init__(self, capacity: int):
        self._buf = np.zeros(capacity, dtype=np.float32)
        self._capacity = capacity
        self._write_pos = 0
        self._lock = threading.Lock()

    def write(self, data: np.ndarray) -> None:
        n = len(data)
        if n > self._capacity:
            data = data[-self._capacity:]
            n = self._capacity
        with self._lock:
            end = self._write_pos + n
            if end <= self._capacity:
                self._buf[self._write_pos:end] = data
            else:
                first = self._capacity - self._write_pos
                self._buf[self._write_pos:] = data[:first]
                self._buf[:end - self._capacity] = data[first:]
            self._write_pos = end % self._capacity

    def read(self, n: int, advance: int = 0) -> np.ndarray:
        """Read `n` samples back from the most recent write position, offset by `advance`."""
        with self._lock:
            start = (self._write_pos + advance - n) % self._capacity
            if start + n <= self._capacity:
                return self._buf[start:start + n].copy()
            else:
                first = self._capacity - start
                result = np.empty(n, dtype=np.float32)
                result[:first] = self._buf[start:]
                result[first:] = self._buf[:n - first]
                return result

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def write_pos(self) -> int:
        with self._lock:
            return self._write_pos
