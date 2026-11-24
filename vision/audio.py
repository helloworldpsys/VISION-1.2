"""Microphone, speech-to-text and double-clap detection.

Three layers of resilience, because audio is the most fragile part of a
desktop assistant:

1. **Capture** - SpeechRecognition/PyAudio is preferred; if PyAudio is missing
   or fails to open a device, ``sounddevice`` is used instead.  If neither
   works, the assistant degrades to typed commands.
2. **Recognition** - Google's free web service is used when online.  A local
   Vosk model is used as the offline fallback (or first, when configured).
3. **Runtime** - repeated device/network errors reset the recognizer and, after
   ``MAX_AUDIO_FAILURES``, permanently switch the session to text input instead
   of spinning forever.

Heavy imports (pyaudio, sounddevice, vosk) are all lazy.
"""

from __future__ import annotations

import array
import contextlib
import math
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .logging_setup import get_logger

logger = get_logger("audio")


class AudioUnavailable(RuntimeError):
    """No capture backend could be initialised."""


def _import_sr():
    import speech_recognition as sr  # imported lazily

    return sr


@dataclass
class ListenSettings:
    timeout: int = 4
    phrase_time: int = 8


class CaptureBackend(ABC):
    name = "base"

    def __init__(self, config: Config) -> None:
        self.config = config

    @abstractmethod
    def listen(self, settings: ListenSettings) -> Any:
        """Return ``speech_recognition.AudioData`` or ``None`` on timeout."""

    def calibrate(self, duration: float = 0.8, force: bool = False) -> None:
        return None

    def close(self) -> None:
        return None


class PyAudioBackend(CaptureBackend):
    """SpeechRecognition's default PyAudio-backed microphone."""

    name = "pyaudio"

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.sr = _import_sr()
        self.recognizer = self._make_recognizer()
        self._lock = threading.Lock()
        self._last_calibration = 0.0
        # Probe the device now so a missing microphone is detected early.
        with self.sr.Microphone(device_index=config.microphone_device) as source:
            _ = source

    def _make_recognizer(self):
        recognizer = self.sr.Recognizer()
        recognizer.pause_threshold = 0.6
        recognizer.phrase_threshold = 0.2
        recognizer.non_speaking_duration = 0.3
        recognizer.energy_threshold = 150
        recognizer.dynamic_energy_threshold = True
        return recognizer

    def calibrate(self, duration: float = 0.8, force: bool = False) -> None:
        interval = max(10, self.config.calibration_interval)
        now = time.time()
        if not force and self._last_calibration and now - self._last_calibration < interval:
            return
        try:
            logger.info("Calibrating microphone for ambient noise...")
            with (
                self._lock,
                self.sr.Microphone(device_index=self.config.microphone_device) as source,
            ):
                self.recognizer.adjust_for_ambient_noise(source, duration=duration)
            self.recognizer.energy_threshold = max(80, min(250, self.recognizer.energy_threshold))
            self._last_calibration = time.time()
            logger.info("Microphone calibrated (energy %.0f)", self.recognizer.energy_threshold)
        except Exception as exc:
            logger.warning("Microphone calibration failed: %s", exc)

    def listen(self, settings: ListenSettings):
        with self._lock:
            try:
                with self.sr.Microphone(device_index=self.config.microphone_device) as source:
                    return self.recognizer.listen(
                        source,
                        timeout=max(1, int(settings.timeout)),
                        phrase_time_limit=max(1, int(settings.phrase_time)),
                    )
            except self.sr.WaitTimeoutError:
                return None

    def reset(self) -> None:
        self.recognizer = self._make_recognizer()


