"""
Vision holographic interface (OpenCV window).

Blue while idle, red while Vision is speaking (state arrives from vision.py over UDP).

    python interface.py            # normal 1280x720
    python interface.py --sd       # lighter 854x480
    python interface.py --hd       # Full HD
    python interface.py --hands    # enable webcam hand control (needs mediapipe)

Mouse drag = rotate, scroll or + / - = zoom, [ ] = glow, R = reset, F = fullscreen, Q/Esc = quit.
Hands: one hand rotates, two hands moving apart/together zoom.
"""
import math
import os
import socket
import sys
import threading
import time
import urllib.request

import cv2
import numpy as np

WIN = "VISION"
UDP_PORT = 50555
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "hand_landmarker.task")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")

ARGS = set(sys.argv[1:])
if "--sd" in ARGS:
    W, H = 854, 480
elif "--hd" in ARGS:
    W, H = 1920, 1080
else:
    W, H = 1280, 720
USE_HANDS = "--hands" in ARGS
S = H / 720.0  # UI scale

IDLE = np.array([255, 150, 30], float)   # BGR -> blue
SPEAK = np.array([50, 50, 255], float)   # BGR -> red


# ------------------------------------------------------------------ geometry
def _pairs(pts):
    return np.stack([pts[:-1], pts[1:]], axis=1)


def sphere_segments(r, lat_step, lon_step, n):
    t = np.linspace(0, 2 * np.pi, n + 1)
    out = []
    for lat in range(-90 + lat_step, 90, lat_step):
        phi = math.radians(lat)
        pts = np.stack([r * math.cos(phi) * np.cos(t),
                        np.full_like(t, r * math.sin(phi)),
                        r * math.cos(phi) * np.sin(t)], 1)
        out.append(_pairs(pts))
    for lon in range(0, 180, lon_step):
        th = math.radians(lon)
        pts = np.stack([r * np.cos(t) * math.cos(th), r * np.sin(t),
                        r * np.cos(t) * math.sin(th)], 1)
        out.append(_pairs(pts))
    return np.concatenate(out)


def ring_segments(r, n=120):
    t = np.linspace(0, 2 * np.pi, n + 1)
    return _pairs(np.stack([r * np.cos(t), np.zeros_like(t), r * np.sin(t)], 1))


def rot(ax, ay, az=0.0):
    ca, sa = math.cos(ax), math.sin(ax)
    cb, sb = math.cos(ay), math.sin(ay)
    cc, sc = math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]])
    ry = np.array([[cb, 0, sb], [0, 1, 0], [-sb, 0, cb]])
    rz = np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]])
    return rz @ rx @ ry


OUTER = sphere_segments(1.0, 15, 15, 48)
CORE = sphere_segments(0.5, 30, 30, 32)
RINGS = [(ring_segments(1.3), 0.0, 0.0), (ring_segments(1.45), 1.1, 0.4),
         (ring_segments(1.6), -0.8, -0.6)]

_rng = np.random.default_rng(7)
_dirs = _rng.normal(size=(260, 3))
_dirs /= np.linalg.norm(_dirs, axis=1, keepdims=True)
PARTICLES = _dirs * _rng.uniform(1.05, 1.75, size=(260, 1))


def project(p, scale, cx, cy):
    z = p[..., 2]
    persp = 3.5 / (3.5 - z)
    xy = np.stack([cx + p[..., 0] * scale * persp, cy - p[..., 1] * scale * persp], -1)
    return xy, z


def draw_segments(layer, segs, R, color, scale, cx, cy, boost=1.0):
    p = segs @ R.T
    xy, z = project(p, scale, cx, cy)
    bright = np.clip(0.30 + 0.70 * (z.mean(axis=1) + 1.6) / 3.2, 0.1, 1.0) * boost
    pts = xy.astype(np.int32).tolist()
    cols = np.clip(color[None, :] * bright[:, None], 0, 255).astype(int).tolist()
    for (a, b), c in zip(pts, cols):
        cv2.line(layer, tuple(a), tuple(b), tuple(c), 1, cv2.LINE_AA)


