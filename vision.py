"""
Vision - voice assistant with a holographic interface (Windows edition).

Double clap (or say "Hey Vision") to wake it. Talk in English, Hindi or Hinglish.
Run:  python vision.py
"""
import asyncio
import ctypes
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from urllib.parse import quote_plus

import numpy as np
import requests
import speech_recognition as sr

# ------------------------------------------------------------------ CONFIG
CREATOR_NAME = "Your Name"            # who Vision says created it
EDGE_VOICE = "en-IN-NeerjaNeural"     # try en-US-GuyNeural, en-GB-RyanNeural ...
EDGE_RATE = "+0%"
EDGE_PITCH = "+0Hz"
CLAP_THRESHOLD = 8000                 # lower if claps are missed, raise if it self-triggers
LANGUAGE = "en-IN"                    # good for English + Hinglish
OLLAMA_MODEL = "llama3"
OLLAMA_URL = "http://localhost:11434/api/chat"
INTERFACE_ARGS = []                   # e.g. ["--hd"] or ["--hands"] (see README)
# --------------------------------------------------------------------------

BASE = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE, "memory.json")
SHOT_DIR = os.path.join(BASE, "screenshots")
PHOTO_DIR = os.path.join(BASE, "photos")
UDP_ADDR = ("127.0.0.1", 50555)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ------------------------------------------------------------ interface link
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_iface = None


def set_state(state):
    """Tell the hologram window what colour to be: 'idle' (blue) / 'speaking' (red)."""
    try:
        _sock.sendto(state.encode(), UDP_ADDR)
    except OSError:
        pass


def open_interface():
    global _iface
    if _iface is not None and _iface.poll() is None:
        return
    _iface = subprocess.Popen(
        [sys.executable, os.path.join(BASE, "interface.py"), *INTERFACE_ARGS], cwd=BASE
    )


def close_interface():
    global _iface
    if _iface is None or _iface.poll() is not None:
        return
    set_state("quit")
    try:
        _iface.wait(timeout=3)
    except subprocess.TimeoutExpired:
        _iface.kill()
    _iface = None


# ------------------------------------------------------------------- memory
def load_memory():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("name", None)
        data.setdefault("notes", [])
        data.setdefault("history", [])
        return data
    except Exception:
        return {"name": None, "notes": [], "history": []}


memory = load_memory()


def save_memory():
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)


def log_turn(user, bot):
    memory["history"].append(
        {"time": datetime.datetime.now().isoformat(timespec="seconds"), "user": user, "vision": bot}
    )
    memory["history"] = memory["history"][-100:]
    save_memory()


# ------------------------------------------------------------------- speech
_mixer_ready = False


def _speak_edge(text):
    import edge_tts
    import pygame

    global _mixer_ready
    if not _mixer_ready:
        pygame.mixer.init()
        _mixer_ready = True
    path = os.path.join(tempfile.gettempdir(), f"vision_{os.getpid()}.mp3")
    asyncio.run(edge_tts.Communicate(text, EDGE_VOICE, rate=EDGE_RATE, pitch=EDGE_PITCH).save(path))
    pygame.mixer.music.load(path)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.05)
    pygame.mixer.music.unload()
    try:
        os.remove(path)
    except OSError:
        pass


def _speak_sapi(text):
    import pyttsx3

    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()
    engine.stop()


def speak(text):
    text = re.sub(r"[*_`#]", "", text).strip()
    if not text:
        return
    print(f"Vision: {text}")
    set_state("speaking")
    try:
        try:
            _speak_edge(text)  # natural neural voice (needs internet)
        except Exception:
            _speak_sapi(text)  # offline Windows voice
    except Exception as e:
        print(f"[speech error] {e}")
    finally:
        set_state("idle")


# ---------------------------------------------------------------- listening
recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8


def calibrate():
    try:
        with sr.Microphone() as src:
            recognizer.adjust_for_ambient_noise(src, duration=1.0)
    except Exception as e:
        print(f"[mic] calibration skipped: {e}")


