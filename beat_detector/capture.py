"""WASAPI loopback audio capture via ctypes."""

import ctypes
import logging
import threading
from ctypes import wintypes, byref, POINTER, c_void_p, c_float, c_ubyte

import numpy as np

if __package__:
    from .ringbuffer import RingBuffer
else:
    from ringbuffer import RingBuffer

logger = logging.getLogger(__name__)

# ── COM / WASAPI constants ──────────────────────────────────────────────────

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 1

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000

# Data format: WAVE_FORMAT_EXTENSIBLE with float32
WAVE_FORMAT_EXTENSIBLE = 0xFFFE
KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = ctypes.create_string_buffer(
    bytes([0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x10, 0x00, 0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71]),
    16,
)

AUDCLNT_BUFFERFLAGS_SILENT = 0x2
AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY = 0x1

WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF

# ── GUIDs ───────────────────────────────────────────────────────────────────


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(data1, data2, data3, b0, b1, b2, b3, b4, b5, b6, b7):
    return GUID(data1, data2, data3, (b0, b1, b2, b3, b4, b5, b6, b7))


CLSID_MMDeviceEnumerator = _guid(0xBCDE0395, 0xE52F, 0x467C,
                                  0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E)
IID_IMMDeviceEnumerator = _guid(0xA95664D2, 0x9614, 0x4F35,
                                 0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6)
IID_IAudioClient = _guid(0x1CB9AD4C, 0xDBFA, 0x4C32,
                          0xB1, 0x78, 0xC2, 0xF5, 0x68, 0xA7, 0x03, 0xB2)
IID_IAudioCaptureClient = _guid(0xC8ADBD64, 0xE71E, 0x48A0,
                                 0xA4, 0xDE, 0x18, 0x5C, 0x39, 0x5C, 0xD3, 0x17)

EDataFlow_eRender = 0
ERole_eConsole = 0

# ── WAVEFORMAT structures ───────────────────────────────────────────────────


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


# Type alias for the GUID used in WAVEFORMATEXTENSIBLE
_SubFormat_GUID = ctypes.c_ubyte * 16


class WAVEFORMATEXTENSIBLE(ctypes.Structure):
    _fields_ = [
        ("Format", WAVEFORMATEX),
        ("Samples", wintypes.WORD),
        ("dwChannelMask", wintypes.DWORD),
        ("SubFormat", _SubFormat_GUID),
    ]


# ── COM vtable helpers ──────────────────────────────────────────────────────

# The vtable pointer is the first field of every COM object (pointer to pointer array)
_VTBLOB = ctypes.POINTER(ctypes.c_void_p)


def _com_call(this, vtbl_index, restype, argtypes, *args):
    """Call a COM method via its vtable offset."""
    proto = ctypes.WINFUNCTYPE(restype, *argtypes)
    vtbl = ctypes.cast(this, POINTER(_VTBLOB)).contents
    func = proto(ctypes.cast(vtbl[vtbl_index], ctypes.c_void_p).value)
    return func(this, *args)


# ── IMMDeviceEnumerator ─────────────────────────────────────────────────────

def _de_EnumAudioEndpoints(this, dataFlow, dwStateMask, devices):
    return _com_call(this, 3, ctypes.c_long,
                     [c_void_p, wintypes.DWORD, wintypes.DWORD, POINTER(c_void_p)],
                     dataFlow, dwStateMask, devices)


def _de_GetDefaultAudioEndpoint(this, dataFlow, role, device):
    return _com_call(this, 4, ctypes.c_long,
                     [c_void_p, wintypes.DWORD, wintypes.DWORD, POINTER(c_void_p)],
                     dataFlow, role, device)


# ── IMMDevice ───────────────────────────────────────────────────────────────

def _dev_Activate(this, iid, clsctx, activation_params, interface_ptr):
    return _com_call(this, 3, ctypes.c_long,
                     [c_void_p, ctypes.c_void_p, wintypes.DWORD, c_void_p, POINTER(c_void_p)],
                     iid, clsctx, activation_params, interface_ptr)


# ── IAudioClient ────────────────────────────────────────────────────────────

def _ac_Initialize(this, shareMode, streamFlags, hnsBufferDuration,
                   hnsPeriodicity, pFormat, audioSessionGuid):
    return _com_call(this, 3, ctypes.c_long,
                     [c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_longlong,
                      ctypes.c_longlong, c_void_p, c_void_p],
                     shareMode, streamFlags, hnsBufferDuration, hnsPeriodicity,
                     pFormat, audioSessionGuid)


def _ac_GetBufferSize(this, num_frames):
    return _com_call(this, 4, ctypes.c_long,
                     [c_void_p, POINTER(wintypes.UINT)],
                     num_frames)


def _ac_GetStreamLatency(this, latency):
    return _com_call(this, 5, ctypes.c_long,
                     [c_void_p, POINTER(ctypes.c_longlong)],
                     latency)


