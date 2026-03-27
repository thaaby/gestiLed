#!/usr/bin/env python3
"""
minimalv2.py — Lavagna LED Interattiva (Raspberry Pi 5 / Linux Edition)
=======================================================================
Porta fedele di minimalv2.py ottimizzata per RPi5:
  - Thread dedicato alla cattura webcam (producer/consumer, latenza minima)
  - Risoluzione webcam 320×240 (alleggerisce MediaPipe su ARM)
  - Frame skip: MediaPipe processa 1 frame su 2
  - Porta seriale: solo pattern Linux (/dev/ttyUSB*, /dev/ttyACM*)
  - cv2.CAP_V4L2 per accesso diretto V4L2 su Linux

REQUISITI:
  pip install mediapipe opencv-python pyserial pygame numpy

USO:
  python3 minimalv2.py
"""

import cv2
import numpy as np
from collections import namedtuple, deque
import math
import json
import time
import sys
import os
import threading
import queue
from datetime import datetime
import socket
import glob
import subprocess

# --- Aggiunge la cartella padre al path per importare i moduli condivisi ---
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT_DIR)

from hand_tracker import HandTracker, HandState
from led_canvas import LEDCanvas, COLOR_PALETTE, COLOR_NAMES_IT
from audio_synth import AudioSynth

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False
    print("[!] pyserial non installato — Arduino video disabilitato (pip install pyserial)")


# ============================================================
# DATABASE COLORI
# ============================================================
ColorDef = namedtuple('ColorDef', ['name', 'name_it', 'rgb', 'hex_code'])