def listen(timeout=7, limit=10):
    """Listen once and return lowercase text ('' if nothing understood)."""
    try:
        with sr.Microphone() as src:
            audio = recognizer.listen(src, timeout=timeout, phrase_time_limit=limit)
        return recognizer.recognize_google(audio, language=LANGUAGE).lower().strip()
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""
    except sr.RequestError:
        print("[speech] Google speech service unreachable - check your internet.")
        return ""
    except OSError as e:
        print(f"[mic] {e}")
        time.sleep(1)
        return ""


def wait_for_wake_phrase():
    while True:
        text = listen(timeout=5, limit=4)
        if text and re.search(r"\b(hey|hi|hello|ok|okay)\s+vision\b|^vision$", text):
            return


def wait_for_double_clap():
    """Block until a double clap. Returns False if no microphone can be opened."""
    import pyaudio

    pa = pyaudio.PyAudio()
    try:
        pa.get_default_input_device_info()
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000,
                         input=True, frames_per_buffer=512)
    except Exception:
        pa.terminate()
        return False
    claps, last = [], 0.0
    try:
        while True:
            data = np.frombuffer(stream.read(512, exception_on_overflow=False), dtype=np.int16)
            peak = int(np.abs(data.astype(np.int32)).max())
            now = time.time()
            if peak > CLAP_THRESHOLD and now - last > 0.15:
                last = now
                claps = [t for t in claps if now - t < 0.9] + [now]
                if len(claps) >= 2:
                    return True
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


# -------------------------------------------------------------- system tools
def desktop_path():
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as k:
            value, _ = winreg.QueryValueEx(k, "Desktop")
            return os.path.expandvars(value)  # handles OneDrive-redirected desktops
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Desktop")


def _volume_endpoint():
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):  # newer pycaw
        return dev.EndpointVolume
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def _press_key(vk, times=1):
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def handle_volume(c):
    up = re.search(r"\b(up|increase|raise|louder|badha\w*|zyada|tez)\b", c)
    down = re.search(r"\b(down|decrease|lower|reduce|quieter|kam|dheere|halka)\b", c)
    number = re.search(r"\b(\d{1,3})\b", c)
    try:
        ep = _volume_endpoint()
        cur = round(ep.GetMasterVolumeLevelScalar() * 100)
        if "unmute" in c:
            ep.SetMute(0, None)
            return "Unmuted."
        if "mute" in c:
            ep.SetMute(1, None)
            return "Muted."
        if number:
            level = max(0, min(100, int(number.group(1))))
        elif up:
            level = min(100, cur + 10)
        elif down:
            level = max(0, cur - 10)
        else:
            return f"Volume is at {cur} percent."
        ep.SetMasterVolumeLevelScalar(level / 100, None)
        ep.SetMute(0, None)
        return f"Volume set to {level} percent."
    except Exception:
        # fallback: simulate the keyboard media keys
        if "mute" in c:
            _press_key(0xAD)
            return "Toggled mute."
        if up:
            _press_key(0xAF, 5)
            return "Volume up."
        if down:
            _press_key(0xAE, 5)
            return "Volume down."
        return "I couldn't control the volume. Try: pip install pycaw comtypes"


def battery_status():
    import psutil

    b = psutil.sensors_battery()
    if b is None:
        return "I can't find a battery. This looks like a desktop PC."
    state = "charging" if b.power_plugged else "not charging"
    return f"Battery is at {int(b.percent)} percent and {state}."


def take_screenshot():
    from PIL import ImageGrab

    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f"screenshot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png")
    ImageGrab.grab(all_screens=True).save(path)
    return "Screenshot saved."


def take_photo():
    import cv2

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        return "I couldn't open the camera. Close other apps using it and try again."
    frame = None
    for _ in range(10):  # let auto-exposure settle
        ok, frame = cap.read()
        time.sleep(0.05)
    cap.release()
    if frame is None:
        return "The camera gave me no picture."
    os.makedirs(PHOTO_DIR, exist_ok=True)
    cv2.imwrite(os.path.join(PHOTO_DIR, f"photo_{datetime.datetime.now():%Y%m%d_%H%M%S}.jpg"), frame)
    return "Photo saved."