def _ac_GetMixFormat(this, ppFormat):
    # ppFormat is WAVEFORMATEX** but we just need a pointer
    return _com_call(this, 8, ctypes.c_long,
                     [c_void_p, POINTER(c_void_p)],
                     ppFormat)


def _ac_Start(this):
    return _com_call(this, 10, ctypes.c_long, [c_void_p])


def _ac_Stop(this):
    return _com_call(this, 11, ctypes.c_long, [c_void_p])


def _ac_SetEventHandle(this, eventHandle):
    return _com_call(this, 13, ctypes.c_long,
                     [c_void_p, wintypes.HANDLE], eventHandle)


def _ac_GetService(this, iid, ppv):
    return _com_call(this, 14, ctypes.c_long,
                     [c_void_p, ctypes.c_void_p, POINTER(c_void_p)],
                     iid, ppv)


# ── IAudioCaptureClient ─────────────────────────────────────────────────────

def _cc_GetBuffer(this, ppData, pNumFramesToRead, pdwFlags, pu64DevicePosition,
                  pu64QPCPosition):
    return _com_call(this, 3, ctypes.c_long,
                     [c_void_p, POINTER(POINTER(c_ubyte)),
                      POINTER(wintypes.DWORD), POINTER(wintypes.DWORD),
                      POINTER(ctypes.c_ulonglong), POINTER(ctypes.c_ulonglong)],
                     ppData, pNumFramesToRead, pdwFlags,
                     pu64DevicePosition, pu64QPCPosition)


def _cc_ReleaseBuffer(this, numFramesRead):
    return _com_call(this, 4, ctypes.c_long,
                     [c_void_p, wintypes.DWORD],
                     numFramesRead)


def _cc_GetNextPacketSize(this, pPacketSize):
    return _com_call(this, 5, ctypes.c_long,
                     [c_void_p, POINTER(wintypes.DWORD)],
                     pPacketSize)


# ── DLLs ────────────────────────────────────────────────────────────────────

_ole32 = ctypes.windll.ole32
_kernel32 = ctypes.windll.kernel32


# ── AudioCapture ────────────────────────────────────────────────────────────

