# 4K Resolution Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** Run existing Alas tasks on 3840x2160 MuMu displays with economical capture.
**Architecture:** Keep recognition at 1280x720; normalize frames and input at device boundaries. Extend the existing screenshot interval API for declared waits and temporary input bursts.
**Tech Stack:** Python 3.7, NumPy, OpenCV, ctypes, existing emulator SDKs, pytest.
**Spec:** ../specs/2026-11-02-4k-design.md

## Global Constraints
- No new runtime dependencies, alternate rendering resolutions, or asset rebuild.
- Keep existing 720p behavior and manual/exercise combat requirements.
- Work in the user-requested checkout; leave changes reviewable on codex/4k-resolution.

## Review Focus
- A reused raw buffer must never mutate retained recognition/error images.
- Resolution changes, rotations and retries must not corrupt buffers or scale twice.
- ADB, uiautomator2, nemu, builders and direct dorm inputs use different coordinate spaces.
- Wait/fast intervals must restore on completion, exceptions and task switches.
- Low-frequency waits must not extend count-based confirmation or stuck timers.

### Task 1: Capture and recognition
Files: module/device/screenshot.py, module/device/connection.py,
module/device/method/nemu_ipc.py, module/device/method/uiautomator_2.py,
module/device/method/droidcast.py, tests/device/test_resolution.py.
Interfaces: Connection.control_point(x, y) maps logical points using _screen_size;
Screenshot normalizes 4K to 720p before retaining frames.
- [x] Write tests for 4K/720p capture, retained-frame independence, rotation and buffer resize.
- [x] Run targeted tests and observe missing behavior fail.
- [x] Implement minimal capture-buffer reuse and early normalization; preserve raw capture lifetime on timeout.
- [x] Run targeted tests and record results.

### Task 2: Native input coordinates
Files: existing ADB/uiautomator2/nemu/Hermit methods, module/dorm/dorm.py,
tests/device/test_resolution.py.
Interfaces: Physical input methods consume logical points except explicitly native hierarchy clicks.
- [x] Test emitted native 4K points, drag paths, raw hierarchy coordinates and existing builder scaling.
- [x] Observe failing tests; implement once-only coordinate mapping.
- [x] Run targeted regression tests.

### Task 3: Scene screenshot frequency
Files: module/device/screenshot.py, module/device/control.py, alas.py,
module/handler/login.py, module/combat/combat.py, module/ui/ui.py,
tests/device/test_screenshot_interval.py.
Interfaces: screenshot_interval_set('wait') declares noncritical waits;
screenshot_interval_set('active') temporarily overrides the configured scene;
explicit completion restores the scene/normal interval.
- [x] Test ordinary/combat intervals, input bursts, explicit waits and restoration with a fake clock.
- [x] Observe failures; implement using existing Timer and entry points.
- [x] Integrate loading waits with time-based confirmation; retain combat/exercise safety.
- [x] Run targeted tests and the whole suite; distinguish pre-existing failures.

### Task 4: Verification and usage
- [x] Read the complete diff and obtain a fresh code review.
- [x] Check real 4K capture, retained image dimensions and representative UI recognition.
- [x] Benchmark the new path and validate emitted coordinates without game input.
- [x] Document usage and report precise limits of validation. Leave changes uncommitted for user review.