COLOR_DATABASE = [
    # Rossi
    ColorDef('Red', 'Rosso', (255, 0, 0), '#FF0000'),
    ColorDef('Dark Red', 'Rosso Scuro', (139, 0, 0), '#8B0000'),
    ColorDef('Crimson', 'Cremisi', (220, 20, 60), '#DC143C'),
    ColorDef('Indian Red', 'Rosso Indiano', (205, 92, 92), '#CD5C5C'),
    ColorDef('Light Coral', 'Corallo Chiaro', (240, 128, 128), '#F08080'),
    ColorDef('Salmon', 'Salmone', (250, 128, 114), '#FA8072'),
    ColorDef('Dark Salmon', 'Salmone Scuro', (233, 150, 122), '#E9967A'),
    ColorDef('Light Salmon', 'Salmone Chiaro', (255, 160, 122), '#FFA07A'),
    ColorDef('Fire Brick', 'Mattone', (178, 34, 34), '#B22222'),
    ColorDef('Maroon', 'Marrone Rosso', (128, 0, 0), '#800000'),
    # Arancioni
    ColorDef('Orange', 'Arancione', (255, 165, 0), '#FFA500'),
    ColorDef('Dark Orange', 'Arancione Scuro', (255, 140, 0), '#FF8C00'),
    ColorDef('Orange Red', 'Rosso Arancio', (255, 69, 0), '#FF4500'),
    ColorDef('Tomato', 'Pomodoro', (255, 99, 71), '#FF6347'),
    ColorDef('Coral', 'Corallo', (255, 127, 80), '#FF7F50'),
    ColorDef('Peach', 'Pesca', (255, 218, 185), '#FFDAB9'),
    ColorDef('Apricot', 'Albicocca', (251, 206, 177), '#FBCEB1'),
    ColorDef('Tangerine', 'Mandarino', (255, 159, 0), '#FF9F00'),
    ColorDef('Burnt Orange', 'Arancione Bruciato', (204, 85, 0), '#CC5500'),
    ColorDef('Pumpkin', 'Zucca', (255, 117, 24), '#FF7518'),
    # Gialli
    ColorDef('Yellow', 'Giallo', (255, 255, 0), '#FFFF00'),
    ColorDef('Light Yellow', 'Giallo Chiaro', (255, 255, 224), '#FFFFE0'),
    ColorDef('Lemon', 'Limone', (255, 247, 0), '#FFF700'),
    ColorDef('Gold', 'Oro', (255, 215, 0), '#FFD700'),
    ColorDef('Golden Yellow', 'Giallo Dorato', (255, 223, 0), '#FFDF00'),
    ColorDef('Mustard', 'Senape', (255, 219, 88), '#FFDB58'),
    ColorDef('Canary Yellow', 'Giallo Canarino', (255, 239, 0), '#FFEF00'),
    ColorDef('Banana Yellow', 'Giallo Banana', (255, 225, 53), '#FFE135'),
    ColorDef('Amber', 'Ambra', (255, 191, 0), '#FFBF00'),
    ColorDef('Champagne', 'Champagne', (247, 231, 206), '#F7E7CE'),
    ColorDef('Cream', 'Crema', (255, 253, 208), '#FFFDD0'),
    ColorDef('Khaki', 'Cachi', (240, 230, 140), '#F0E68C'),
    ColorDef('Dark Khaki', 'Cachi Scuro', (189, 183, 107), '#BDB76B'),
    # Verdi
    ColorDef('Green', 'Verde', (0, 128, 0), '#008000'),
    ColorDef('Lime', 'Lime', (0, 255, 0), '#00FF00'),
    ColorDef('Bright Green', 'Verde Brillante', (102, 255, 0), '#66FF00'),
    ColorDef('Dark Green', 'Verde Scuro', (0, 100, 0), '#006400'),
    ColorDef('Forest Green', 'Verde Foresta', (34, 139, 34), '#228B22'),
    ColorDef('Sea Green', 'Verde Mare', (46, 139, 87), '#2E8B57'),
    ColorDef('Medium Sea Green', 'Verde Mare Medio', (60, 179, 113), '#3CB371'),
    ColorDef('Light Green', 'Verde Chiaro', (144, 238, 144), '#90EE90'),
    ColorDef('Pale Green', 'Verde Pallido', (152, 251, 152), '#98FB98'),
    ColorDef('Spring Green', 'Verde Primavera', (0, 255, 127), '#00FF7F'),
    ColorDef('Lawn Green', 'Verde Prato', (124, 252, 0), '#7CFC00'),
    ColorDef('Chartreuse', 'Chartreuse', (127, 255, 0), '#7FFF00'),
    ColorDef('Yellow Green', 'Giallo Verde', (154, 205, 50), '#9ACD32'),
    ColorDef('Olive', 'Oliva', (128, 128, 0), '#808000'),
    ColorDef('Olive Drab', 'Oliva Opaco', (107, 142, 35), '#6B8E23'),
    ColorDef('Dark Olive', 'Oliva Scuro', (85, 107, 47), '#556B2F'),
    ColorDef('Mint', 'Menta', (189, 252, 201), '#BDFCC9'),
    ColorDef('Emerald', 'Smeraldo', (80, 200, 120), '#50C878'),
    ColorDef('Jade', 'Giada', (0, 168, 107), '#00A86B'),
    ColorDef('Teal Green', 'Verde Petrolio', (0, 128, 128), '#008080'),
    # Ciano/Acqua
    ColorDef('Cyan', 'Ciano', (0, 255, 255), '#00FFFF'),
    ColorDef('Aqua', 'Acqua', (0, 200, 200), '#00C8C8'),
    ColorDef('Light Cyan', 'Ciano Chiaro', (224, 255, 255), '#E0FFFF'),
    ColorDef('Dark Cyan', 'Ciano Scuro', (0, 139, 139), '#008B8B'),
    ColorDef('Turquoise', 'Turchese', (64, 224, 208), '#40E0D0'),
    ColorDef('Dark Turquoise', 'Turchese Scuro', (0, 206, 209), '#00CED1'),
    ColorDef('Medium Turquoise', 'Turchese Medio', (72, 209, 204), '#48D1CC'),
    ColorDef('Pale Turquoise', 'Turchese Pallido', (175, 238, 238), '#AFEEEE'),
    ColorDef('Aquamarine', 'Acquamarina', (127, 255, 212), '#7FFFD4'),
    ColorDef('Teal', 'Petrolio', (0, 128, 128), '#008080'),
    ColorDef('Cadet Blue', 'Blu Cadetto', (95, 158, 160), '#5F9EA0'),
    # Blu
    ColorDef('Blue', 'Blu', (0, 0, 255), '#0000FF'),
    ColorDef('Light Blue', 'Blu Chiaro', (173, 216, 230), '#ADD8E6'),
    ColorDef('Sky Blue', 'Azzurro Cielo', (135, 206, 235), '#87CEEB'),
    ColorDef('Light Sky Blue', 'Azzurro Cielo Chiaro', (135, 206, 250), '#87CEFA'),
    ColorDef('Deep Sky Blue', 'Azzurro Intenso', (0, 191, 255), '#00BFFF'),
    ColorDef('Dodger Blue', 'Blu Dodger', (30, 144, 255), '#1E90FF'),
    ColorDef('Cornflower Blue', 'Blu Fiordaliso', (100, 149, 237), '#6495ED'),
    ColorDef('Steel Blue', 'Blu Acciaio', (70, 130, 180), '#4682B4'),
    ColorDef('Royal Blue', 'Blu Reale', (65, 105, 225), '#4169E1'),
    ColorDef('Medium Blue', 'Blu Medio', (0, 0, 205), '#0000CD'),
    ColorDef('Dark Blue', 'Blu Scuro', (0, 0, 139), '#00008B'),
    ColorDef('Navy', 'Blu Navy', (0, 0, 128), '#000080'),
    ColorDef('Midnight Blue', 'Blu Mezzanotte', (25, 25, 112), '#191970'),
    ColorDef('Cobalt Blue', 'Blu Cobalto', (0, 71, 171), '#0047AB'),
    ColorDef('Electric Blue', 'Blu Elettrico', (125, 249, 255), '#7DF9FF'),
    ColorDef('Azure', 'Azzurro', (0, 127, 255), '#007FFF'),
    ColorDef('Powder Blue', 'Blu Polvere', (176, 224, 230), '#B0E0E6'),
    ColorDef('Alice Blue', 'Blu Alice', (240, 248, 255), '#F0F8FF'),
    # Viola/Porpora
    ColorDef('Purple', 'Viola', (128, 0, 128), '#800080'),
    ColorDef('Violet', 'Violetto', (238, 130, 238), '#EE82EE'),
    ColorDef('Dark Violet', 'Violetto Scuro', (148, 0, 211), '#9400D3'),
    ColorDef('Blue Violet', 'Blu Violetto', (138, 43, 226), '#8A2BE2'),
    ColorDef('Dark Orchid', 'Orchidea Scura', (153, 50, 204), '#9932CC'),
    ColorDef('Medium Orchid', 'Orchidea Media', (186, 85, 211), '#BA55D3'),
    ColorDef('Orchid', 'Orchidea', (218, 112, 214), '#DA70D6'),
    ColorDef('Plum', 'Prugna', (221, 160, 221), '#DDA0DD'),
    ColorDef('Medium Purple', 'Porpora Medio', (147, 112, 219), '#9370DB'),
    ColorDef('Indigo', 'Indaco', (75, 0, 130), '#4B0082'),
    ColorDef('Slate Blue', 'Blu Ardesia', (106, 90, 205), '#6A5ACD'),
    ColorDef('Dark Slate Blue', 'Blu Ardesia Scuro', (72, 61, 139), '#483D8B'),
    ColorDef('Lavender', 'Lavanda', (230, 230, 250), '#E6E6FA'),
    ColorDef('Thistle', 'Cardo', (216, 191, 216), '#D8BFD8'),
    ColorDef('Mauve', 'Malva', (224, 176, 255), '#E0B0FF'),
    ColorDef('Amethyst', 'Ametista', (153, 102, 204), '#9966CC'),
    ColorDef('Grape', 'Uva', (111, 45, 168), '#6F2DA8'),
    ColorDef('Eggplant', 'Melanzana', (97, 64, 81), '#614051'),
    # Rosa/Magenta
    ColorDef('Pink', 'Rosa', (255, 192, 203), '#FFC0CB'),
    ColorDef('Light Pink', 'Rosa Chiaro', (255, 182, 193), '#FFB6C1'),
    ColorDef('Hot Pink', 'Rosa Acceso', (255, 105, 180), '#FF69B4'),
    ColorDef('Deep Pink', 'Rosa Intenso', (255, 20, 147), '#FF1493'),
    ColorDef('Medium Violet Red', 'Rosso Violetto Medio', (199, 21, 133), '#C71585'),
    ColorDef('Pale Violet Red', 'Rosso Violetto Pallido', (219, 112, 147), '#DB7093'),
    ColorDef('Magenta', 'Magenta', (255, 0, 255), '#FF00FF'),
    ColorDef('Fuchsia', 'Fucsia', (255, 0, 200), '#FF00C8'),
    ColorDef('Rose', 'Rosa', (255, 0, 127), '#FF007F'),
    ColorDef('Blush', 'Rosa Cipria', (222, 93, 131), '#DE5D83'),
    ColorDef('Carnation Pink', 'Rosa Garofano', (255, 166, 201), '#FFA6C9'),
    ColorDef('Flamingo', 'Fenicottero', (252, 142, 172), '#FC8EAC'),
    ColorDef('Raspberry', 'Lampone', (227, 11, 92), '#E30B5C'),
    ColorDef('Cerise', 'Ciliegia', (222, 49, 99), '#DE3163'),
    # Marroni
    ColorDef('Brown', 'Marrone', (165, 42, 42), '#A52A2A'),
    ColorDef('Dark Brown', 'Marrone Scuro', (101, 67, 33), '#654321'),
    ColorDef('Saddle Brown', 'Marrone Sella', (139, 69, 19), '#8B4513'),
    ColorDef('Sienna', 'Terra di Siena', (160, 82, 45), '#A0522D'),
    ColorDef('Chocolate', 'Cioccolato', (210, 105, 30), '#D2691E'),
    ColorDef('Peru', 'Peru', (205, 133, 63), '#CD853F'),
    ColorDef('Sandy Brown', 'Marrone Sabbia', (244, 164, 96), '#F4A460'),
    ColorDef('Burly Wood', 'Legno', (222, 184, 135), '#DEB887'),
    ColorDef('Tan', 'Cuoio', (210, 180, 140), '#D2B48C'),
    ColorDef('Rosy Brown', 'Marrone Rosato', (188, 143, 143), '#BC8F8F'),
    ColorDef('Moccasin', 'Mocassino', (255, 228, 181), '#FFE4B5'),
    ColorDef('Navajo White', 'Bianco Navajo', (255, 222, 173), '#FFDEAD'),
    ColorDef('Wheat', 'Grano', (245, 222, 179), '#F5DEB3'),
    ColorDef('Bisque', 'Biscotto', (255, 228, 196), '#FFE4C4'),
    ColorDef('Blanched Almond', 'Mandorla', (255, 235, 205), '#FFEBCD'),
    ColorDef('Cornsilk', 'Seta di Mais', (255, 248, 220), '#FFF8DC'),
    ColorDef('Beige', 'Beige', (245, 245, 220), '#F5F5DC'),
    ColorDef('Antique White', 'Bianco Antico', (250, 235, 215), '#FAEBD7'),
    ColorDef('Papaya Whip', 'Papaya', (255, 239, 213), '#FFEFD5'),
    ColorDef('Linen', 'Lino', (250, 240, 230), '#FAF0E6'),
    ColorDef('Old Lace', 'Pizzo Antico', (253, 245, 230), '#FDF5E6'),
    ColorDef('Coffee', 'Caffe', (111, 78, 55), '#6F4E37'),
    ColorDef('Caramel', 'Caramello', (255, 213, 154), '#FFD59A'),
    ColorDef('Rust', 'Ruggine', (183, 65, 14), '#B7410E'),
    ColorDef('Copper', 'Rame', (184, 115, 51), '#B87333'),
    ColorDef('Bronze', 'Bronzo', (205, 127, 50), '#CD7F32'),
    ColorDef('Terracotta', 'Terracotta', (226, 114, 91), '#E2725B'),
    ColorDef('Burgundy', 'Borgogna', (128, 0, 32), '#800020'),
    ColorDef('Wine', 'Vino', (114, 47, 55), '#722F37'),
    ColorDef('Vermillion', 'Vermiglio', (227, 66, 52), '#E34234'),
    ColorDef('Ochre', 'Ocra', (204, 119, 34), '#CC7722'),
    ColorDef('Marigold', 'Calendula', (234, 162, 33), '#EAA221'),
    ColorDef('Dark Teal', 'Petrolio Scuro', (0, 109, 111), '#006D6F'),
    ColorDef('Persian Red', 'Rosso Persiano', (204, 51, 51), '#CC3333'),
    ColorDef('Sapphire', 'Zaffiro', (15, 82, 186), '#0F52BA'),
    # Grigi
    ColorDef('Gray', 'Grigio', (128, 128, 128), '#808080'),
    ColorDef('Dark Gray', 'Grigio Scuro', (169, 169, 169), '#A9A9A9'),
    ColorDef('Dim Gray', 'Grigio Tenue', (105, 105, 105), '#696969'),
    ColorDef('Light Gray', 'Grigio Chiaro', (211, 211, 211), '#D3D3D3'),
    ColorDef('Silver', 'Argento', (192, 192, 192), '#C0C0C0'),
    ColorDef('Light Slate Gray', 'Grigio Ardesia Chiaro', (119, 136, 153), '#778899'),
    ColorDef('Slate Gray', 'Grigio Ardesia', (112, 128, 144), '#708090'),
    ColorDef('Dark Slate Gray', 'Grigio Ardesia Scuro', (47, 79, 79), '#2F4F4F'),
    ColorDef('Charcoal', 'Carbone', (54, 69, 79), '#36454F'),
    ColorDef('Ash Gray', 'Grigio Cenere', (178, 190, 181), '#B2BEB5'),
    ColorDef('Gainsboro', 'Gainsboro', (220, 220, 220), '#DCDCDC'),
    ColorDef('White Smoke', 'Fumo Bianco', (245, 245, 245), '#F5F5F5'),
    # Bianco e Nero
    ColorDef('White', 'Bianco', (255, 255, 255), '#FFFFFF'),
    ColorDef('Snow', 'Neve', (255, 250, 250), '#FFFAFA'),
    ColorDef('Honeydew', 'Melata', (240, 255, 240), '#F0FFF0'),
    ColorDef('Mint Cream', 'Crema Menta', (245, 255, 250), '#F5FFFA'),
    ColorDef('Ghost White', 'Bianco Fantasma', (248, 248, 255), '#F8F8FF'),
    ColorDef('Floral White', 'Bianco Floreale', (255, 250, 240), '#FFFAF0'),
    ColorDef('Seashell', 'Conchiglia', (255, 245, 238), '#FFF5EE'),
    ColorDef('Ivory', 'Avorio', (255, 255, 240), '#FFFFF0'),
    ColorDef('Black', 'Nero', (0, 0, 0), '#000000'),
    ColorDef('Jet Black', 'Nero Corvino', (52, 52, 52), '#343434'),
    ColorDef('Onyx', 'Onice', (53, 56, 57), '#353839'),
    ColorDef('Ebony', 'Ebano', (85, 93, 80), '#555D50'),
]


