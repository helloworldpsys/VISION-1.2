"""Text-to-speech with a neural online voice and a native offline fallback.

The primary engine is ``edge-tts`` (natural Microsoft neural voices).  If it is
not installed, the machine is offline, or playback fails, Vision falls back to
the OS voice (``say`` / SAPI / ``espeak-ng``) instead of going silent.

Playback and MP3->WAV conversion are delegated to the platform adapter, which
removes the macOS-only ``afplay``/``afconvert`` calls from the old code.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
from pathlib import Path

from .config import Config
from .logging_setup import get_logger
from .platform_utils import PlatformAdapter, run_command
from .state import SpeakingState

logger = get_logger("tts")

ULTRON_FX = [
    "compand",
    "0.02,0.2",
    "6:-70,-60,-20",
    "-5",
    "-90",
    "0.1",
    "pitch",
    "-80",
    "chorus",
    "0.7",
    "0.9",
    "55",
    "0.4",
    "0.25",
    "2",
    "-t",
    "equalizer",
    "2800",
    "1.0q",
    "+3",
    "bass",
    "+3",
    "pad",
    "0",
    "0.5",
    "reverb",
    "20",
    "50",
    "60",
    "norm",
    "-0.5",
]


class Speaker:
    """Serialised text-to-speech facade."""

    def __init__(
        self,
        config: Config,
        platform: PlatformAdapter,
        state: SpeakingState | None = None,
    ) -> None:
        self.config = config
        self.platform = platform
        self.state = state or SpeakingState(config.resolved_paths().state_file or "state.txt")
        self._lock = threading.Lock()
        self._has_edge = _edge_available()
        self._sox = shutil.which("sox") if config.sox_effect else None
        if config.tts_engine == "edge" and not self._has_edge:
            logger.warning("edge-tts is not installed; using the native voice.")

    # ------------------------------------------------------------------ API
    def speak(self, text: str) -> None:
        """Speak *text* synchronously. Never raises."""
        message = self._clean(text)
        if not message:
            return
        with self._lock:
            logger.info("speaking: %s", message)
            print(f"{self.config.assistant_name}: {message}")
            self.state.set_speaking(True)
            try:
                if self._speak_with_config(message):
                    return
                if self.config.tts_engine != "none":
                    logger.warning("All TTS engines failed; text was shown only.")
            finally:
                self.state.set_idle()

    def _speak_with_config(self, message: str) -> bool:
        engine = self.config.tts_engine
        if engine == "none":
            return True
        if engine == "edge" and self._has_edge:
            if self._speak_edge(message):
                return True
            logger.info("edge-tts playback failed; falling back to native voice.")
        if engine in {"edge", "native", "auto"}:
            return self.platform.speak_native(
                message,
                voice=self.config.native_voice,
                rate=self.config.native_rate,
            )
        return False

    # -------------------------------------------------------------- engines
    def _speak_edge(self, text: str) -> bool:
        """edge-tts -> (optional) WAV -> (optional sox) -> platform playback."""
        tmp_dir = Path(tempfile.mkdtemp(prefix="vision-tts-"))
        mp3 = tmp_dir / "speech.mp3"
        wav = tmp_dir / "speech.wav"
        fx = tmp_dir / "speech-fx.wav"
        try:
            asyncio.run(self._edge_save(text, mp3))
            if not mp3.exists() or mp3.stat().st_size == 0:
                logger.warning("edge-tts produced an empty file.")
                return False

            play_path = mp3
            # MP3 works directly on macOS/Linux; Windows needs a WAV.
            if self.platform.os_name != "macos" or self._sox:
                if self._has_ffmpeg_or_afconvert() and self.platform.convert_audio(mp3, wav):
                    play_path = wav
                    if self._sox:
                        fx_ok = self._apply_sox(wav, fx)
                        if fx_ok:
                            play_path = fx
                elif self.platform.os_name == "windows":
                    logger.warning(
                        "ffmpeg is required to play edge-tts audio on Windows; "
                        "using the native voice instead."
                    )
                    return False

            return self.platform.play_audio_file(play_path, volume=self.config.play_volume)
        except Exception as exc:
            logger.warning("edge-tts failed: %s", exc)
            return False
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def _edge_save(self, text: str, path: Path) -> None:
        import edge_tts  # imported lazily: optional at runtime

        communicate = edge_tts.Communicate(
            text,
            self.config.edge_voice,
            rate=self.config.edge_rate,
            pitch=self.config.edge_pitch,
            volume=self.config.edge_volume,
        )
        await communicate.save(str(path))

    def _has_ffmpeg_or_afconvert(self) -> bool:
        if self.platform.os_name == "macos":
            return self.platform.has("afconvert") or self.platform.has("ffmpeg")
        return self.platform.has("ffmpeg")

    def _apply_sox(self, source: Path, target: Path) -> bool:
        assert self._sox is not None
        result = run_command(
            [self._sox, str(source), str(target), *ULTRON_FX],
            timeout=60.0,
        )
        return result.ok

    @staticmethod
    def _clean(text: object) -> str:
        return str(text).replace("\r", " ").replace("\n", " ").strip().lstrip("-").strip()


def _edge_available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except Exception:
        return False
    return True
