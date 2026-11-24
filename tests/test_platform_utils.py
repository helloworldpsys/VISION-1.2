"""Platform abstraction tests using a fake subprocess runner.

These tests prove the macOS/Windows/Linux mappings without executing anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vision.platform_utils import (
    CommandResult,
    create_platform,
    detect_os,
    reset_platform_cache,
)


class RecordingRunner:
    def __init__(self, result: CommandResult | None = None) -> None:
        self.calls: list[list[str]] = []
        self.result = result or CommandResult(ok=True)
        self.kwargs: list[dict] = []

    def __call__(self, argv, timeout=15.0, **kwargs):
        self.calls.append(list(argv))
        self.kwargs.append({"timeout": timeout, **kwargs})
        return self.result


def mac(**kwargs):
    runner = kwargs.pop("runner", RecordingRunner())
    return (
        create_platform("macos", runner=runner, which=lambda name: f"/usr/bin/{name}", **kwargs),
        runner,
    )


def windows(**kwargs):
    runner = kwargs.pop("runner", RecordingRunner())
    return (
        create_platform(
            "windows", runner=runner, which=lambda name: f"C:/tools/{name}.exe", **kwargs
        ),
        runner,
    )


def linux(**kwargs):
    runner = kwargs.pop("runner", RecordingRunner())
    return (
        create_platform("linux", runner=runner, which=lambda name: f"/usr/bin/{name}", **kwargs),
        runner,
    )


def test_detect_os_override(monkeypatch) -> None:
    monkeypatch.setenv("VISION_OS", "windows")
    assert detect_os() == "windows"
    monkeypatch.setenv("VISION_OS", "mac")
    assert detect_os() == "macos"
    monkeypatch.setenv("VISION_OS", "linux")
    assert detect_os() == "linux"


def test_platform_cache_can_be_reset() -> None:
    reset_platform_cache()


# --------------------------------------------------------------------- macOS
def test_mac_native_speech() -> None:
    platform, runner = mac()
    assert platform.speak_native("hello", voice="Ralph", rate=170) is True
    assert runner.calls[0][:4] == ["say", "-v", "Ralph", "-r"]
    assert runner.calls[0][-1] == "hello"


def test_mac_play_audio_uses_afplay() -> None:
    platform, runner = mac()
    assert platform.play_audio_file("/tmp/a.wav", volume=2.5) is True
    assert runner.calls[0] == ["afplay", "-v", "2.50", "/tmp/a.wav"]


def test_mac_open_apps() -> None:
    platform, runner = mac()
    assert platform.open_app("chrome") is True
    assert runner.calls[-1] == ["open", "-a", "Google Chrome"]
    assert platform.open_app("safari") is True
    assert runner.calls[-1] == ["open", "-a", "Safari"]


def test_mac_screenshot() -> None:
    platform, runner = mac()
    assert platform.take_screenshot("/tmp/s.png") is True
    assert runner.calls[0] == ["screencapture", "-x", "/tmp/s.png"]


def test_mac_volume_set_and_mute() -> None:
    platform, runner = mac()
    assert platform.set_volume(40) is True
    assert runner.calls[0][:2] == ["osascript", "-e"]
    assert "set volume output volume 40" in runner.calls[0][2]
    assert platform.set_mute(True) is True
    assert "with output muted" in runner.calls[-1][2]


def test_mac_volume_get() -> None:
    runner = RecordingRunner(CommandResult(ok=True, stdout="37"))
    platform, _ = mac(runner=runner)
    assert platform.get_volume() == 37


def test_mac_battery_parsing() -> None:
    runner = RecordingRunner(
        CommandResult(
            ok=True,
            stdout="Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t85%; discharging; 4:12 remaining",
        )
    )
    platform, _ = mac(runner=runner)
    assert platform.get_battery() == "Battery is at 85 percent and not charging"


def test_mac_convert_audio() -> None:
    platform, runner = mac()
    assert platform.convert_audio("a.mp3", "a.wav") is True
    assert runner.calls[0][0] == "afconvert"


# ------------------------------------------------------------------- Windows
def test_windows_native_speech_uses_sapi() -> None:
    platform, runner = windows()
    assert platform.speak_native("hello", rate=180) is True
    assert runner.calls[0][0] == "powershell"
    script = runner.calls[0][-1]
    assert "System.Speech" in script
    assert "Speak('hello')" in script


def test_windows_open_chrome() -> None:
    platform, runner = windows()
    assert platform.open_app("chrome") is True
    assert runner.calls[0] == ["cmd", "/c", "start", "", "chrome"]


def test_windows_screenshot_script() -> None:
    platform, runner = windows()
    target = Path("shot.png").resolve()
    assert platform.take_screenshot(target) is True
    script = runner.calls[0][-1]
    assert "CopyFromScreen" in script
    assert str(target).replace("'", "''") in script


def test_windows_battery_json() -> None:
    runner = RecordingRunner(
        CommandResult(ok=True, stdout='{"EstimatedChargeRemaining": 72, "BatteryStatus": 2}')
    )
    platform, _ = windows(runner=runner)
    assert platform.get_battery() == "Battery is at 72 percent and charging"


def test_windows_convert_requires_ffmpeg() -> None:
    platform, runner = windows()
    assert platform.convert_audio("a.mp3", "a.wav") is True
    assert runner.calls[0][0].endswith("ffmpeg.exe")


# --------------------------------------------------------------------- Linux
def test_linux_native_speech() -> None:
    platform, runner = linux()
    assert platform.speak_native("hello") is True
    assert runner.calls[0][0].endswith("espeak-ng")


def test_linux_volume_uses_pactl() -> None:
    platform, runner = linux()
    assert platform.set_volume(25) is True
    assert runner.calls[0][:3] == ["/usr/bin/pactl", "set-sink-volume", "@DEFAULT_SINK@"]
    assert runner.calls[0][3] == "25%"


def test_linux_open_path_uses_xdg_open() -> None:
    platform, runner = linux()
    assert platform.open_path("/tmp/file.txt") is True
    assert runner.calls[0] == ["/usr/bin/xdg-open", "/tmp/file.txt"]


def test_linux_screenshot_prefers_gnome_screenshot() -> None:
    platform, runner = linux()
    assert platform.take_screenshot("/tmp/s.png") is True
    assert runner.calls[0][:2] == ["/usr/bin/gnome-screenshot", "-f"]


def test_missing_command_is_not_fatal() -> None:
    runner = RecordingRunner(CommandResult(ok=False, error="not found"))
    platform, _ = mac(runner=runner)
    assert platform.set_volume(10) is False
    assert platform.play_audio_file("x.wav") is False


def test_url_opening_is_injectable() -> None:
    opened: list[str] = []

    def opener(url, new=2):
        opened.append(url)
        return True

    platform, _ = mac(url_opener=opener)
    assert platform.open_app("youtube") is True
    assert opened == ["https://youtube.com"]


@pytest.mark.parametrize("name", ["chrome", "Google Chrome", "CHROME"])
def test_app_aliases(name: str) -> None:
    platform, _ = mac()
    assert platform.normalize_app(name) == "chrome"
