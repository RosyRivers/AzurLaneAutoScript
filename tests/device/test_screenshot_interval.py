from types import SimpleNamespace
from itertools import count

import numpy as np
import pytest

import module.device.screenshot as screenshot_module
from module.base.button import Button
from module.device.control import Control
from module.device.screenshot import Screenshot
from module.combat.combat import Combat
from module.handler.login import LoginHandler
from module.ui.ui import UI
import module.base.timer as timer_module
from alas import AzurLaneAutoScript
from module.testing.screenshot_device import ScreenshotDevice


class TestDevice(Screenshot, Control):
    __test__ = False


@pytest.fixture
def device(monkeypatch):
    device = object.__new__(TestDevice)
    device.config = SimpleNamespace(
        Optimization_ScreenshotInterval=0.2, Optimization_CombatScreenshotInterval=0.8,
        Emulator_ScreenshotMethod='nemu_ipc', Emulator_ScreenshotDedithering=False,
        Error_SaveError=False, Emulator_ControlMethod='ADB',
    )
    device.screenshot_interval_set()
    device.orientation = 0
    device._screen_size_checked = True
    device._screen_black_checked = True
    device.screenshot_methods = {'nemu_ipc': lambda: np.ones((720, 1280, 3), dtype=np.uint8)}
    device._screenshot_interval.wait = lambda: None
    monkeypatch.setattr(screenshot_module.time, 'monotonic', lambda: 100.0)
    return device


def test_input_burst_restores_configured_interval_after_confirmation(device):
    device.screenshot_interval_set('wait')
    device.screenshot_interval_set('active')
    assert device._screenshot_interval.limit == 0.1
    device.screenshot_interval_set('confirmed')
    assert device._screenshot_interval.limit == 0.5
    device.screenshot_interval_set()
    assert device._screenshot_interval.limit == 0.2


def test_burst_expires_without_changing_combat_configuration(device, monkeypatch):
    device.screenshot_interval_set('combat')
    device.screenshot_interval_set('active')
    device.screenshot()
    assert device._screenshot_interval.limit == 0.1
    monkeypatch.setattr(screenshot_module.time, 'monotonic', lambda: 103.0)
    device.screenshot()
    assert device._screenshot_interval.limit == 0.8
    assert device.config.Optimization_CombatScreenshotInterval == 0.8


def test_click_without_control_check_still_restores_fast_polling(device):
    device.screenshot_interval_set('wait')
    device.click_methods = {'ADB': lambda x, y: None}
    device.click(Button(area=(), color=(), button=(640, 360, 640, 360)), control_check=False)
    assert device._screenshot_interval.limit == 0.1


def test_reset_cancels_pending_input_burst(device, monkeypatch):
    device.screenshot_interval_set('wait')
    device.screenshot_interval_set('active')
    device.screenshot_interval_set()
    monkeypatch.setattr(screenshot_module.time, 'monotonic', lambda: 103.0)
    device.screenshot()
    assert device._screenshot_interval.limit == 0.2


def test_two_devices_have_independent_intervals():
    first, second = object.__new__(Screenshot), object.__new__(Screenshot)
    first.config = second.config = SimpleNamespace(Emulator_ScreenshotMethod='nemu_ipc')
    first.screenshot_interval_set(0.5)
    second.screenshot_interval_set(1.0)
    assert first._screenshot_interval.limit == 0.5
    assert second._screenshot_interval.limit == 1.0


def test_combat_loading_wait_restores_combat_interval_when_battle_starts(device):
    device.stuck_record_clear = device.click_record_clear = lambda: None
    seen = []
    combat = SimpleNamespace(device=device, phase=0)

    def loop():
        for phase in (0, 1):
            combat.phase = phase
            yield
            seen.append(device._screenshot_interval.limit)

    combat.loop = loop
    combat.appear = lambda *args, **kwargs: False
    for name in ('handle_retirement', 'handle_combat_low_emotion', 'handle_battle_preparation',
                 'handle_combat_automation_confirm', 'handle_story_skip'):
        setattr(combat, name, lambda: False)
    combat.is_combat_loading = lambda: combat.phase == 0
    combat.is_combat_executing = lambda: combat.phase == 1
    Combat.combat_preparation(combat)
    assert seen == [0.5]
    assert device._screenshot_interval.limit == 0.8


def test_ui_confirmation_restores_ordinary_frequency(device, monkeypatch):
    clock = count(100.0)
    monkeypatch.setattr(timer_module, 'time', lambda: next(clock))
    device.screenshot_interval_set('wait')
    device.screenshot_interval_set('active')
    ui = SimpleNamespace(device=device, ui_process_check_button=lambda *args, **kwargs: True)
    UI.ui_click(ui, None, None, skip_first_screenshot=True)
    assert device._screenshot_interval.limit == 0.2


def test_login_confirmation_uses_elapsed_time_in_low_frequency_wait(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(timer_module, 'time', lambda: clock[0])
    login = object.__new__(LoginHandler)
    captures = []

    def screenshot():
        clock[0] += 1.0
        captures.append(clock[0])

    login.device = SimpleNamespace(screenshot=screenshot, get_orientation=lambda: 0,
                                   stuck_record_clear=lambda: None, click_record_clear=lambda: None)
    login.is_in_main = lambda: True
    for name in ('match_template_color', 'appear', 'appear_then_click', 'handle_cn_user_agreement',
                 'handle_popup_confirm', 'handle_urgent_commission', 'ui_page_main_popups'):
        setattr(login, name, lambda *args, **kwargs: False)
    login._handle_app_login()
    assert captures == [101.0, 102.0]


def test_task_start_restores_ordinary_scene(device):
    device.screenshot_interval_set('wait')
    runner = SimpleNamespace(device=device, nothing=lambda: None)
    assert AzurLaneAutoScript.run(runner, 'nothing', skip_first_screenshot=True)
    assert device._screenshot_interval.limit == 0.2


@pytest.mark.parametrize('operation', ['long_click', 'swipe', 'drag'])
def test_fast_polling_starts_after_blocking_input_finishes(device, monkeypatch, operation):
    clock = [100.0]
    monkeypatch.setattr(screenshot_module.time, 'monotonic', lambda: clock[0])
    device.config.Emulator_ControlMethod = 'nemu_ipc'
    device.handle_control_check = lambda *args: None
    device.screenshot_interval_set('combat')

    def blocking_input(*args, **kwargs):
        clock[0] += 4.0

    if operation == 'long_click':
        device.long_click_nemu_ipc = blocking_input
        device.long_click(Button(area=(), color=(), button=(640, 360, 640, 360)), duration=4)
    else:
        setattr(device, operation + '_nemu_ipc', blocking_input)
        getattr(device, operation)((100, 200), (500, 400))
    device.screenshot()
    assert device._screenshot_interval.limit == 0.1


def test_ui_confirmation_still_works_with_offline_screenshot_device(monkeypatch):
    clock = count(100.0)
    monkeypatch.setattr(timer_module, 'time', lambda: next(clock))
    image = np.ones((720, 1280, 3), dtype=np.uint8)
    device = ScreenshotDevice(image)
    ui = SimpleNamespace(device=device, ui_process_check_button=lambda *args, **kwargs: True)
    UI.ui_click(ui, None, None, skip_first_screenshot=True)
    assert device.image is image
