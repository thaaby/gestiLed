#!/usr/bin/env python3
"""
TEST ARDUINO LED MATRICE 56x32
==============================
Script standalone per testare la comunicazione seriale con l'Arduino.

PREREQUISITO: Caricare arduino_video_only/arduino_video_only.ino sull'Arduino!
              (NON arduino_palette_sketch.ino — quello ha un bug con gli interrupt)

TASTI:
  1 = Pannelli tricolore (SX=Blu, CSX=Rosso, CDX=Verde, DX=Giallo)
  2 = Pannelli invertiti  (SX=Verde, CSX=Giallo, CDX=Blu, DX=Rosso)
  3 = Tutto ROSSO
  4 = Tutto VERDE
  5 = Tutto BLU
  6 = Snake test (pixel bianco che attraversa la matrice)
  7 = Arcobaleno orizzontale
  8 = Riga bianca che scorre dall'alto al basso
  9 = Scacchiera bianco/nero (test mapping)
  0 = Spegni tutto (nero)
  Q / ESC = Esci
"""

import numpy as np
import cv2
import time
import sys
import glob
import colorsys

try:
    import serial
except ImportError:
    print("[X] pyserial non installato! Installa con: pip install pyserial")
    sys.exit(1)

# ============================================================
# CONFIGURAZIONE (identica a minimalv2.py)
# ============================================================
ARDUINO_PORT = "auto"
ARDUINO_BAUD = 500000
ARDUINO_ROWS = 32
ARDUINO_COLS = 56
ARDUINO_PANEL_W = 8
ARDUINO_PANEL_H = 32
ARDUINO_PANELS_COUNT = 7
ARDUINO_MIRROR_HORIZONTAL = True
ARDUINO_MIRROR_VERTICAL = True

ARDUINO_PANEL_ORDER = [6, 5, 4, 3, 2, 1, 0]
ARDUINO_PANEL_START_BOTTOM = [False, False, False, False, False, False, False]
ARDUINO_SERPENTINE_X = True

GAMMA = 2.5
gamma_table = np.array([((i / 255.0) ** GAMMA) * 255
                         for i in np.arange(0, 256)]).astype("uint8")

MAGIC_HEADER = b'\xFFLE'  # 0xFF 0x4C 0x45


# ============================================================
# MAPPING (identico a minimalv2.py)
# ============================================================
def map_frame_to_leds(frame_rgb):
    """Converte un frame 56x32 RGB in buffer seriale per Arduino."""
    out_buffer = bytearray(ARDUINO_COLS * ARDUINO_ROWS * 3)
    idx = 0

    for p in range(ARDUINO_PANELS_COUNT):
        panel_pos_x = ARDUINO_PANEL_ORDER[p]
        start_x = panel_pos_x * ARDUINO_PANEL_W
        starts_bottom = ARDUINO_PANEL_START_BOTTOM[p]

        for y_local in range(ARDUINO_PANEL_H):
            if starts_bottom:
                global_y = (ARDUINO_PANEL_H - 1) - y_local
            else:
                global_y = y_local

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
# CONNESSIONE SERIALE
# ============================================================
def connect_arduino():
    port = ARDUINO_PORT
    if port == "auto":
        porte = (
            glob.glob('/dev/ttyUSB*') +
            glob.glob('/dev/ttyACM*') +
            glob.glob('/dev/cu.usbmodem*') +
            glob.glob('/dev/cu.usbserial*')
        )
        if not porte:
            print("[X] Nessuna porta seriale trovata!")
            return None
        port = porte[0]
        print(f"[AUTO] Porta: {port}")

    try:
        ser = serial.Serial(port, ARDUINO_BAUD, timeout=0.1)
        time.sleep(2.5)  # Attendi reset Arduino + lampeggi avvio
        
        # Leggi messaggi di avvio
        startup = ser.read_all().decode('utf-8', errors='ignore')
        if startup.strip():
            for line in startup.strip().split('\n'):
                print(f"  Arduino: {line.strip()}")

        print(f"[OK] Arduino connesso su {port} @ {ARDUINO_BAUD} baud")
        return ser
    except Exception as e:
        print(f"[X] Errore: {e}")
        return None