# ============================================================
# CONFIGURAZIONE MAXISCHERMO ESP (MULTI-PANNELLO UDP)
# ============================================================
ESP_ENABLED = "auto"
ESP_IPS = ["192.168.1.61", "192.168.1.62", "192.168.1.63", "192.168.1.64", "192.168.1.65", "192.168.1.68"]
ESP_PORT = 4210

PANEL_WIDTH = 15
PANEL_HEIGHT = 44
TOTAL_WIDTH = PANEL_WIDTH * len(ESP_IPS)

ESP_SERPENTINE_HORIZONTAL = True
ESP_START_BOTTOM = False


# ============================================================
# CONFIGURAZIONE ARDUINO VIDEO (SERIALE)
# ============================================================
ARDUINO_ENABLED = "auto"
ARDUINO_PORT = "auto"
ARDUINO_BAUD = 500000
ARDUINO_ROWS = 32
ARDUINO_COLS = 32
ARDUINO_PANEL_W = 8
ARDUINO_PANEL_H = 32
ARDUINO_PANELS_COUNT = 4
ARDUINO_MIRROR_HORIZONTAL = True

LOGICAL_WIDTH = ARDUINO_COLS
LOGICAL_HEIGHT = ARDUINO_ROWS

ARDUINO_PANEL_ORDER = [3, 2, 1, 0]
ARDUINO_PANEL_START_BOTTOM = [False, False, False, False]
ARDUINO_SERPENTINE_X = True

