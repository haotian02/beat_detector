"""Low-latency keyboard simulation via Windows keybd_event / SendInput API."""

import ctypes
import time
import sys

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

# Virtual key codes A-Z
VK_CODES = {chr(c): c for c in range(0x41, 0x5B)}
VK_CODES.update({str(i): 0x30 + i for i in range(10)})

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def vk_code(key: str) -> int:
    upper = key.upper()
    if upper in VK_CODES:
        return VK_CODES[upper]
    return ord(upper)


def press_key(key: str = "s", hold_ms: int = 20) -> None:
    """Send a key down, wait hold_ms, then key up via keybd_event."""
    vk = vk_code(key)

    _user32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold_ms / 1000.0)
    _user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


if __name__ == "__main__":
    from time import sleep
    print("Sending 's' key in 2 seconds — focus a text editor now!")
    sleep(2)
    press_key("s", hold_ms=50)
    print("Done. Check if 's' appeared in your text editor.")