class SoundDeviceBackend(CaptureBackend):
    """Fallback capture using PortAudio through ``sounddevice``.

    Records with a simple energy gate instead of a full VAD: start when the
    input is louder than the ambient floor, stop after 0.9 s of silence.
    """

    name = "sounddevice"
    SAMPLE_RATE = 16_000
    BLOCK_MS = 30

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        import sounddevice as sd  # lazy

        self.sd = sd
        self.sr = _import_sr()
        self._device = config.microphone_device
        self._check_device()

    def _check_device(self) -> None:
        try:
            devices = self.sd.query_devices()
        except Exception as exc:
            raise AudioUnavailable(f"sounddevice query failed: {exc}") from exc
        if not any(int(d.get("max_input_channels", 0)) > 0 for d in devices):
            raise AudioUnavailable("no input device reported by sounddevice")
        if self._device is not None:
            info = self.sd.query_devices(self._device)
            if int(info.get("max_input_channels", 0)) <= 0:
                raise AudioUnavailable(f"device {self._device} has no input channels")

    def _ambient_floor(self) -> float:
        try:
            frames = int(self.SAMPLE_RATE * 0.4)
            data = self.sd.rec(
                frames, samplerate=self.SAMPLE_RATE, channels=1, dtype="int16", device=self._device
            )
            self.sd.wait()
            return max(80.0, _rms_array(data) * 2.5)
        except Exception:
            return 300.0

    def listen(self, settings: ListenSettings):
        threshold = self._ambient_floor()
        block = int(self.SAMPLE_RATE * self.BLOCK_MS / 1000)
        collected: list[bytes] = []
        speech_started = False
        silent_ms = 0
        started = time.monotonic()
        deadline = started + max(1, settings.timeout) + max(1, settings.phrase_time)
        try:
            with self.sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=block,
                device=self._device,
            ) as stream:
                while time.monotonic() < deadline:
                    chunk, overflowed = stream.read(block)
                    if overflowed:
                        logger.debug("sounddevice input overflow")
                    pcm = bytes(chunk)
                    energy = _rms_bytes(pcm)
                    if energy > threshold:
                        speech_started = True
                        silent_ms = 0
                        collected.append(pcm)
                    elif speech_started:
                        collected.append(pcm)
                        silent_ms += self.BLOCK_MS
                        if silent_ms >= 900:
                            break
                    elif time.monotonic() - started > max(1, settings.timeout):
                        return None
        except Exception as exc:
            raise AudioUnavailable(f"sounddevice capture failed: {exc}") from exc
        if not collected:
            return None
        raw = b"".join(collected)
        return self.sr.AudioData(raw, self.SAMPLE_RATE, 2)

    def close(self) -> None:
        return None


