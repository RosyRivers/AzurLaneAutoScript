import ctypes
from types import SimpleNamespace

import numpy as np
import pytest

from module.base.timer import Timer
from module.device.method.nemu_ipc import NemuIpc, NemuIpcImpl
from module.device.method.adb import Adb
from module.device.method.hermit import Hermit
from module.device.method.maatouch import MaatouchBuilder
from module.device.method.uiautomator_2 import Uiautomator2
from module.device.screenshot import Screenshot
from module.exception import RequestHumanTakeover
import module.device.method.nemu_ipc as nemu_module
from module.device.method.pool import JobTimeout


def screenshot_device(frame, method='ADB', orientation=0):
    device = object.__new__(Screenshot)
    device.config = SimpleNamespace(
        Emulator_ScreenshotMethod=method, Emulator_ScreenshotDedithering=False,
        Emulator_Serial='test', Error_SaveError=True, Error_ScreenshotLength=2,
        Optimization_ScreenshotInterval=0.2, Optimization_CombatScreenshotInterval=1.0,
    )
    device.orientation = orientation
    device.get_orientation = lambda: orientation
    device.screenshot_methods = {method: lambda: frame}
    device._screenshot_interval = Timer(0)
    device._screen_size_checked = False
    device._screen_black_checked = False
    return device


def test_4k_frame_is_normalized_before_error_history():
    frame = np.full((2160, 3840, 3), 40, dtype=np.uint8)
    device = screenshot_device(frame, orientation=1)
    result = device.screenshot()
    assert result.shape == (720, 1280, 3)
    assert device.screenshot_deque[-1]['image'] is result
    assert device.control_point(640, 360) == (1920, 1080)


def test_portrait_4k_frame_rotates_then_normalizes():
    frame = np.full((3840, 2160, 3), 40, dtype=np.uint8)
    result = screenshot_device(frame, orientation=1).screenshot()
    assert result.shape == (720, 1280, 3)


def test_720p_keeps_original_frame_and_coordinates():
    frame = np.full((720, 1280, 3), 40, dtype=np.uint8)
    device = screenshot_device(frame)
    assert device.screenshot() is frame
    assert device.control_point(640, 360) == (640, 360)


def test_unsupported_size_is_rejected_even_after_valid_frame():
    device = screenshot_device(np.full((720, 1280, 3), 40, dtype=np.uint8))
    device.screenshot()
    device.screenshot_methods['ADB'] = lambda: np.ones((900, 1600, 3), dtype=np.uint8)
    with pytest.raises(RequestHumanTakeover):
        device.screenshot()


def test_nemu_normalization_does_not_retain_reused_rgba_buffer():
    raw = np.full((2160, 3840, 4), 40, dtype=np.uint8)
    device = object.__new__(Screenshot)
    device.nemu_ipc = SimpleNamespace(screenshot=lambda: raw)
    first = NemuIpc.screenshot_nemu_ipc(device)
    raw[:] = 90
    second = NemuIpc.screenshot_nemu_ipc(device)
    assert first.shape == second.shape == (720, 1280, 3)
    assert np.all(first == 40)
    assert np.all(second == 90)
    assert device.control_point(100, 200) == (300, 600)


def test_nemu_capture_reuses_buffer_and_reallocates_on_resize():
    ipc = object.__new__(NemuIpcImpl)
    ipc.connect_id = 1
    ipc.display_id = 0
    ipc.width, ipc.height = 3840, 2160
    ipc._pixels_pointer = None
    ipc.get_resolution = lambda on_thread=False: None
    ipc.lib = SimpleNamespace(nemu_capture_display=lambda *args: 0)
    first = ipc._screenshot()
    second = ipc._screenshot()
    assert ctypes.addressof(first.contents) == ctypes.addressof(second.contents)
    ipc.width, ipc.height = 1280, 720
    third = ipc._screenshot()
    assert len(third.contents) == 3686400
    assert ctypes.addressof(first.contents) != ctypes.addressof(third.contents)


def input_device():
    device = object.__new__(Screenshot)
    device._screen_size = (3840, 2160)
    device.sleep = lambda *args: None
    return device


