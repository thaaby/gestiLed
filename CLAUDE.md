# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Lavagna LED Interattiva** — Sistema di disegno interattivo su pannelli LED controllati tramite gesti delle mani (webcam + MediaPipe). Il sistema ha due modalita' di output mutuamente esclusive, rilevate automaticamente all'avvio (`detect_hardware()`):

- **Modalita' ESP (LED Wall)**: 6 pannelli ESP da 15x44 pixel ciascuno, collegati via WiFi/UDP. Si attiva se il primo ESP risponde al ping. Canvas logico: 90x44.
- **Modalita' Arduino (fallback)**: 7 pannelli da 8x32 pixel (matrici WS2812B), collegati in serie via cavo seriale ad un Arduino. Si attiva se viene trovata una porta seriale USB. Canvas logico: 56x32.

Se entrambi sono disponibili, si attiva la modalita' DUAL (canvas ESP come primario).

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# doom_ledwall.py richiede anche: pip install mss
```

Il file `hand_landmarker.task` (modello MediaPipe) deve essere nella root del progetto.

## Running

```bash
# Applicazione principale — disegno interattivo con gesti
python3 Lavagna.py

# Streaming finestra DOOM sulla matrice Arduino (solo macOS, usa osascript)
python3 doom_ledwall.py

# Test pattern Arduino (per calibrazione e debug pannelli)
python3 test_arduino.py

# Versione Linux / Raspberry Pi 5
python3 Lavagna-Linux/minimalv2.py
```

## Architecture

### Due protocolli di output

**ESP (UDP)**: ogni pannello ha un IP fisso (`ESP_IPS` in Lavagna.py). Il frame viene tagliato in fette verticali di 15px, ogni fetta viene serializzata riga per riga con serpentina orizzontale, divisa in 2 pacchetti UDP (prefisso `0x00` e `0x01`), e inviata sulla porta 4210. Pausa di 3ms tra pannelli per non sovraccaricare il router.

**Arduino (Seriale)**: frame inviato come `MAGIC_HEADER (0xFF 0x4C 0x45)` + buffer RGB. Il buffer e' ordinato per pannelli (non per righe): la funzione `map_frame_to_leds()` itera pannello per pannello secondo `ARDUINO_PANEL_ORDER`, applicando cablaggio serpentina (`ARDUINO_SERPENTINE_X`). Arduino risponde con `'K'` (ACK). Invio non-bloccante con timeout 0.5s.

Prima dell'invio: mirror orizzontale + correzione gamma (γ=2.5) tramite lookup table.

### Moduli

- **`Lavagna.py`** — Entry point principale. Orchestrazione: detect hardware → selezione camera → loop principale (tracking → canvas → invio LED → preview OpenCV → input tastiera). Contiene anche il database colori (~100 colori con nomi IT/EN), la pipeline di riconoscimento colore tramite CLAHE + K-Means + Delta-E CIE2000, e la modalita' calibrazione matrice (tasto T).
- **`hand_tracker.py` (`HandTracker`)** — MediaPipe HandLandmarker in modalita' LIVE_STREAM asincrona (max 2 mani). Gesti riconosciuti con isteresi multi-frame per evitare falsi positivi:
  - **Pinch** (pollice+indice vicini): disegna. Isteresi con soglie diverse per attivazione/disattivazione + grace period di 3 frame.
  - **Indice solo + pollice piegato**: cancellino di precisione. Grace period post-drawing di 8 frame per evitare attivazione accidentale.
  - **V (pace)**: cambia colore. Richiede 5 frame stabili + cooldown 1s.
  - **Pollice in giu'**: cancella tutto. Richiede 5 frame stabili + cooldown 1.5s.
  - Smoothing EMA (α=0.35) sulla posizione. Zona attiva: margine 10% su ogni lato.
- **`led_canvas.py` (`LEDCanvas`)** — Stato pixel come array NumPy `(height, width, 3)`. Disegno con interpolazione Bresenham tra frame successivi. Supporta multi-mano (stato separato per hand_id), brush size 1-3, e esportazione PNG.
- **`audio_synth.py` (`AudioSynth`)** — Sintetizzatore Pygame. Scala pentatonica su 3 ottave: Y mappa alla nota (alto=acuto, basso=grave), X mappa al panning stereo.
- **`doom_ledwall.py`** — Script standalone. Cattura finestra macOS via `mss` + AppleScript, crop 4:3, resize a 56x32, stessa pipeline gamma+mirror+panel-mapping, streaming seriale.
- **`Lavagna-Linux/minimalv2.py`** — Port per Raspberry Pi 5. Thread dedicato alla cattura webcam (producer/consumer), risoluzione 320x240, frame skip (MediaPipe ogni 2 frame), backend V4L2. Stessa logica di detect_hardware() con entrambe le modalita'.

### Arduino firmware

- **`arduino_video_only/arduino_video_only.ino`** — Firmware per ricezione video. Solo ricezione seriale, nessuna animazione in background. FastLED.show() chiamato solo dopo frame completo per non perdere byte seriali.
- **`test_avanzato/test_avanzato.ino`** — Firmware standalone con pattern animati (FastLED). Non usa il protocollo seriale video.

### Costanti chiave (duplicate in piu' file)

Le costanti Arduino sono ripetute identiche in `Lavagna.py`, `Lavagna-Linux/minimalv2.py`, `doom_ledwall.py`, e `test_arduino.py`. Se ne modifichi una, aggiorna tutte.

```
ARDUINO_BAUD = 500000
ARDUINO_PANEL_W = 8, ARDUINO_PANEL_H = 32
MAGIC_HEADER = b'\xFFLE'
GAMMA = 2.5
ARDUINO_SERPENTINE_X = True
ARDUINO_MIRROR_VERTICAL = True
```

**ATTENZIONE mirror orizzontale**: `Lavagna.py` e `minimalv2.py` hanno `ARDUINO_MIRROR_HORIZONTAL = False` perche' la webcam gia' flippa il frame (`cv2.flip(frame, 1)`). `doom_ledwall.py` e `test_arduino.py` hanno `True` perche' non usano la webcam.

### Controlli tastiera (Lavagna.py)

`1-9` colore | `+/-` brush size | `C` cancella | `S` salva PNG | `I` inverti (common anode) | `T` calibrazione | `F` fullscreen | `Q/ESC` esci