class SpeechToText:
    """Recognition with Google primary and Vosk offline fallback."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.sr = _import_sr()
        self._vosk_model = None
        self._vosk_failed = False
        self._local_lock = threading.Lock()

    # ------------------------------------------------------------- availability
    @property
    def vosk_available(self) -> bool:
        model = self.config.vosk_model_path
        return bool(model and Path(model).is_dir() and not self._vosk_failed)

    def _load_vosk(self):
        with self._local_lock:
            if self._vosk_model is not None or self._vosk_failed:
                return self._vosk_model
            path = self.config.vosk_model_path
            if not path or not Path(path).is_dir():
                self._vosk_failed = True
                return None
            try:
                import vosk

                vosk.SetLogLevel(-1)
                self._vosk_model = vosk.Model(str(path))
                logger.info("Loaded offline Vosk model from %s", path)
            except Exception as exc:
                logger.warning("Could not load Vosk model %s: %s", path, exc)
                self._vosk_failed = True
            return self._vosk_model

    # -------------------------------------------------------------- recognition
    def recognize(self, audio: Any) -> str:
        engines = ["vosk", "google"] if self.config.prefer_offline_stt else ["google", "vosk"]
        if self.config.stt_engine in {"google", "vosk"}:
            engines = [self.config.stt_engine]
        for engine in engines:
            if engine == "google":
                text = self._google(audio)
            elif engine == "vosk":
                text = self._vosk(audio)
            else:
                continue
            if text:
                return text
        return ""

    def _google(self, audio: Any) -> str:
        try:
            return self.sr.recognize_google(audio, language=self.config.stt_language).strip()
        except self.sr.UnknownValueError:
            logger.debug("Google STT: speech not understood")
        except self.sr.RequestError as exc:
            logger.warning("Google STT unavailable (offline?): %s", exc)
        except Exception as exc:
            logger.warning("Google STT error: %s", exc)
        return ""

    def _vosk(self, audio: Any) -> str:
        model = self._load_vosk()
        if model is None:
            return ""
        try:
            import json

            import vosk

            rate = int(getattr(audio, "sample_rate", 16_000))
            raw = audio.get_raw_data(convert_rate=rate, convert_width=2)
            recognizer = vosk.KaldiRecognizer(model, rate)
            recognizer.AcceptWaveform(raw)
            result = json.loads(recognizer.FinalResult() or "{}")
            return str(result.get("text", "")).strip()
        except Exception as exc:
            logger.warning("Vosk recognition failed: %s", exc)
            return ""


class SpeechEngine:
    """High-level listen API used by the assistant loop."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.sr = _import_sr()
        self.stt = SpeechToText(config)
        self.backend: CaptureBackend | None = None
        self.backend_name = "none"
        self._failures = 0
        self._degraded = False
        if config.stt_engine == "text":
            self._degraded = True
            return
        self.backend = self._select_backend()

    def _select_backend(self) -> CaptureBackend | None:
        errors: list[str] = []
        for cls in (PyAudioBackend, SoundDeviceBackend):
            try:
                backend = cls(self.config)
                logger.info("Microphone backend: %s", backend.name)
                self.backend_name = backend.name
                return backend
            except Exception as exc:
                errors.append(f"{cls.name}: {exc}")
                logger.warning("Audio backend %s unavailable: %s", cls.name, exc)
        logger.error(
            "No microphone backend available (%s). Falling back to text input.",
            "; ".join(errors),
        )
        self._degraded = True
        return None

    # ---------------------------------------------------------------- properties
    @property
    def microphone_available(self) -> bool:
        return self.backend is not None and not self._degraded

    @property
    def degraded(self) -> bool:
        return self._degraded or self.backend is None

    def calibrate(self, force: bool = False) -> None:
        if self.backend is None:
            return
        try:
            if force:
                self.backend.calibrate(duration=0.8, force=True)
            else:
                self.backend.calibrate()
        except Exception as exc:
            logger.warning("Microphone calibration error: %s", exc)

    # -------------------------------------------------------------------- listen
    def listen(self, timeout: int = 4, phrase_time: int = 8) -> str:
        """Return recognized text, or ``""`` on timeout/failure."""
        if self.backend is None or self._degraded:
            return self.read_text()
        settings = ListenSettings(timeout=timeout, phrase_time=phrase_time)
        try:
            audio = self.backend.listen(settings)
        except Exception as exc:
            self._note_failure(f"capture error: {exc}")
            return ""
        if audio is None:
            return ""
        text = self.stt.recognize(audio)
        if text:
            self._failures = 0
            logger.info("Heard: %s", text)
        return text

    def listen_for_command(self) -> str:
        return self.listen(self.config.command_listen_timeout, self.config.command_phrase_time)

    def listen_for_wake_word(self) -> str:
        return self.listen(self.config.wake_listen_timeout, self.config.wake_phrase_time)

    @staticmethod
    def read_text(prompt: str = "You: ") -> str:
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    # ------------------------------------------------------------------ recovery
    def _note_failure(self, reason: str) -> None:
        self._failures += 1
        logger.warning(
            "Audio failure %s/%s: %s", self._failures, self.config.max_audio_failures, reason
        )
        if self._failures < max(1, self.config.max_audio_failures):
            return
        logger.warning("Too many audio failures; switching to typed commands.")
        self._failures = 0
        self._degraded = True
        if self.backend is not None:
            with contextlib.suppress(Exception):
                self.backend.close()

    def close(self) -> None:
        if self.backend is not None:
            with contextlib.suppress(Exception):
                self.backend.close()
            self.backend = None