def draw_particles(layer, R, color, scale, cx, cy):
    xy, z = project(PARTICLES @ R.T, scale, cx, cy)
    bright = np.clip(0.25 + 0.75 * (z + 1.8) / 3.6, 0.1, 1.0)
    pts = xy.astype(np.int32).tolist()
    cols = np.clip(color[None, :] * bright[:, None], 0, 255).astype(int).tolist()
    rad = max(1, int(round(1.5 * S)))
    for pt, c in zip(pts, cols):
        cv2.circle(layer, tuple(pt), rad, tuple(c), -1, cv2.LINE_AA)


def draw_brackets(layer, color):
    c = tuple(int(v) for v in color)
    m, l = int(30 * S), int(60 * S)
    for x, y, dx, dy in [(m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)]:
        cv2.line(layer, (x, y), (x + dx * l, y), c, 2, cv2.LINE_AA)
        cv2.line(layer, (x, y), (x, y + dy * l), c, 2, cv2.LINE_AA)


def make_background():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    k = np.clip(1.0 - r / 1.4, 0, 1) ** 2
    return np.dstack([34 * k + 4, 18 * k + 2, 6 * k + 1]).astype(np.uint8)


# ----------------------------------------------------------------- UDP link
def make_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", UDP_PORT))
    except OSError:
        return None
    s.setblocking(False)
    try:
        s.ioctl(socket.SIO_UDP_CONNRESET, False)  # Windows only
    except Exception:
        pass
    return s


def poll(sock):
    msgs = []
    if sock is None:
        return msgs
    while True:
        try:
            data, _ = sock.recvfrom(64)
        except OSError:
            break
        msgs.append(data.decode(errors="ignore").strip())
    return msgs