# ============================================================
# INVIO FRAME
# ============================================================
def send_frame(ser, frame_rgb, retries=3):
    """Invia un frame 56x32 RGB all'Arduino con retry."""
    if frame_rgb.shape != (ARDUINO_ROWS, ARDUINO_COLS, 3):
        frame_rgb = cv2.resize(frame_rgb, (ARDUINO_COLS, ARDUINO_ROWS),
                               interpolation=cv2.INTER_AREA)

    if ARDUINO_MIRROR_HORIZONTAL:
        frame_rgb = cv2.flip(frame_rgb, 1)
    if ARDUINO_MIRROR_VERTICAL:
        frame_rgb = cv2.flip(frame_rgb, 0)

    frame_gamma = gamma_table[frame_rgb]
    rgb_bytes = map_frame_to_leds(frame_gamma)
    payload = MAGIC_HEADER + rgb_bytes

    for attempt in range(retries):
        # Pulisci buffer in/out prima di inviare
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        # Invia frame
        ser.write(payload)
        ser.flush()  # Assicura che tutti i byte siano inviati

        # Attendi ACK (con timeout)
        start = time.time()
        while time.time() - start < 1.0:
            if ser.in_waiting > 0:
                resp = ser.read(ser.in_waiting)
                if b'K' in resp:
                    return True
            time.sleep(0.005)

        # Timeout: retry
        if attempt < retries - 1:
            # Flush e piccola pausa prima del retry
            ser.reset_input_buffer()
            time.sleep(0.05)

    return False


# ============================================================
# PATTERN DI TEST
# ============================================================

def make_panels_tricolor():
    """Test 1: ogni pannello 8x32 un colore diverso."""
    frame = np.zeros((ARDUINO_ROWS, ARDUINO_COLS, 3), dtype=np.uint8)
    colors = [
        (0, 0, 255),    # Pannello 0: Blu
        (255, 0, 0),    # Pannello 1: Rosso
        (0, 255, 0),    # Pannello 2: Verde
        (255, 255, 0),  # Pannello 3: Giallo
        (255, 0, 255),  # Pannello 4: Magenta
        (0, 255, 255),  # Pannello 5: Ciano
        (255, 128, 0),  # Pannello 6: Arancione
    ]
    for i in range(ARDUINO_PANELS_COUNT):
        x_start = i * ARDUINO_PANEL_W
        x_end = (i + 1) * ARDUINO_PANEL_W
        frame[:, x_start:x_end] = colors[i]
    return frame


def make_panels_inverted():
    """Test 2: colori invertiti rispetto al test 1."""
    frame = np.zeros((ARDUINO_ROWS, ARDUINO_COLS, 3), dtype=np.uint8)
    colors = [
        (0, 255, 0),    # Pannello 0: Verde
        (255, 255, 0),  # Pannello 1: Giallo
        (0, 0, 255),    # Pannello 2: Blu
        (255, 0, 0),    # Pannello 3: Rosso
        (0, 255, 255),  # Pannello 4: Ciano
        (255, 0, 255),  # Pannello 5: Magenta
        (255, 128, 0),  # Pannello 6: Arancione
    ]
    for i in range(ARDUINO_PANELS_COUNT):
        x_start = i * ARDUINO_PANEL_W
        x_end = (i + 1) * ARDUINO_PANEL_W
        frame[:, x_start:x_end] = colors[i]
    return frame


def make_solid(r, g, b):
    """Crea un frame di colore solido."""
    frame = np.zeros((ARDUINO_ROWS, ARDUINO_COLS, 3), dtype=np.uint8)
    frame[:, :] = (r, g, b)
    return frame


def make_rainbow():
    """Test 7: gradiente arcobaleno orizzontale."""
    frame = np.zeros((ARDUINO_ROWS, ARDUINO_COLS, 3), dtype=np.uint8)
    for x in range(ARDUINO_COLS):
        hue = x / ARDUINO_COLS
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        frame[:, x] = (int(r * 255), int(g * 255), int(b * 255))
    return frame


