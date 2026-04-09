#!/usr/bin/env python3
"""
DOOM → ARDUINO 56x32 (SPECCHIO)
=================================
Cattura la finestra attiva di DOOM e la streamma sulla matrice Arduino 56x32.
Usa la logica ESATTA di minimalv2.py: invio non-bloccante, MAGIC_HEADER,
mappatura pannelli con serpentina, gamma e mirror orizzontale.

PREREQUISITO: arduino_video_only/arduino_video_only.ino sull'Arduino!

USO:
  python3 doom_ledwall.py
  Durante il conto alla rovescia, clicca sulla finestra di DOOM.
  Q = esci.
"""

import cv2
import numpy as np
import mss
import time
import subprocess
import glob
import sys

try:
    import serial
except ImportError:
    print("[X] pyserial non installato! pip install pyserial")
    sys.exit(1)


# ============================================================
# CONFIGURAZIONE ARDUINO — IDENTICA A minimalv2.py
# ============================================================
ARDUINO_PORT           = "auto"
ARDUINO_BAUD           = 500000
ARDUINO_ROWS           = 32
ARDUINO_COLS           = 56
ARDUINO_PANEL_W        = 8
ARDUINO_PANEL_H        = 32
ARDUINO_PANELS_COUNT   = 7
ARDUINO_MIRROR_HORIZONTAL = True
ARDUINO_MIRROR_VERTICAL = True

ARDUINO_PANEL_ORDER        = [6, 5, 4, 3, 2, 1, 0]
ARDUINO_PANEL_START_BOTTOM = [False, False, False, False, False, False, False]
ARDUINO_SERPENTINE_X       = True

MAGIC_HEADER = b'\xFFLE'   # 0xFF 0x4C 0x45

GAMMA = 2.5
gamma_table = np.array([((i / 255.0) ** GAMMA) * 255
                         for i in np.arange(0, 256)]).astype("uint8")

# ============================================================
# CROP ASPECT RATIO (4:3 per DOOM, None = libero)
# ============================================================
FORCE_ASPECT_RATIO = 4 / 3


# ============================================================
# MAPPATURA PANNELLI — IDENTICA A minimalv2.py / test_arduino.py
# ============================================================
def map_frame_to_leds(frame_rgb: np.ndarray) -> bytes:
    """Converte frame 56x32 RGB in buffer seriale ordinato per pannelli."""
    out_buffer = bytearray(ARDUINO_COLS * ARDUINO_ROWS * 3)
    idx = 0

    for p in range(ARDUINO_PANELS_COUNT):
        panel_pos_x   = ARDUINO_PANEL_ORDER[p]
        start_x       = panel_pos_x * ARDUINO_PANEL_W
        starts_bottom = ARDUINO_PANEL_START_BOTTOM[p]

        for y_local in range(ARDUINO_PANEL_H):
            global_y = (ARDUINO_PANEL_H - 1) - y_local if starts_bottom else y_local

            for x_local in range(ARDUINO_PANEL_W):
                eff_x = x_local
                if ARDUINO_SERPENTINE_X and (y_local % 2 == 1):
                    eff_x = (ARDUINO_PANEL_W - 1) - x_local
                global_x = start_x + eff_x

                pixel            = frame_rgb[global_y, global_x]
                out_buffer[idx  ] = pixel[0]
                out_buffer[idx+1] = pixel[1]
                out_buffer[idx+2] = pixel[2]
                idx += 3

    return bytes(out_buffer)


# ============================================================
# CONNESSIONE ARDUINO
# ============================================================
def connect_arduino():
    port = ARDUINO_PORT
    if port == "auto":
        porte = (glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*') +
                 glob.glob('/dev/cu.usbmodem*') + glob.glob('/dev/cu.usbserial*'))
        if not porte:
            print("[X] Nessuna porta seriale trovata!")
            return None
        port = porte[0]
        print(f"[AUTO] Porta: {port}")

    try:
        ser = serial.Serial(port, ARDUINO_BAUD, timeout=0.01)
        print("[WAIT] Reset Arduino...", end=" ", flush=True)
        time.sleep(2.5)
        ser.read_all()   # svuota buffer avvio
        print(f"[OK] Arduino connesso su {port} @ {ARDUINO_BAUD} baud")
        return ser
    except Exception as e:
        print(f"[X] Errore connessione: {e}")
        return None


# ============================================================
# CATTURA FINESTRA AUTOMATICA (AppleScript macOS)
# ============================================================
COUNTDOWN_SECONDS = 4