# ------------------------------------------------------------ hand tracking
class HandTracker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.hands = []  # normalised palm centres [(x, y), ...]
        self._halt = False

    def run(self):
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision

            if not os.path.exists(MODEL_PATH):
                print("[interface] downloading hand model...")
                urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
            options = mp_vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
                running_mode=mp_vision.RunningMode.VIDEO, num_hands=2)
            detector = mp_vision.HandLandmarker.create_from_options(options)
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not cap.isOpened():
                raise RuntimeError("camera not available")
        except Exception as e:
            print(f"[interface] hand tracking disabled: {e}")
            return
        last_ts = 0
        while not self._halt:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue
            frame = cv2.flip(frame, 1)
            img = mp.Image(image_format=mp.ImageFormat.SRGB,
                           data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            ts = max(int(time.time() * 1000), last_ts + 1)
            last_ts = ts
            result = detector.detect_for_video(img, ts)
            self.hands = [(lm[9].x, lm[9].y) for lm in result.hand_landmarks]
        cap.release()

    def stop(self):
        self._halt = True


# --------------------------------------------------------------------- main
def main():
    ui = {"drag": False, "last": (0, 0), "dx": 0.0, "dy": 0.0, "zoom_mul": 1.0}

    def on_mouse(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN:
            ui["drag"], ui["last"] = True, (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            ui["drag"] = False
        elif event == cv2.EVENT_MOUSEMOVE and ui["drag"]:
            ui["dx"] += x - ui["last"][0]
            ui["dy"] += y - ui["last"][1]
            ui["last"] = (x, y)
        elif event == cv2.EVENT_MOUSEWHEEL:
            delta = cv2.getMouseWheelDelta(flags) if hasattr(cv2, "getMouseWheelDelta") else flags
            ui["zoom_mul"] *= 1.08 if delta > 0 else 1 / 1.08

    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, W, H)
    cv2.setMouseCallback(WIN, on_mouse)

    sock = make_socket()
    tracker = None
    if USE_HANDS:
        tracker = HandTracker()
        tracker.start()
    bg = make_background()

    yaw, pitch, zoom, glow = 0.4, 0.25, 1.0, 1.0
    speak_amt, target_speak = 0.0, 0.0
    prev_hand, prev_dist = None, None
    fullscreen = False
    t0 = last = time.time()

    while True:
        now = time.time()
        dt = max(1e-3, now - last)
        last = now
        t = now - t0

        for msg in poll(sock):
            if msg == "speaking":
                target_speak = 1.0
            elif msg == "idle":
                target_speak = 0.0
            elif msg == "quit":
                if tracker:
                    tracker.stop()
                cv2.destroyAllWindows()
                return

        # --- input -> camera
        yaw += ui["dx"] * 0.008
        pitch = float(np.clip(pitch + ui["dy"] * 0.008, -1.4, 1.4))
        ui["dx"] = ui["dy"] = 0.0
        if not ui["drag"]:
            yaw += 0.25 * dt  # slow auto-rotation
        zoom = float(np.clip(zoom * ui["zoom_mul"], 0.4, 2.5))
        ui["zoom_mul"] = 1.0

        hands = tracker.hands if tracker else []
        if len(hands) == 2:
            d = math.dist(hands[0], hands[1])
            if prev_dist:
                zoom = float(np.clip(zoom * np.clip(d / prev_dist, 0.92, 1.08), 0.4, 2.5))
            prev_dist, prev_hand = d, None
        elif len(hands) == 1:
            if prev_hand:
                yaw += (hands[0][0] - prev_hand[0]) * 7
                pitch = float(np.clip(pitch + (hands[0][1] - prev_hand[1]) * 5, -1.4, 1.4))
            prev_hand, prev_dist = hands[0], None
        else:
            prev_hand = prev_dist = None

        # --- animation state
        speak_amt += (target_speak - speak_amt) * min(1.0, 8 * dt)
        color = IDLE + (SPEAK - IDLE) * speak_amt
        pulse = 1 + 0.012 * math.sin(t * 1.5) + speak_amt * (0.04 * math.sin(t * 11) + 0.02 * math.sin(t * 23))
        scale = min(W, H) * 0.30 * zoom * pulse
        cx, cy = W // 2, H // 2

        # --- draw
        layer = np.zeros((H, W, 3), np.uint8)
        view = rot(pitch, yaw)
        draw_segments(layer, OUTER, view, color, scale, cx, cy)
        draw_segments(layer, CORE, view @ rot(0.3, -t * 0.9), color, scale, cx, cy, boost=1.2)
        for segs, tilt_x, tilt_z in RINGS:
            draw_segments(layer, segs, view @ rot(tilt_x, t * (0.5 + tilt_x * 0.3), tilt_z),
                          color, scale, cx, cy, boost=0.9)
        draw_particles(layer, view @ rot(0, t * 0.15), color, scale, cx, cy)
        draw_brackets(layer, color * 0.8)

        small = cv2.resize(layer, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
        halo = cv2.resize(cv2.GaussianBlur(small, (0, 0), 4), (W, H))
        frame = cv2.add(bg, cv2.addWeighted(layer, 1.0, halo, 1.4 * glow * (1 + 0.5 * speak_amt), 0))
        frame[::3] = frame[::3] * 0.85  # scanlines

        # --- HUD text
        c = tuple(int(v) for v in color)
        cv2.putText(frame, "V I S I O N", (int(50 * S), int(70 * S)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9 * S, c, max(1, int(2 * S)), cv2.LINE_AA)
        status = "SPEAKING" if target_speak > 0.5 else "ONLINE"
        cv2.putText(frame, status, (int(50 * S), H - int(50 * S)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6 * S, c, max(1, int(1 * S)), cv2.LINE_AA)
        for hx, hy in hands:
            cv2.circle(frame, (int(hx * W), int(hy * H)), int(10 * S), c, 2, cv2.LINE_AA)

        cv2.imshow(WIN, frame)
        wait = max(1, int((1 / 30 - (time.time() - now)) * 1000))
        key = cv2.waitKey(wait) & 0xFF
        if key in (ord("q"), 27) or cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
            break
        if key in (ord("+"), ord("=")):
            zoom = min(2.5, zoom * 1.1)
        elif key == ord("-"):
            zoom = max(0.4, zoom / 1.1)
        elif key == ord("["):
            glow = max(0.1, glow - 0.1)
        elif key == ord("]"):
            glow = min(2.0, glow + 0.1)
        elif key == ord("r"):
            yaw, pitch, zoom, glow = 0.4, 0.25, 1.0, 1.0
        elif key == ord("f"):
            fullscreen = not fullscreen
            cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN,
                                  cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)

    if tracker:
        tracker.stop()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