GAMMA = 2.5
COMMON_ANODE = False

gamma_table = np.array([((i / 255.0) ** GAMMA) * 255
                         for i in np.arange(0, 256)]).astype("uint8")

MAGIC_HEADER = b'\xFFLE'


# ============================================================
# OTTIMIZZAZIONE RPi5: THREAD WEBCAM
# ============================================================
# Risoluzione ridotta: alleggerisce MediaPipe su ARM senza perdere qualità utile
CAM_WIDTH  = 320
CAM_HEIGHT = 240
# Processa MediaPipe ogni N frame (1 = sempre, 2 = un frame su due)
MEDIAPIPE_SKIP = 2


class CameraThread(threading.Thread):
    """Thread dedicato alla cattura webcam.
    Usa cv2.CAP_V4L2 (Linux) e buffer minimo per latenza minima.
    Mantiene sempre l'ultimo frame disponibile in una queue maxsize=2.
    """

    def __init__(self, cam_index=0, width=320, height=240):
        super().__init__(daemon=True)
        self.cap = cv2.VideoCapture(cam_index, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._queue = queue.Queue(maxsize=2)
        self._stop_event = threading.Event()

        if not self.cap.isOpened():
            raise RuntimeError(f"[X] Impossibile aprire webcam (indice {cam_index})")

        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[CAM] Risoluzione effettiva: {actual_w}x{actual_h}")

    def run(self):
        while not self._stop_event.is_set():
            ret, frame = self.cap.read()
            if not ret:
                continue
            # Scarta il vecchio frame se la queue è piena (teniamo sempre il più recente)
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put(frame)

    def read(self):
        """Restituisce l'ultimo frame (blocca max 0.1s)."""
        try:
            return self._queue.get(timeout=0.1)
        except queue.Empty:
            return None

    def stop(self):
        self._stop_event.set()
        self.cap.release()


# ============================================================
# AUTO-RILEVAMENTO HARDWARE (Linux only)
# ============================================================

def _ping_host(ip, timeout_ms=500):
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-W', str(timeout_ms), ip],
            capture_output=True, timeout=2
        )
        return result.returncode == 0
    except Exception:
        return False


def detect_hardware():
    global ESP_ENABLED, ARDUINO_ENABLED, LOGICAL_WIDTH, LOGICAL_HEIGHT

    print("\n[SCAN] Rilevamento hardware automatico...")

    # --- Arduino: cerca porte seriali USB (Linux) ---
    if ARDUINO_ENABLED == "auto":
        porte = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')
        ARDUINO_ENABLED = len(porte) > 0
        if ARDUINO_ENABLED:
            print(f"  [v] Arduino: porta trovata ({porte[0]})")
        else:
            print("  [x] Arduino: nessuna porta seriale USB")

    # --- ESP: ping del primo pannello ---
    if ESP_ENABLED == "auto":
        print(f"  [?] ESP LED Wall: ping {ESP_IPS[0]}...", end=" ", flush=True)
        ESP_ENABLED = _ping_host(ESP_IPS[0])
        if ESP_ENABLED:
            print(f"raggiungibile! ({len(ESP_IPS)} pannelli)")
        else:
            print("non raggiungibile")

    # --- Calcola dimensioni logiche ---
    if ESP_ENABLED:
        LOGICAL_WIDTH = TOTAL_WIDTH
        LOGICAL_HEIGHT = PANEL_HEIGHT
    else:
        LOGICAL_WIDTH = ARDUINO_COLS
        LOGICAL_HEIGHT = ARDUINO_ROWS

    if ESP_ENABLED and ARDUINO_ENABLED:
        mode = f"DUAL — ESP ({TOTAL_WIDTH}x{PANEL_HEIGHT}) + Arduino ({ARDUINO_COLS}x{ARDUINO_ROWS})"
    elif ESP_ENABLED:
        mode = f"SOLO ESP — {TOTAL_WIDTH}x{PANEL_HEIGHT}"
    elif ARDUINO_ENABLED:
        mode = f"SOLO ARDUINO — {ARDUINO_COLS}x{ARDUINO_ROWS}"
    else:
        mode = "NESSUN DISPOSITIVO — Solo preview"

    print(f"\n  > MODALITA': {mode}")
    print(f"  > Canvas: {LOGICAL_WIDTH}x{LOGICAL_HEIGHT}")


def apply_gamma(color):
    return gamma_table[color]


def create_udp_socket():
    if not ESP_ENABLED:
        return None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print(f"[OK] Socket UDP creato -> {len(ESP_IPS)} pannelli sulla porta {ESP_PORT}")
        for i, ip in enumerate(ESP_IPS):
            print(f"  Pannello {i}: {ip}")
        return sock
    except Exception as e:
        print(f"[X] Errore creazione socket UDP: {e}")
        return None