def folder_name_from(c):
    m = re.search(r"(?:named|called|name|naam)\s+(.+)$", c)
    name = m.group(1) if m else re.sub(
        r"\b(please|create|make|open|new|a|the|folder|banao|kholo|on|desktop|my)\b", " ", c
    )
    name = re.sub(r'[\\/:*?"<>|]', "", name).strip()
    return name


def start_app(target):
    subprocess.Popen(f'start "" {target}', shell=True)


APPS = {
    "chrome": "chrome", "edge": "msedge", "firefox": "firefox", "notepad": "notepad",
    "calculator": "calc", "paint": "mspaint", "file explorer": "explorer",
    "explorer": "explorer", "task manager": "taskmgr", "spotify": "spotify",
    "word": "winword", "excel": "excel",
}
SITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "google": "https://www.google.com",
}


# ---------------------------------------------------------------------- AI
conversation = []


def ask_ai(prompt):
    system = (
        f"You are Vision, a friendly voice assistant created by {CREATOR_NAME}. "
        "Answer in one to three short spoken sentences, plain text only, no lists or markdown. "
        "Reply in the same language the user speaks (English, Hindi or Hinglish)."
    )
    if memory.get("name"):
        system += f" The user's name is {memory['name']}."
    messages = [{"role": "system", "content": system}] + conversation[-6:] + [
        {"role": "user", "content": prompt}
    ]
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
            timeout=120,
        )
        r.raise_for_status()
        answer = r.json()["message"]["content"].strip()
    except Exception:
        return "My AI is not responding. Please make sure Ollama is running."
    conversation.extend([{"role": "user", "content": prompt},
                         {"role": "assistant", "content": answer}])
    return answer