def test_adb_emits_native_points_but_keeps_hierarchy_clicks_native():
    device = input_device()
    commands = []
    device.adb_shell = lambda args: commands.append(args)
    Adb.click_adb.__wrapped__(device, 640, 360)
    Adb.swipe_adb.__wrapped__(device, (100, 200), (500, 400), 0.2)
    assert commands == [['input', 'tap', 1920, 1080],
                        ['input', 'swipe', 300, 600, 1500, 1200, 200]]
    Adb.click_adb.__wrapped__(device, 2000, 1000, native=True)
    assert commands[-1] == ['input', 'tap', 2000, 1000]


def test_uiautomator_inputs_and_drag_path_use_native_points():
    device = input_device()
    events = []
    device.u2 = SimpleNamespace(
        click=lambda x, y: events.append(('click', x, y)),
        long_click=lambda x, y, duration: events.append(('long', x, y)),
        swipe=lambda *args, **kwargs: events.append(('swipe', *args)),
        touch=SimpleNamespace(
            down=lambda x, y: events.append(('down', x, y)),
            move=lambda x, y: events.append(('move', x, y)),
            up=lambda x, y: events.append(('up', x, y)),
        ),
    )
    Uiautomator2.click_uiautomator2.__wrapped__(device, 640, 360)
    Uiautomator2.long_click_uiautomator2.__wrapped__(device, 100, 200, 1)
    Uiautomator2.swipe_uiautomator2.__wrapped__(device, (100, 200), (500, 400), 0.2)
    Uiautomator2._drag_along.__wrapped__(device, [(100, 200, 0), (200, 300, 0), (500, 400, 0)])
    assert events == [('click', 1920, 1080), ('long', 300, 600),
                      ('swipe', 300, 600, 1500, 1200), ('down', 300, 600),
                      ('move', 600, 900), ('up', 1500, 1200)]


def test_nemu_input_converts_before_native_sdk():
    device = input_device()
    events = []
    device.nemu_ipc = SimpleNamespace(
        down=lambda x, y: events.append((x, y)), up=lambda: None,
    )
    NemuIpc.click_nemu_ipc(device, 640, 360)
    NemuIpc.long_click_nemu_ipc(device, 100, 200, 1)
    assert events == [(1920, 1080), (300, 600)]


def test_hermit_input_uses_native_points():
    device = input_device()
    events = []
    device.hermit_send = lambda url, **kwargs: events.append(kwargs)
    Hermit.click_hermit.__wrapped__(device, 640, 360)
    assert events == [{'x': 1920, 'y': 1080}]


def test_maatouch_keeps_existing_once_only_scaling():
    device = input_device()
    device.config = SimpleNamespace(DEVICE_OVER_HTTP=False)
    device.max_x, device.max_y = 3840, 2160
    assert MaatouchBuilder(device).convert(640, 360) == (1920, 1080)


def test_nemu_timeout_replaces_buffer_before_retry(monkeypatch):
    ipc = object.__new__(NemuIpcImpl)
    ipc.connect_id, ipc.display_id = 1, 0
    ipc.width, ipc.height = 1280, 720
    ipc.get_resolution = lambda on_thread=False: None
    ipc.lib = SimpleNamespace(nemu_capture_display=lambda *args: 0)
    old = ctypes.pointer((ctypes.c_ubyte * 3686400)())
    ipc._pixels_pointer = old
    attempts = []

    def run_func(function, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise JobTimeout
        return function()

    ipc.run_func = run_func
    monkeypatch.setattr(nemu_module.time, 'sleep', lambda _: None)
    ipc.screenshot()
    assert ctypes.addressof(ipc._pixels_pointer.contents) != ctypes.addressof(old.contents)


def test_portrait_4k_refreshes_stale_orientation_before_retaining_frame():
    device = screenshot_device(np.full((3840, 2160, 3), 40, dtype=np.uint8))

    def get_orientation():
        device.orientation = 1
        return 1

    device.get_orientation = get_orientation
    assert device.screenshot().shape == (720, 1280, 3)
    assert device.screenshot_deque[-1]['image'].shape == (720, 1280, 3)