def create_arduino_serial():
    if not ARDUINO_ENABLED or not HAS_SERIAL:
        if not HAS_SERIAL:
            print("[!] pyserial non disponibile. Installa con: pip install pyserial")
        return None

    port = ARDUINO_PORT

    if port == "auto":
        porte_trovate = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')
        if not porte_trovate:
            print("[!] Nessuna porta seriale trovata!")
            print("    Controlla che l'Arduino sia collegato via USB.")
            return None
        port = porte_trovate[0]
        print(f"[AUTO] Porta seriale rilevata: {port}")

    try:
        ser = serial.Serial(port, ARDUINO_BAUD, timeout=0.01)
        time.sleep(2)
        print(f"[OK] Arduino connesso su {port} @ {ARDUINO_BAUD} baud")
        print(f"     Matrice: {ARDUINO_COLS}x{ARDUINO_ROWS} ({ARDUINO_COLS * ARDUINO_ROWS} LED)")
        ser.read_all()
        return ser
    except serial.SerialException as e:
        print(f"[X] Errore apertura porta {port}: {e}")
        return None
    except Exception as e:
        print(f"[!] Arduino non connesso: {e}")
        return None


def map_frame_to_leds(frame_rgb):
    out_buffer = bytearray(ARDUINO_COLS * ARDUINO_ROWS * 3)
    idx = 0
    for p in range(ARDUINO_PANELS_COUNT):
        panel_pos_x = ARDUINO_PANEL_ORDER[p]
        start_x = panel_pos_x * ARDUINO_PANEL_W
        starts_bottom = ARDUINO_PANEL_START_BOTTOM[p]
        for y_local in range(ARDUINO_PANEL_H):
            global_y = (ARDUINO_PANEL_H - 1) - y_local if starts_bottom else y_local
            for x_local in range(ARDUINO_PANEL_W):
                eff_x = x_local
                if ARDUINO_SERPENTINE_X and (y_local % 2 == 1):
                    eff_x = (ARDUINO_PANEL_W - 1) - x_local
                global_x = start_x + eff_x
                pixel = frame_rgb[global_y, global_x]
                out_buffer[idx]     = pixel[0]
                out_buffer[idx + 1] = pixel[1]
                out_buffer[idx + 2] = pixel[2]
                idx += 3
    return bytes(out_buffer)


# ============================================================
# FUNZIONI COLORE (LAB + Delta-E CIE2000)
# ============================================================

def rgb_to_lab(rgb):
    r, g, b = [x / 255.0 for x in rgb]

    def linearize(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = linearize(r), linearize(g), linearize(b)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    x, y, z = x / 0.95047, y / 1.0, z / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t + 16 / 116)

    L = 116 * f(y) - 16
    a = 500 * (f(x) - f(y))
    b_val = 200 * (f(y) - f(z))
    return (L, a, b_val)


def delta_e_cie2000(lab1, lab2):
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    kL, kC, kH = 1.0, 1.0, 1.0
    C1 = np.sqrt(a1**2 + b1**2)
    C2 = np.sqrt(a2**2 + b2**2)
    C_avg = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(C_avg**7 / (C_avg**7 + 25**7)))
    a1_prime = a1 * (1 + G)
    a2_prime = a2 * (1 + G)
    C1_prime = np.sqrt(a1_prime**2 + b1**2)
    C2_prime = np.sqrt(a2_prime**2 + b2**2)
    h1_prime = np.degrees(np.arctan2(b1, a1_prime)) % 360
    h2_prime = np.degrees(np.arctan2(b2, a2_prime)) % 360
    delta_L_prime = L2 - L1
    delta_C_prime = C2_prime - C1_prime
    delta_h_prime = h2_prime - h1_prime
    if abs(delta_h_prime) > 180:
        delta_h_prime -= 360 * np.sign(delta_h_prime)
    delta_H_prime = 2 * np.sqrt(C1_prime * C2_prime) * np.sin(np.radians(delta_h_prime / 2))
    L_avg_prime = (L1 + L2) / 2
    C_avg_prime = (C1_prime + C2_prime) / 2
    h_avg_prime = (h1_prime + h2_prime) / 2
    if abs(h1_prime - h2_prime) > 180:
        h_avg_prime += 180
    T = (1 - 0.17 * np.cos(np.radians(h_avg_prime - 30)) +
         0.24 * np.cos(np.radians(2 * h_avg_prime)) +
         0.32 * np.cos(np.radians(3 * h_avg_prime + 6)) -
         0.20 * np.cos(np.radians(4 * h_avg_prime - 63)))
    SL = 1 + (0.015 * (L_avg_prime - 50)**2) / np.sqrt(20 + (L_avg_prime - 50)**2)
    SC = 1 + 0.045 * C_avg_prime
    SH = 1 + 0.015 * C_avg_prime * T
    delta_theta = 30 * np.exp(-((h_avg_prime - 275) / 25)**2)
    RC = 2 * np.sqrt(C_avg_prime**7 / (C_avg_prime**7 + 25**7))
    RT = -RC * np.sin(np.radians(2 * delta_theta))
    delta_E = np.sqrt(
        (delta_L_prime / (kL * SL))**2 +
        (delta_C_prime / (kC * SC))**2 +
        (delta_H_prime / (kH * SH))**2 +
        RT * (delta_C_prime / (kC * SC)) * (delta_H_prime / (kH * SH))
    )
    return delta_E


COLOR_LAB_CACHE = {color.name: rgb_to_lab(color.rgb) for color in COLOR_DATABASE}


def find_closest_color(rgb):
    target_lab = rgb_to_lab(rgb)
    min_distance = float('inf')
    closest_color = None
    for color in COLOR_DATABASE:
        color_lab = COLOR_LAB_CACHE[color.name]
        distance = delta_e_cie2000(target_lab, color_lab)
        if distance < min_distance:
            min_distance = distance
            closest_color = color
    return (closest_color.name, closest_color.name_it, closest_color.hex_code, min_distance)


def rgb_to_hex(r, g, b):
    return f'#{r:02X}{g:02X}{b:02X}'


# ============================================================
# PIPELINE ACCURATEZZA (CLAHE + K-Means)
# ============================================================