# ---------------------------------------------------------------- commands
def handle(cmd):
    """Return (reply, action). action is None, 'sleep' or 'stop'."""
    c = cmd.lower().strip()

    # --- assistant control
    if re.search(r"\b(stop vision|shut ?down|exit vision|vision band)\b", c):
        return "Shutting down. Goodbye!", "stop"
    if re.search(r"go to sleep|sleep mode|\bso ja(?:o|a)?\b", c):
        return "Going to sleep. Say Hey Vision to wake me.", "sleep"
    if re.search(r"(open|show|start|kholo|khol).*interface|interface (open|kholo|khol)", c):
        open_interface()
        return "Interface online.", None
    if re.search(r"(close|hide|stop|band|off).*interface|interface (close|band)", c):
        close_interface()
        return "Interface closed.", None

    # --- memory
    if re.search(r"what('s| is) my name|mera naam kya|do you know my name", c):
        n = memory.get("name")
        return (f"Your name is {n}." if n else "I don't know your name yet. Tell me: my name is..."), None
    m = (re.search(r"my name is (\w+)", c) or re.search(r"call me (\w+)", c)
         or re.search(r"mera naam (\w+)", c))
    if m:
        memory["name"] = m.group(1).capitalize()
        save_memory()
        return f"Nice to meet you, {memory['name']}!", None
    if re.search(r"recent conversations?|conversation history|show history|pichli baat", c):
        last = memory["history"][-3:]
        if not last:
            return "We haven't talked yet.", None
        return "Recently you said: " + "; ".join(t["user"] for t in last) + ".", None
    if re.search(r"(show|read|list|my|meri|what are my).*notes?\b|notes? (dikhao|sunao|batao)"
                 r"|what (do|did) you remember", c):
        notes = memory["notes"][-5:]
        return ("Your notes: " + "; ".join(notes) + "." if notes else "You have no notes yet."), None
    m = re.search(r"(?:remember that|remember|yaad rakho(?: ki)?|note that)\s+(.+)", c)
    if m:
        memory["notes"].append(m.group(1))
        save_memory()
        return "Okay, I'll remember that.", None

    # --- system actions
    if re.search(r"screenshot|screen shot|screen capture", c):
        return take_screenshot(), None
    if re.search(r"(take|click|capture|kheench|le).*(photo|picture|selfie)"
                 r"|(photo|picture|selfie).*(lo|le|kheench|khench)", c):
        return take_photo(), None
    if re.search(r"volume|awaaz|awaz|\bmute\b|unmute", c):
        return handle_volume(c), None
    if "battery" in c:
        return battery_status(), None
    if re.search(r"\btime\b.*(kya|is it|now)|what('s| is) the time|current time", c):
        return f"It's {datetime.datetime.now():%I:%M %p}.", None
    if re.search(r"what('s| is) (the |today's )?date|aaj ki date|today's date", c):
        return f"Today is {datetime.datetime.now():%A, %d %B %Y}.", None
    if "folder" in c:
        name = folder_name_from(c)
        if not name:
            return "What should the folder be called?", None
        path = os.path.join(desktop_path(), name)
        if re.search(r"\b(open|kholo|khol)\b", c):
            if os.path.isdir(path):
                os.startfile(path)
                return f"Opening {name}.", None
            return f"I couldn't find a folder called {name} on your desktop.", None
        os.makedirs(path, exist_ok=True)
        return f"Folder {name} created on your desktop.", None

    # --- web: play / search
    m = (re.search(r"^(?:please\s+)?(?:play|chalao|chala do|bajao)\s+(.+?)(?:\s+on youtube)?$", c)
         or re.search(r"^(.+?)\s+(?:gana|gaana|song)\s+(?:sunao|chalao|bajao|play(?: karo)?|laga do|lagao)$", c))
    if m:
        webbrowser.open("https://www.youtube.com/results?search_query=" + quote_plus(m.group(1)))
        return f"Playing {m.group(1)} on YouTube.", None
    m = (re.search(r"(?:search|google|find)\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+(google|youtube)$", c)
         or re.search(r"(youtube|google)\s+(?:par|pe|me|mein)\s+(.+?)\s+search", c))
    if m:
        a, b = m.groups()
        site, query = (a, b) if a in ("google", "youtube") else (b, a)
        base = "https://www.youtube.com/results?search_query=" if site == "youtube" \
            else "https://www.google.com/search?q="
        webbrowser.open(base + quote_plus(query))
        return f"Searching {query} on {site}.", None
    m = re.search(r"^(?:search|google)\s+(?:for\s+)?(.+)$", c)
    if m:
        webbrowser.open("https://www.google.com/search?q=" + quote_plus(m.group(1)))
        return f"Searching Google for {m.group(1)}.", None

    # --- open sites / apps
    if re.search(r"\b(open|kholo|khol|start|launch|chalu)\b", c):
        for key, url in SITES.items():
            if key in c:
                webbrowser.open(url)
                return f"Opening {key}.", None
        for key, exe in APPS.items():
            if key in c:
                start_app(exe)
                return f"Opening {key}.", None

    # --- anything else: local AI
    return ask_ai(cmd), None


# -------------------------------------------------------------------- main
def main():
    print("=" * 50)
    print(" VISION (Windows) - double clap or say 'Hey Vision'")
    print(" Ctrl+C to quit")
    print("=" * 50)
    calibrate()
    clap_ok = True
    wake_by_voice = False

    while True:
        if clap_ok and not wake_by_voice:
            print("Waiting for a double clap...")
            if wait_for_double_clap() is False:
                clap_ok = False
                print("No microphone stream for clap detection - say 'Hey Vision' instead.")
                continue
        else:
            print("Say 'Hey Vision'...")
            wait_for_wake_phrase()
        wake_by_voice = False

        open_interface()
        time.sleep(1.5)  # let the window appear so it can show the speaking colour
        name = memory.get("name")
        speak(f"Hello {name}, Vision online. How can I help?" if name else "Vision online. How can I help?")

        misses = 0
        while True:
            print("Listening...")
            cmd = listen()
            if not cmd:
                misses += 1
                if misses >= 4:
                    speak("I'll rest for now. Clap twice when you need me.")
                    break
                continue
            misses = 0
            print(f"You: {cmd}")
            reply, action = handle(cmd)
            speak(reply)
            log_turn(cmd, reply)
            if action == "stop":
                close_interface()
                return
            if action == "sleep":
                wake_by_voice = True
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        close_interface()