class AudioCapture:
    """Captures system audio via WASAPI loopback into a ring buffer."""

    def __init__(self, ring_buffer: RingBuffer, sample_rate: int = 44100,
                 buffer_duration_ms: int = 20):
        self._ring = ring_buffer
        self._sample_rate = sample_rate
        self._buffer_duration_ms = buffer_duration_ms
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # COM objects
        self._enumerator = c_void_p()
        self._device = c_void_p()
        self._audio_client = c_void_p()
        self._capture_client = c_void_p()
        self._event_handle = wintypes.HANDLE()
        self._channels = 0
        self._mix_rate = 0

    def _init_com(self):
        _ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)

        # Create device enumerator
        hr = _ole32.CoCreateInstance(
            byref(CLSID_MMDeviceEnumerator), None, CLSCTX_INPROC_SERVER,
            byref(IID_IMMDeviceEnumerator), byref(self._enumerator),
        )
        if hr < 0:
            raise OSError(f"CoCreateInstance(MMDeviceEnumerator) failed: 0x{hr & 0xFFFFFFFF:08X}")

    def _open_loopback(self):
        # Get default render endpoint
        hr = _de_GetDefaultAudioEndpoint(self._enumerator, EDataFlow_eRender,
                                         ERole_eConsole, byref(self._device))
        if hr < 0:
            raise OSError(f"GetDefaultAudioEndpoint failed: 0x{hr & 0xFFFFFFFF:08X}")

        # Activate IAudioClient
        hr = _dev_Activate(self._device, byref(IID_IAudioClient), CLSCTX_INPROC_SERVER,
                           None, byref(self._audio_client))
        if hr < 0:
            raise OSError(f"Activate(IAudioClient) failed: 0x{hr & 0xFFFFFFFF:08X}")

        # Get mix format to determine native sample rate and channels
        mix_format_ptr = c_void_p()
        hr = _ac_GetMixFormat(self._audio_client, byref(mix_format_ptr))
        if hr < 0:
            raise OSError(f"GetMixFormat failed: 0x{hr & 0xFFFFFFFF:08X}")

        # Read format tag to determine if WAVEFORMATEX or WAVEFORMATEXTENSIBLE
        fmt_tag = ctypes.cast(mix_format_ptr, POINTER(wintypes.WORD)).contents.value
        if fmt_tag == WAVE_FORMAT_EXTENSIBLE:
            wfx = ctypes.cast(mix_format_ptr, POINTER(WAVEFORMATEXTENSIBLE)).contents
            self._channels = wfx.Format.nChannels
            self._mix_rate = wfx.Format.nSamplesPerSec
            wfx_ptr = mix_format_ptr
        else:
            wfx = ctypes.cast(mix_format_ptr, POINTER(WAVEFORMATEX)).contents
            self._channels = wfx.nChannels
            self._mix_rate = wfx.nSamplesPerSec
            wfx_ptr = mix_format_ptr

        logger.info("WASAPI mix format: %d Hz, %d channels, tag=0x%04X",
                     self._mix_rate, self._channels, fmt_tag)
        self._sample_rate = self._mix_rate

        # Create event handle
        self._event_handle = _kernel32.CreateEventW(None, False, False, None)
        if not self._event_handle:
            _ole32.CoTaskMemFree(mix_format_ptr)
            raise OSError("CreateEventW failed")

        # Buffer duration in 100-nanosecond units
        hns_buf = int(self._buffer_duration_ms * 10000)

        hr = _ac_Initialize(
            self._audio_client,
            AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
            hns_buf, 0, wfx_ptr, None,
        )
        if hr < 0:
            _ole32.CoTaskMemFree(mix_format_ptr)
            raise OSError(f"IAudioClient::Initialize failed: 0x{hr & 0xFFFFFFFF:08X}")

        hr = _ac_SetEventHandle(self._audio_client, self._event_handle)
        if hr < 0:
            _ole32.CoTaskMemFree(mix_format_ptr)
            raise OSError(f"SetEventHandle failed: 0x{hr & 0xFFFFFFFF:08X}")

        # Get IAudioCaptureClient
        hr = _ac_GetService(self._audio_client, byref(IID_IAudioCaptureClient),
                            byref(self._capture_client))
        if hr < 0:
            _ole32.CoTaskMemFree(mix_format_ptr)
            raise OSError(f"GetService(IAudioCaptureClient) failed: 0x{hr & 0xFFFFFFFF:08X}")

        # Get buffer size and latency
        buf_frames = wintypes.UINT()
        _ac_GetBufferSize(self._audio_client, byref(buf_frames))
        latency = ctypes.c_longlong()
        _ac_GetStreamLatency(self._audio_client, byref(latency))
        logger.info("WASAPI initialized: buffer=%d frames, latency=%.1fms, rate=%d",
                     buf_frames.value, latency.value / 10000.0, self._sample_rate)

        # Free the mix format
        _ole32.CoTaskMemFree(mix_format_ptr)

    def _capture_loop(self):
        """Runs in a dedicated thread. Waits for audio events and reads data."""
        try:
            self._init_com()
            self._open_loopback()

            hr = _ac_Start(self._audio_client)
            if hr < 0:
                raise OSError(f"IAudioClient::Start failed: 0x{hr & 0xFFFFFFFF:08X}")

            logger.info("Capture loop started.")

            while not self._stop_event.is_set():
                ret = _kernel32.WaitForSingleObject(self._event_handle, 1000)
                if ret != WAIT_OBJECT_0:
                    continue

                # Read all available packets
                while True:
                    pkt_size = wintypes.DWORD()
                    hr = _cc_GetNextPacketSize(self._capture_client, byref(pkt_size))
                    if hr < 0 or pkt_size.value == 0:
                        break

                    data_ptr = POINTER(c_ubyte)()
                    num_frames = wintypes.DWORD()
                    flags = wintypes.DWORD()
                    dev_pos = ctypes.c_ulonglong()
                    qpc_pos = ctypes.c_ulonglong()

                    hr = _cc_GetBuffer(self._capture_client, byref(data_ptr),
                                       byref(num_frames), byref(flags),
                                       byref(dev_pos), byref(qpc_pos))
                    if hr < 0:
                        break

                    if num_frames.value > 0 and not (flags.value & AUDCLNT_BUFFERFLAGS_SILENT):
                        # Convert byte data to numpy float32 array
                        sample_count = num_frames.value * self._channels
                        samples = np.ctypeslib.as_array(
                            ctypes.cast(data_ptr, POINTER(c_float)),
                            shape=(sample_count,)
                        ).copy()

                        # Convert interleaved stereo to mono by averaging
                        if self._channels == 2:
                            mono = (samples[0::2] + samples[1::2]) * 0.5
                        else:
                            mono = samples

                        self._ring.write(mono.astype(np.float32))

                    _cc_ReleaseBuffer(self._capture_client, num_frames.value)

        except Exception:
            logger.exception("Capture loop error")
        finally:
            self._cleanup()

    def _cleanup(self):
        if self._audio_client:
            try:
                _ac_Stop(self._audio_client)
            except Exception:
                pass
        if self._event_handle:
            _kernel32.CloseHandle(self._event_handle)
            self._event_handle = None
        if self._capture_client:
            self._capture_client = c_void_p()
        if self._audio_client:
            self._audio_client = c_void_p()
        if self._device:
            self._device = c_void_p()
        if self._enumerator:
            self._enumerator = c_void_p()
        _ole32.CoUninitialize()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="wasapi-capture")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("Audio capture stopped.")