def get_frontmost_window_bounds():
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        tell frontApp
            if (count of windows) > 0 then
                set w to first window
                set pos to position of w
                set sz to size of w
                return (item 1 of pos as text) & "," & (item 2 of pos as text) & "," & (item 1 of sz as text) & "," & (item 2 of sz as text) & "," & appName
            end if
        end tell
    end tell
    """
    try:
        res = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split(",")
            if len(parts) >= 4:
                x, y, w, h = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                app_name = parts[4].strip() if len(parts) > 4 else "?"
                return x, y, w, h, app_name
    except Exception as e:
        print(f"[!] AppleScript fallito: {e}")
    return None


def countdown_and_capture():
    preview = np.zeros((300, 500, 3), dtype=np.uint8)
    cv2.namedWindow("DOOM 56x32 - Setup", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("DOOM 56x32 - Setup", 500, 300)

    for i in range(COUNTDOWN_SECONDS, 0, -1):
        preview[:] = (20, 20, 40)
        cv2.putText(preview, "Clicca sulla finestra di DOOM!", (20, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 50), 2)
        cv2.putText(preview, "Cattura in:", (20, 140),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 1)
        cv2.putText(preview, str(i), (210, 230),
                    cv2.FONT_HERSHEY_SIMPLEX, 3.5, (50, 255, 100), 5)
        cv2.imshow("DOOM 56x32 - Setup", preview)
        cv2.waitKey(1000)

    preview[:] = (20, 40, 20)
    cv2.putText(preview, "Lettura finestra...", (80, 160),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 255, 100), 2)
    cv2.imshow("DOOM 56x32 - Setup", preview)
    cv2.waitKey(500)
    cv2.destroyWindow("DOOM 56x32 - Setup")
    return get_frontmost_window_bounds()


# ============================================================
# MAIN
# ============================================================
def main():
    print("\n" + "=" * 55)
    print("  DOOM → ARDUINO 56x32")
    print("=" * 55 + "\n")

    ser = connect_arduino()
    if ser is None:
        print("[X] Arduino non trovato. Controlla il collegamento USB.")
        return

    print(f"\n[INFO] Tra {COUNTDOWN_SECONDS}s clicca sulla finestra di DOOM!")
    bounds = countdown_and_capture()
    if bounds is None:
        print("[X] Impossibile trovare la finestra DOOM.")
        ser.close()
        return

    x, y, w, h, app_name = bounds
    print(f"[OK] Finestra: '{app_name}'  pos({x},{y})  dim({w}x{h})")

    titlebar_h = 28
    monitor = {"top": y + titlebar_h, "left": x, "width": w, "height": h - titlebar_h}
    print(f"[OK] Area cattura: {monitor}")
    print("\n[DOOM MODE] Premi Q per uscire.\n")

    scale = 14
    cv2.namedWindow("DOOM 56x32 - Preview", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("DOOM 56x32 - Preview", ARDUINO_COLS * scale, ARDUINO_ROWS * scale)

    # Stato invio non-bloccante (come in minimalv2.py)
    arduino_ready         = True
    arduino_last_send_time = time.time()

    frame_count = 0
    t_start     = time.time()

    with mss.mss() as sct:
        while True:
            # 1. CATTURA
            try:
                screenshot = sct.grab(monitor)
            except Exception as e:
                print(f"[!] Errore cattura: {e}")
                time.sleep(0.05)
                continue

            frame_bgr = np.array(screenshot)[:, :, :3]

            # 2. CROP 4:3 (evita stretching di DOOM)
            fh, fw = frame_bgr.shape[:2]
            if FORCE_ASPECT_RATIO is not None:
                target_w = int(fh * FORCE_ASPECT_RATIO)
                if target_w < fw:
                    off = (fw - target_w) // 2
                    frame_bgr = frame_bgr[:, off:off + target_w]
                elif target_w > fw:
                    target_h = int(fw / FORCE_ASPECT_RATIO)
                    off = (fh - target_h) // 2
                    frame_bgr = frame_bgr[off:off + target_h, :]

            # 3. RESIZE → 32x32 (INTER_AREA = miglior qualità per downscale)
            frame_piccolo = cv2.resize(frame_bgr, (ARDUINO_COLS, ARDUINO_ROWS),
                                       interpolation=cv2.INTER_AREA)

            frame_rgb = cv2.cvtColor(frame_piccolo, cv2.COLOR_BGR2RGB)

            # 4. INVIO NON-BLOCCANTE — logica identica a minimalv2.py
            #    Controlla ACK del frame precedente
            if ser.in_waiting > 0:
                risposta = ser.read_all()
                if b'K' in risposta:
                    arduino_ready = True

            # Se nessun ACK dopo 0.5s, invia comunque (evita blocco)
            if not arduino_ready and (time.time() - arduino_last_send_time > 0.5):
                arduino_ready = True

            if arduino_ready:
                try:
                    # Mirror orizzontale (come in minimalv2.py)
                    ard_rgb = frame_rgb.copy()
                    if ARDUINO_MIRROR_HORIZONTAL:
                        ard_rgb = cv2.flip(ard_rgb, 1)
                    if ARDUINO_MIRROR_VERTICAL:
                        ard_rgb = cv2.flip(ard_rgb, 0)

                    # Applica gamma (come in minimalv2.py)
                    ard_rgb = gamma_table[ard_rgb]

                    # Mappa sui pannelli e invia
                    rgb_bytes = map_frame_to_leds(ard_rgb)
                    ser.write(MAGIC_HEADER + rgb_bytes)

                    arduino_ready          = False
                    arduino_last_send_time = time.time()

                except Exception as e:
                    print(f"[X] Errore invio: {e}")
                    ser = None
                    break

            # 5. PREVIEW PIXEL-ART sul PC
            preview = cv2.resize(frame_piccolo,
                                 (ARDUINO_COLS * scale, ARDUINO_ROWS * scale),
                                 interpolation=cv2.INTER_NEAREST)
            cv2.imshow("DOOM 56x32 - Preview", preview)

            frame_count += 1
            elapsed = time.time() - t_start
            if elapsed >= 5.0:
                print(f"[FPS] {frame_count / elapsed:.1f}")
                frame_count = 0
                t_start     = time.time()

            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("\n[BYE] Uscita...")
                break

    # Spegni LED
    try:
        black = np.zeros((ARDUINO_ROWS, ARDUINO_COLS, 3), dtype=np.uint8)
        ser.write(MAGIC_HEADER + map_frame_to_leds(black))
        time.sleep(0.1)
        ser.close()
    except Exception:
        pass
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()