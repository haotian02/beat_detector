#!/usr/bin/env python3
"""Beat Detector — simulates keyboard input synced to music drum beats.

Captures system audio via WASAPI loopback, detects drum onsets using
spectral flux analysis, and presses a configurable key on each beat.
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

if __package__:
    from .config import Config
    from .ringbuffer import RingBuffer
    from .capture import AudioCapture
    from .detector import BeatDetector
    from .shared_state import SharedState
    from .web_server import WebServer
else:
    from config import Config
    from ringbuffer import RingBuffer
    from capture import AudioCapture
    from detector import BeatDetector
    from shared_state import SharedState
    from web_server import WebServer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Detect drum beats in system audio and simulate key presses."
    )
    p.add_argument("-c", "--config", default="config.json", help="Path to config JSON")
    p.add_argument("-s", "--sensitivity", type=float, help="Detection sensitivity (1.0-3.0)")
    p.add_argument("-k", "--keybind", help="Key to press on beat (default: s)")
    p.add_argument("-i", "--min-interval", type=int, help="Minimum ms between triggers")
    p.add_argument("-d", "--show-debug", action="store_true", help="Print per-frame debug info")
    p.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    return p.parse_args()


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    args = parse_args()

    # Load config, CLI args override file
    config_path = Path(args.config)
    if config_path.is_absolute():
        cfg = Config.load(str(config_path))
    else:
        # Look in script directory first, then cwd
        script_dir = Path(__file__).resolve().parent
        cfg_path = script_dir / args.config
        if cfg_path.exists():
            cfg = Config.load(str(cfg_path))
        else:
            cfg = Config.load(str(config_path))

    if args.sensitivity is not None:
        cfg.sensitivity = args.sensitivity
    if args.keybind is not None:
        cfg.keybind = args.keybind
    if args.min_interval is not None:
        cfg.min_interval_ms = args.min_interval
    if args.show_debug:
        cfg.show_debug = True

    setup_logging()
    logger = logging.getLogger("main")

    print("=" * 60)
    print("  Beat Detector — Drum-triggered Keyboard Input")
    print("=" * 60)
    print(f"  Keybind:      '{cfg.keybind}'")
    print(f"  Sensitivity:  {cfg.sensitivity:.1f}")
    print(f"  Min interval: {cfg.min_interval_ms}ms")
    print(f"  Frame/hop:    {cfg.frame_size}/{cfg.hop_size} @ {cfg.sample_rate}Hz")
    print(f"  Debug:        {'ON' if cfg.show_debug else 'OFF'}")
    print("=" * 60)
    print("Press Ctrl+C to stop.\n")

    # Shared state for web control panel
    state = SharedState(cfg)

    # Ring buffer: hold ~200ms of audio
    ring_capacity = int(cfg.sample_rate * 0.2)
    ring = RingBuffer(ring_capacity)

    capture = AudioCapture(ring, sample_rate=cfg.sample_rate, buffer_duration_ms=20)
    detector = BeatDetector(ring, cfg, state)

    # Start web control panel
    web = WebServer(state, port=8080)
    web.start()

    running = True

    def on_signal(signum, frame):
        nonlocal running
        logger.info("Received signal %d, shutting down...", signum)
        running = False

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    try:
        capture.start()
        # Give capture a moment to initialize
        time.sleep(0.3)
        detector.start()

        while running:
            time.sleep(0.1)

    except Exception:
        logger.exception("Fatal error")
    finally:
        logger.info("Shutting down...")
        detector.stop()
        capture.stop()
        print("\nBeat Detector stopped.")


if __name__ == "__main__":
    main()