def make_checkerboard(block_size=4):
    """Test 9: scacchiera bianco/nero."""
    frame = np.zeros((ARDUINO_ROWS, ARDUINO_COLS, 3), dtype=np.uint8)
    for y in range(ARDUINO_ROWS):
        for x in range(ARDUINO_COLS):
            if ((x // block_size) + (y // block_size)) % 2 == 0:
                frame[y, x] = (255, 255, 255)
    return frame


# ============================================================
# VISUALIZZAZIONE PREVIEW
# ============================================================
def show_preview(frame, title="Test Arduino"):
    """Mostra una preview ingrandita del frame."""
    scale = 12
    preview = cv2.resize(frame, (ARDUINO_COLS * scale, ARDUINO_ROWS * scale),
                         interpolation=cv2.INTER_NEAREST)
    preview_bgr = cv2.cvtColor(preview, cv2.COLOR_RGB2BGR)

    # Griglia pannelli
    for i in range(1, ARDUINO_PANELS_COUNT):
        x = i * ARDUINO_PANEL_W * scale
        cv2.line(preview_bgr, (x, 0), (x, ARDUINO_ROWS * scale),
                 (128, 128, 128), 1)

    cv2.imshow(title, preview_bgr)


# ============================================================
# MAIN
# ============================================================
def main():
    print("\n" + "=" * 55)
    print("  TEST ARDUINO LED MATRICE 56x32")
    print("  Premi i tasti per testare i pattern")
    print("=" * 55)
    print()
    print("  IMPORTANTE: Caricare arduino_video_only.ino!")
    print()
    print("  [1] Pannelli tricolore (Blu/Rosso/Verde/Giallo)")
    print("  [2] Pannelli invertiti (Verde/Giallo/Blu/Rosso)")
    print("  [3] Tutto ROSSO")
    print("  [4] Tutto VERDE")
    print("  [5] Tutto BLU")
    print("  [6] Snake test (pixel bianco mobile)")
    print("  [7] Arcobaleno orizzontale")
    print("  [8] Riga bianca scorrevole")
    print("  [9] Scacchiera")
    print("  [0] Spegni tutto")
    print("  [Q/ESC] Esci")
    print()

    ser = connect_arduino()
    if not ser:
        print("[X] Impossibile connettersi all'Arduino!")
        return

    cv2.namedWindow("Test Arduino", cv2.WINDOW_NORMAL)

    current_test = "nessuno"
    snake_pos = 0
    row_pos = 0
    animation_active = False
    frames_ok = 0
    frames_fail = 0

    # Invia frame nero iniziale
    frame = make_solid(0, 0, 0)
    send_frame(ser, frame)
    show_preview(frame)

    print("\n[READY] Premi un tasto nella finestra OpenCV!\n")

    try:
        while True:
            # Animazioni continue
            if animation_active:
                if current_test == "snake":
                    frame = np.zeros((ARDUINO_ROWS, ARDUINO_COLS, 3), dtype=np.uint8)
                    y = snake_pos // ARDUINO_COLS
                    x = snake_pos % ARDUINO_COLS
                    if y < ARDUINO_ROWS:
                        frame[y, x] = (255, 255, 255)
                        # Coda del serpente
                        for tail in range(1, 4):
                            tp = snake_pos - tail
                            if tp >= 0:
                                ty = tp // ARDUINO_COLS
                                tx = tp % ARDUINO_COLS
                                brightness = max(0, 255 - tail * 70)
                                frame[ty, tx] = (brightness, brightness, brightness)

                    ok = send_frame(ser, frame, retries=1)
                    show_preview(frame)
                    if ok:
                        frames_ok += 1
                    else:
                        frames_fail += 1

                    snake_pos += 1
                    if snake_pos >= ARDUINO_ROWS * ARDUINO_COLS:
                        snake_pos = 0
                        print(f"  Snake ciclo completato: OK={frames_ok} FAIL={frames_fail}")
                        frames_ok = 0
                        frames_fail = 0

                elif current_test == "row_scan":
                    frame = np.zeros((ARDUINO_ROWS, ARDUINO_COLS, 3), dtype=np.uint8)
                    frame[row_pos, :] = (255, 255, 255)
                    if row_pos > 0:
                        frame[row_pos - 1, :] = (60, 60, 60)

                    ok = send_frame(ser, frame, retries=1)
                    show_preview(frame)

                    row_pos = (row_pos + 1) % ARDUINO_ROWS

            key = cv2.waitKey(30 if animation_active else 100) & 0xFF

            if key == ord('q') or key == 27:
                print("\n[BYE] Spegnimento LED...")
                break

            elif key == ord('1'):
                animation_active = False
                current_test = "tricolor"
                frame = make_panels_tricolor()
                ok = send_frame(ser, frame)
                show_preview(frame)
                status = "OK ✓" if ok else "TIMEOUT ✗"
                print(f"[TEST 1] Pannelli tricolore — {status}")

            elif key == ord('2'):
                animation_active = False
                current_test = "inverted"
                frame = make_panels_inverted()
                ok = send_frame(ser, frame)
                show_preview(frame)
                status = "OK ✓" if ok else "TIMEOUT ✗"
                print(f"[TEST 2] Pannelli invertiti — {status}")

            elif key == ord('3'):
                animation_active = False
                current_test = "red"
                frame = make_solid(255, 0, 0)
                ok = send_frame(ser, frame)
                show_preview(frame)
                status = "OK ✓" if ok else "TIMEOUT ✗"
                print(f"[TEST 3] Tutto ROSSO — {status}")

            elif key == ord('4'):
                animation_active = False
                current_test = "green"
                frame = make_solid(0, 255, 0)
                ok = send_frame(ser, frame)
                show_preview(frame)
                status = "OK ✓" if ok else "TIMEOUT ✗"
                print(f"[TEST 4] Tutto VERDE — {status}")

            elif key == ord('5'):
                animation_active = False
                current_test = "blue"
                frame = make_solid(0, 0, 255)
                ok = send_frame(ser, frame)
                show_preview(frame)
                status = "OK ✓" if ok else "TIMEOUT ✗"
                print(f"[TEST 5] Tutto BLU — {status}")

            elif key == ord('6'):
                animation_active = True
                current_test = "snake"
                snake_pos = 0
                frames_ok = 0
                frames_fail = 0
                print("[TEST 6] Snake test avviato... (premi altro tasto per fermare)")

            elif key == ord('7'):
                animation_active = False
                current_test = "rainbow"
                frame = make_rainbow()
                ok = send_frame(ser, frame)
                show_preview(frame)
                status = "OK ✓" if ok else "TIMEOUT ✗"
                print(f"[TEST 7] Arcobaleno — {status}")

            elif key == ord('8'):
                animation_active = True
                current_test = "row_scan"
                row_pos = 0
                print("[TEST 8] Riga scorrevole... (premi altro tasto per fermare)")

            elif key == ord('9'):
                animation_active = False
                current_test = "checkerboard"
                frame = make_checkerboard()
                ok = send_frame(ser, frame)
                show_preview(frame)
                status = "OK ✓" if ok else "TIMEOUT ✗"
                print(f"[TEST 9] Scacchiera — {status}")

            elif key == ord('0'):
                animation_active = False
                current_test = "off"
                frame = make_solid(0, 0, 0)
                ok = send_frame(ser, frame)
                show_preview(frame)
                print("[TEST 0] LED spenti")

    finally:
        # Spegni tutto prima di uscire
        try:
            frame = make_solid(0, 0, 0)
            rgb_bytes = map_frame_to_leds(frame)
            ser.write(MAGIC_HEADER + rgb_bytes)
            time.sleep(0.1)
            ser.close()
            print("[OK] LED spenti. Seriale chiusa.")
        except Exception:
            pass
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
