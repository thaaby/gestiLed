# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Lavagna LED Interattiva** — An interactive LED drawing system using a 32x32 WS2812B LED matrix (4 panels of 8x32) controlled by an Arduino. Users draw on the matrix via hand gestures captured by webcam (MediaPipe), or stream a game window (DOOM) directly to the LEDs.

## Setup

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

The `hand_landmarker.task` MediaPipe model file must be present in the project root (already committed). `HandTracker` will raise `FileNotFoundError` if it's missing.

## Running

```bash
# Interactive drawing mode (hand gestures → LED matrix)
python3 <main_entry>.py

# Stream DOOM window to LED matrix
python3 doom_ledwall.py
```

`doom_ledwall.py` uses AppleScript (`osascript`) to detect the frontmost window on macOS — macOS only. It shows a countdown for the user to click the DOOM window, then streams it at ~32x32 resolution over serial.

## Arduino

- Firmware: `test_avanzato/test_avanzato.ino` — standalone animation patterns (FastLED, no serial video protocol)
- For video streaming, a different firmware (`arduino_video_only.ino`, not in this repo) must be flashed
- Serial baud: **500000**
- Serial port: auto-detected (`/dev/ttyUSB*`, `/dev/ttyACM*`, `/dev/cu.usbmodem*`, `/dev/cu.usbserial*`)

## Architecture

### Serial Protocol (Python → Arduino)
Every frame is sent as: `MAGIC_HEADER (0xFF 0x4C 0x45)` + 3072 bytes of RGB pixel data.
Arduino responds with `'K'` (ACK) per frame. Python uses non-blocking send with a 0.5s ACK timeout fallback.

### Panel Mapping (`map_frame_to_leds`)
The 32x32 frame is split into 4 panels of 8×32. Panel logical order (`ARDUINO_PANEL_ORDER = [3,2,1,0]`) maps panel index to physical X-position. Each panel uses serpentine/snake wiring (`ARDUINO_SERPENTINE_X = True`: odd rows are reversed). Horizontal mirror and gamma correction (γ=2.5) are applied before sending.

### Module Roles
- **`led_canvas.py` (`LEDCanvas`)** — Owns the pixel state as a NumPy array `(height, width, 3)`. Handles Bresenham line interpolation between frames, multi-hand drawing with per-hand state, brush sizes 1–3, and PNG export.
- **`hand_tracker.py` (`HandTracker`)** — Wraps MediaPipe HandLandmarker (LIVE_STREAM async mode). Detects gestures with multi-frame hysteresis:
  - **Pinch** (thumb+index): draw
  - **Index only + thumb curled**: precision eraser
  - **Peace sign** (V): cycle color
  - **Thumbs down**: clear canvas
  - EMA smoothing (`α=0.35`) reduces jitter. Active margin (10% each side) clips the usable webcam area.
- **`audio_synth.py` (`AudioSynth`)** — Pygame-based synth that maps canvas Y-coordinate to pentatonic scale notes (3 octaves) and X-coordinate to stereo panning.
- **`doom_ledwall.py`** — Standalone script; captures a macOS window via `mss`, crops to 4:3, resizes to 32×32, applies the same gamma+mirror+panel-mapping pipeline, and streams via serial.

### Key Constants (shared across files)
- Matrix: 32×32, panels: 4×(8×32)
- `ARDUINO_PANEL_ORDER = [3, 2, 1, 0]` — physical panel X positions
- `MAGIC_HEADER = b'\xFFLE'`
- `GAMMA = 2.5`
- `ARDUINO_MIRROR_HORIZONTAL = True`