class TextOnlySpeech:
    """Keyboard fallback with the same surface as :class:`SpeechEngine`."""

    backend_name = "text"

    def __init__(self, config: Config) -> None:
        self.config = config

    @property
    def microphone_available(self) -> bool:
        return False

    @property
    def degraded(self) -> bool:
        return True

    def calibrate(self, force: bool = False) -> None:
        return None

    def listen(self, timeout: int = 4, phrase_time: int = 8) -> str:
        return self.read_text()

    def listen_for_command(self) -> str:
        return self.read_text()

    def listen_for_wake_word(self) -> str:
        return self.read_text()

    @staticmethod
    def read_text(prompt: str = "You: ") -> str:
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    def close(self) -> None:
        return None


# ================================================================ clap detector
class ClapDetector:
    """Detect two claps in quick succession on the default input device."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def available(self) -> bool:
        try:
            import pyaudio  # noqa: F401

            return True
        except Exception:
            pass
        try:
            import sounddevice as sd

            return any(int(d.get("max_input_channels", 0)) > 0 for d in sd.query_devices())
        except Exception:
            return False

    def _blocks(self) -> Iterable[bytes]:
        """Yield raw little-endian 16-bit mono blocks from either backend."""
        try:
            import pyaudio

            pa = pyaudio.PyAudio()
            try:
                device = next(
                    (
                        index
                        for index in range(pa.get_device_count())
                        if int(pa.get_device_info_by_index(index).get("maxInputChannels", 0)) > 0
                    ),
                    None,
                )
                if device is None:
                    return
                stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=self.config.audio_channels,
                    rate=self.config.audio_rate,
                    input=True,
                    input_device_index=device,
                    frames_per_buffer=self.config.audio_chunk,
                )
                logger.info("Clap detector running (PyAudio, device %s)", device)
                try:
                    while not self._stop.is_set():
                        try:
                            yield stream.read(self.config.audio_chunk, exception_on_overflow=False)
                        except Exception:
                            time.sleep(0.01)
                finally:
                    stream.stop_stream()
                    stream.close()
            finally:
                pa.terminate()
            return
        except Exception as exc:
            logger.info("PyAudio clap detection unavailable (%s); trying sounddevice", exc)

        try:
            import sounddevice as sd

            rate = 16_000
            block = int(rate * self.config.audio_chunk / self.config.audio_rate)
            logger.info("Clap detector running (sounddevice)")
            with sd.InputStream(
                samplerate=rate,
                channels=1,
                dtype="int16",
                blocksize=max(128, block),
                device=self.config.microphone_device,
            ) as stream:
                while not self._stop.is_set():
                    chunk, _overflow = stream.read(max(128, block))
                    yield bytes(chunk)
        except Exception as exc:
            logger.warning("Clap detection unavailable: %s", exc)

    def run(self) -> bool:
        """Block until a double clap is detected or :meth:`stop` is called."""
        clap_count = 0
        first_clap = 0.0
        last_clap = 0.0
        for data in self._blocks():
            if self._stop.is_set():
                return False
            now = time.monotonic()
            if _rms_bytes(data) > self.config.clap_threshold:
                if now - last_clap < self.config.clap_debounce:
                    continue
                last_clap = now
                if clap_count == 0:
                    clap_count, first_clap = 1, now
                else:
                    elapsed = now - first_clap
                    if elapsed < self.config.clap_min_interval:
                        continue
                    if elapsed <= self.config.clap_max_interval:
                        logger.info("Double clap confirmed")
                        return True
                    clap_count, first_clap = 1, now
            elif clap_count == 1 and (now - first_clap) > self.config.clap_max_interval:
                clap_count = 0
        return False


# --------------------------------------------------------------------- helpers
def _rms_bytes(data: bytes) -> float:
    if not data:
        return 0.0
    samples = array.array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _rms_array(data: Any) -> float:
    try:
        flat = data.reshape(-1).astype("float64")
        return float((flat * flat).mean() ** 0.5)
    except Exception:
        return 0.0