CLAHE_CLIP_LIMIT = 2.0
KMEANS_CLUSTERS = 3


def _apply_clahe(roi):
    if roi.size == 0:
        return roi
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=(4, 4))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _extract_dominant_kmeans(roi, n_clusters=3):
    pixels = roi.reshape(-1, 3).astype(np.float32)
    if len(pixels) < n_clusters:
        return np.mean(pixels, axis=0).astype(int)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(
        pixels, n_clusters, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )
    dominant_idx = np.argmax(np.bincount(labels.flatten()))
    return centers[dominant_idx].astype(int)


# ============================================================
# GRIGLIA + PALETTE
# ============================================================

GRID_SIZES = [3, 5, 7]


def detect_grid_colors(frame, grid_size=5, sample_size=12):
    height, width = frame.shape[:2]
    colors = []
    margin_x = int(width * 0.28)
    margin_y = int(height * 0.28)
    for row in range(grid_size):
        for col in range(grid_size):
            px = margin_x + int((width - 2 * margin_x) * col / max(1, grid_size - 1))
            py = margin_y + int((height - 2 * margin_y) * row / max(1, grid_size - 1))
            half = sample_size // 2
            x1, y1 = max(0, px - half), max(0, py - half)
            x2, y2 = min(width, px + half), min(height, py + half)
            roi = frame[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            roi = _apply_clahe(roi)
            if roi.size > 9:
                avg_bgr = _extract_dominant_kmeans(
                    roi, min(KMEANS_CLUSTERS, roi.shape[0] * roi.shape[1]))
            else:
                avg_bgr = np.mean(roi, axis=(0, 1)).astype(int)
            b, g, r = avg_bgr
            rgb = (int(r), int(g), int(b))
            name_en, name_it, hex_code, distance = find_closest_color(rgb)
            colors.append({
                'rgb': rgb, 'bgr': (int(b), int(g), int(r)),
                'hex': rgb_to_hex(*rgb), 'name_en': name_en,
                'name_it': name_it, 'pos': (px, py), 'distance': distance
            })
    return colors


def export_palette(palette, grid_size):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_data = {
        "timestamp": datetime.now().isoformat(),
        "grid": f"{grid_size}x{grid_size}",
        "n_colors": len(palette),
        "colors": []
    }
    for color in palette:
        json_data["colors"].append({
            "name_en": color['name_en'], "name_it": color['name_it'],
            "hex": color['hex'], "rgb": list(color['rgb']),
        })
    json_filename = f"palette_{timestamp}.json"
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    swatch_w, swatch_h, text_h = 100, 100, 35
    n = len(palette)
    if n == 0:
        return json_filename
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    img = np.zeros((rows * (swatch_h + text_h), cols * swatch_w, 3), dtype=np.uint8)
    img[:] = (30, 30, 30)
    for i, color in enumerate(palette):
        col, row = i % cols, i // cols
        x, y = col * swatch_w, row * (swatch_h + text_h)
        cv2.rectangle(img, (x + 2, y + 2), (x + swatch_w - 2, y + swatch_h - 2), color['bgr'], -1)
        cv2.putText(img, color['hex'], (x + 5, y + swatch_h + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
        cv2.putText(img, color['name_it'][:10], (x + 5, y + swatch_h + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)
    cv2.imwrite(f"palette_{timestamp}.png", img)
    return json_filename


def draw_minimal_grid(grid_colors, grid_size, win_w=600, win_h=600):
    canvas = np.zeros((win_h, win_w, 3), dtype=np.uint8)
    swatch_w, swatch_h = win_w // grid_size, win_h // grid_size
    for i, color in enumerate(grid_colors):
        row, col = i // grid_size, i % grid_size
        x, y = col * swatch_w, row * swatch_h
        cv2.rectangle(canvas, (x, y), (x + swatch_w, y + swatch_h), color['bgr'], -1)
    return canvas


# ============================================================
# SELEZIONE CAMERA (Linux / V4L2)
# ============================================================

def list_cameras():
    """Scansione rapida V4L2: prova solo /dev/video0..9."""
    cameras = []
    for i in range(10):
        cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                cameras.append(i)
            cap.release()
    return cameras


def select_camera():
    print("\n[SCAN] Ricerca webcam (V4L2)...")
    cameras = list_cameras()
    if not cameras:
        print("[!] Nessuna webcam trovata, provo ID 0...")
        return 0
    print(f"[CAM] Trovate: {len(cameras)}")
    for cam_id in cameras:
        print(f"  [{cam_id}] /dev/video{cam_id}")
    if len(cameras) == 1:
        print(f"[OK] Camera {cameras[0]} selezionata automaticamente")
        return cameras[0]
    while True:
        try:
            choice = input(f"> Seleziona camera (0-{cameras[-1]}): ")
            cam_id = int(choice)
            if cam_id in cameras:
                return cam_id
            print("[X] Camera non valida!")
        except ValueError:
            print("[X] Inserisci un numero!")


def detect_center_color(frame, center_size=50):
    height, width = frame.shape[:2]
    cx, cy = width // 2, height // 2
    half = min(center_size // 2, cx, cy, width - cx, height - cy)
    if half < 1:
        half = 1
    roi = frame[cy - half:cy + half, cx - half:cx + half]
    roi = _apply_clahe(roi)
    if roi.size > 9:
        avg_bgr = _extract_dominant_kmeans(
            roi, min(KMEANS_CLUSTERS, roi.shape[0] * roi.shape[1]))
    else:
        avg_bgr = np.mean(roi, axis=(0, 1)).astype(int)
    b, g, r = avg_bgr
    rgb = (int(r), int(g), int(b))
    name_en, name_it, hex_code, distance = find_closest_color(rgb)
    return {
        'rgb': rgb, 'bgr': (int(b), int(g), int(r)),
        'hex': rgb_to_hex(*rgb), 'name_en': name_en,
        'name_it': name_it, 'distance': distance
    }


# ============================================================
# MAIN
# ============================================================

def main():
    global COMMON_ANODE

    print("\n" + "=" * 50)
    print("  LAVAGNA LED INTERATTIVA — RPi5 Edition")
    print("  Disegna con le mani sui pannelli LED!")
    print("=" * 50)

    # ── AUTO-RILEVAMENTO HARDWARE ──
    detect_hardware()

    # ── Seleziona camera ──
    camera_id = select_camera()

    print(f"\n[CAM] Avvio webcam {camera_id} a {CAM_WIDTH}x{CAM_HEIGHT} (V4L2)...")
    try:
        cam_thread = CameraThread(camera_id, CAM_WIDTH, CAM_HEIGHT)
    except RuntimeError as e:
        print(e)
        return
    cam_thread.start()

    # ── Audio synth ──
    synth = AudioSynth()

    # ── Tracker e Canvas ──
    tracker = HandTracker(canvas_width=LOGICAL_WIDTH, canvas_height=LOGICAL_HEIGHT)
    canvas_led = LEDCanvas(LOGICAL_WIDTH, LOGICAL_HEIGHT)

    print("\n" + "-" * 50)
    print("  CONTROLLI:")
    print("  [1-9]   - Cambia colore pennello")
    print("  [+/-]   - Cambia dimensione pennello")
    print("  [C]     - Cancella lavagna")
    print("  [S]     - Salva disegno come PNG")
    print("  [I]     - Inverti colori (Common Anode)")
    print("  [T]     - Modalita' Test Matrice (Calibrazione)")
    print("  [F]     - Fullscreen (toggle)")
    print("  [Q/ESC] - Esci")
    print("")
    print("  GESTI:")
    print("  Pinch (indice+pollice) = Disegna")
    print("  Pollice in giu' = Cancella lavagna")
    print("  Segno della pace (V) = Cambia colore pennello")
    print("-" * 50 + "\n")

    # ── Connessioni ──
    udp_sock = create_udp_socket()
    arduino_ser = create_arduino_serial()

    fullscreen = False
    cv2.namedWindow('Lavagna LED - Webcam', cv2.WINDOW_NORMAL)
    cv2.namedWindow('Lavagna LED - Canvas', cv2.WINDOW_NORMAL)

    arduino_status = "+ Arduino" if arduino_ser else "(no Arduino)"

    arduino_ready = True
    arduino_last_send_time = time.time()

    last_erase_time = 0.0
    ERASE_COOLDOWN = 1.5

    calibration_mode = False
    calib_x = 0
    calib_y = 0
    last_calib_time = time.time()

    # Contatore frame per il frame skip di MediaPipe
    frame_count = 0
    hand_states = []

    print(f"\n[LAVAGNA] Lavagna interattiva attiva! {arduino_status}")
    print(f"  Colore: {canvas_led.get_color_name()} | Pennello: {canvas_led.brush_size}px")

    try:
        while True:
            # ── 0. LEGGI FRAME DAL THREAD ──
            frame = cam_thread.read()
            if frame is None:
                continue
            frame_count += 1

            frame = cv2.flip(frame, 1)

            # ── 1. HAND TRACKING (ogni MEDIAPIPE_SKIP frame) ──
            if frame_count % MEDIAPIPE_SKIP == 0:
                hand_states = tracker.process_frame(frame)

            # ── 2. AGGIORNA CANVAS ──
            active_ids = {s.hand_label for s in hand_states}

            for hid in list(canvas_led._hand_states.keys()):
                if hid not in active_ids:
                    canvas_led.draw_at(0, 0, False, hand_id=hid)

            is_any_drawing = any(s.drawing for s in hand_states)
            if not is_any_drawing:
                synth.play_note(0, 0, canvas_led.width, canvas_led.height, False)

            for hand_state in hand_states:
                if hand_state.thumbs_down and not is_any_drawing and (time.time() - last_erase_time > ERASE_COOLDOWN):
                    canvas_led.clear()
                    last_erase_time = time.time()
                    print("[CANCELLA] Lavagna cancellata con POLLICE IN GIU'!")

            for hand_state in hand_states:
                if hand_state.peace_sign:
                    current_idx = canvas_led.get_color_index()
                    next_idx = (current_idx + 1) % len(COLOR_PALETTE)
                    canvas_led.set_color_by_index(next_idx)
                    print(f"[PACE] Nuovo colore: {canvas_led.get_color_name()}")

                if hand_state.drawing:
                    canvas_led.draw_at(hand_state.canvas_x, hand_state.canvas_y,
                                       True, hand_id=hand_state.hand_label,
                                       is_erasing=False)
                    synth.play_note(hand_state.canvas_x, hand_state.canvas_y,
                                   canvas_led.width, canvas_led.height, True)
                elif hand_state.precision_erasing:
                    canvas_led.draw_at(hand_state.canvas_x, hand_state.canvas_y,
                                       True, hand_id=hand_state.hand_label,
                                       is_erasing=True)
                else:
                    canvas_led.draw_at(hand_state.canvas_x, hand_state.canvas_y,
                                       False, hand_id=hand_state.hand_label,
                                       is_erasing=False)

            # ── 3. INVIA FRAME ──
            raw_rgb = canvas_led.get_frame_rgb()

            # --- INVIA LEDWALL ESP (UDP) ---
            if udp_sock is not None and ESP_ENABLED:
                esp_rgb = gamma_table[raw_rgb]
                if COMMON_ANODE:
                    esp_rgb = 255 - esp_rgb
                for indice, ip in enumerate(ESP_IPS):
                    taglio_x_inizio = indice * PANEL_WIDTH
                    taglio_x_fine = (indice + 1) * PANEL_WIDTH
                    fetta = esp_rgb[:, taglio_x_inizio:taglio_x_fine]
                    fetta_righe = fetta.copy().astype(np.uint8)
                    if ESP_START_BOTTOM:
                        fetta_righe = fetta_righe[::-1, :, :]
                    if ESP_SERPENTINE_HORIZONTAL:
                        fetta_righe[1::2] = fetta_righe[1::2, ::-1, :]
                    dati_grezzi = fetta_righe.flatten().tobytes()
                    meta = len(dati_grezzi) // 2
                    try:
                        udp_sock.sendto(bytes([0]) + dati_grezzi[:meta], (ip, ESP_PORT))
                        udp_sock.sendto(bytes([1]) + dati_grezzi[meta:], (ip, ESP_PORT))
                        time.sleep(0.003)
                    except Exception:
                        pass

            # --- INVIA ARDUINO (SERIALE) ---
            if arduino_ser is not None:
                if arduino_ser.in_waiting > 0:
                    risposta = arduino_ser.read_all()
                    if b'K' in risposta:
                        arduino_ready = True

                if not arduino_ready and (time.time() - arduino_last_send_time > 0.5):
                    arduino_ready = True

                if arduino_ready:
                    try:
                        ard_rgb = canvas_led.get_frame_rgb()
                        if ard_rgb.shape[1] != ARDUINO_COLS or ard_rgb.shape[0] != ARDUINO_ROWS:
                            ard_rgb = cv2.resize(ard_rgb, (ARDUINO_COLS, ARDUINO_ROWS),
                                                 interpolation=cv2.INTER_AREA)
                        if ARDUINO_MIRROR_HORIZONTAL:
                            ard_rgb = cv2.flip(ard_rgb, 1)

                        if calibration_mode:
                            ard_rgb = np.zeros((ARDUINO_ROWS, ARDUINO_COLS, 3), dtype=np.uint8)
                            now_t = time.time()
                            if now_t - last_calib_time > 0.05:
                                calib_x += 1
                                if calib_x >= ARDUINO_COLS:
                                    calib_x = 0
                                    calib_y += 1
                                    if calib_y >= ARDUINO_ROWS:
                                        calib_y = 0
                                last_calib_time = now_t
                            ard_rgb[calib_y, :] = (50, 0, 0)
                            ard_rgb[:, calib_x] = (0, 50, 0)
                            ard_rgb[calib_y, calib_x] = (255, 255, 255)

                        ard_rgb = gamma_table[ard_rgb]
                        if COMMON_ANODE:
                            ard_rgb = 255 - ard_rgb
                        rgb_bytes = map_frame_to_leds(ard_rgb)
                        arduino_ser.write(MAGIC_HEADER + rgb_bytes)
                        arduino_ready = False
                        arduino_last_send_time = time.time()
                    except Exception as e:
                        print(f"\n[X] Errore invio frame ad Arduino: {e}")
                        arduino_ser = None
                        print("  -> Arduino scollegato a causa dell'errore.")

            # ── 4. VISUALIZZAZIONE ──
            frame_preview = frame.copy()
            for hand_state in hand_states:
                tracker.draw_overlay(frame_preview, hand_state)

            color_bgr = tuple(int(c) for c in canvas_led.current_color[::-1])
            info_text = (f"Colore: {canvas_led.get_color_name()} | "
                         f"Pennello: {canvas_led.brush_size}px")
            cv2.putText(frame_preview, info_text, (10, frame.shape[0] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_bgr, 2)
            cv2.rectangle(frame_preview, (frame.shape[1] - 50, 10),
                          (frame.shape[1] - 10, 50), color_bgr, -1)
            cv2.rectangle(frame_preview, (frame.shape[1] - 50, 10),
                          (frame.shape[1] - 10, 50), (255, 255, 255), 1)

            cv2.imshow('Lavagna LED - Webcam', frame_preview)

            cursor_x, cursor_y = -1, -1
            for h in hand_states:
                if h.detected:
                    cursor_x, cursor_y = h.canvas_x, h.canvas_y
                    break

            canvas_preview = canvas_led.get_preview(scale=15, cursor_x=cursor_x, cursor_y=cursor_y)
            cv2.imshow('Lavagna LED - Canvas', canvas_preview)

            # ── 5. INPUT TASTIERA ──
            key = cv2.waitKey(16) & 0xFF

            if key == ord('q') or key == 27:
                print("\n[BYE] Arrivederci!")
                break
            elif key == ord('f'):
                fullscreen = not fullscreen
                prop = cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL
                cv2.setWindowProperty('Lavagna LED - Webcam', cv2.WND_PROP_FULLSCREEN, prop)
            elif key == ord('t'):
                calibration_mode = not calibration_mode
                state = "ATTIVA" if calibration_mode else "DISATTIVA"
                print(f"\n[TEST] Modalita' Calibrazione Matrice: {state}")
                if calibration_mode:
                    print("=> Guarda il pannello LED. Un punto bianco con croce "
                          "rosso/verde lo attraversera'.")
            elif key == ord('i'):
                COMMON_ANODE = not COMMON_ANODE
                state = "ATTIVA" if COMMON_ANODE else "DISATTIVA"
                print(f"\n[TOGGLE] Modalita' Inversione: {state}")
            elif key == ord('c'):
                canvas_led.clear()
                last_erase_time = time.time()
                print("[CANCELLA] Lavagna cancellata (tasto C)")
            elif key == ord('s'):
                filename = f"disegno_led_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                img = canvas_led.get_frame_rgb()
                cv2.imwrite(filename, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
                print(f"[SALVA] Immagine salvata come {filename}")
            elif key == ord('+') or key == ord('='):
                new_size = min(5, canvas_led.brush_size + 1)
                canvas_led.set_brush_size(new_size)
                print(f"[PENNELLO] Dimensione aumentata a {new_size}px")
            elif key == ord('-'):
                new_size = max(1, canvas_led.brush_size - 1)
                canvas_led.set_brush_size(new_size)
                print(f"[PENNELLO] Dimensione ridotta a {new_size}px")
            elif ord('1') <= key <= ord('9'):
                idx = key - ord('1')
                canvas_led.set_color_by_index(idx)
                print(f"[COLORE] Tasto {chr(key)} -> {canvas_led.get_color_name()}")

    finally:
        cam_thread.stop()
        tracker.release()
        cv2.destroyAllWindows()

        if arduino_ser:
            try:
                print("[LED] Spegnimento LED Arduino...")
                black_frame = np.zeros((ARDUINO_ROWS, ARDUINO_COLS, 3), dtype=np.uint8)
                arduino_ser.write(MAGIC_HEADER + map_frame_to_leds(black_frame))
                time.sleep(0.1)
                arduino_ser.close()
                print("[OK] LED Arduino spenti. Seriale chiusa.")
            except Exception:
                pass

        if udp_sock and ESP_ENABLED:
            try:
                print("[LED] Spegnimento LED ESP...")
                frame_nero = bytes(PANEL_WIDTH * PANEL_HEIGHT * 3)
                for ip in ESP_IPS:
                    meta = len(frame_nero) // 2
                    udp_sock.sendto(bytes([0]) + frame_nero[:meta], (ip, ESP_PORT))
                    udp_sock.sendto(bytes([1]) + frame_nero[meta:], (ip, ESP_PORT))
                    time.sleep(0.02)
                print("[OK] LED ESP spenti.")
            except Exception as e:
                print(f"[X] Errore nello spegnimento LED ESP: {e}")


if __name__ == "__main__":
    main()
