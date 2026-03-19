"""
hand_tracker.py — Modulo di tracking mani per Lavagna LED Interattiva.

Versione Professionale: Usa MediaPipe HandLandmarker (Tasks API) con:
  - Filtro stabilizzatore (EMA - Exponential Moving Average) per azzerare il tremolio
  - Rilevamento avanzato dei gesti (Intenzionalità del Pinch)
  - Swipe tracking per la cancellazione anti-errore
"""

import os
import math
import time
from dataclasses import dataclass, field
from collections import deque

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    RunningMode,
)

# Indici dei landmark MediaPipe Hands (21 punti)
WRIST = 0
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP = 3
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_DIP = 11
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_DIP = 15
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_DIP = 19
PINKY_TIP = 20


@dataclass
class HandState:
    """Stato della mano rilevata in un singolo frame."""
    detected: bool = False
    drawing: bool = False
    fist_closed: bool = False
    precision_erasing: bool = False
    thumbs_down: bool = False   # Pollice in giù = cancella tutto
    canvas_x: int = -1
    canvas_y: int = -1
    raw_x: float = 0.0          # Posizione X normalizzata smorzata (0–1)
    raw_y: float = 0.0          # Posizione Y normalizzata smorzata (0–1)
    confidence: float = 0.0
    landmarks: list = field(default_factory=list)
    hand_label: str = "Unknown" # "Left" o "Right"


class HandTracker:
    """Tracker mano avanzato con stabilizzazione e riconoscimento gesti robusto."""

    # Soglia per il Pinch (percentuale della dimensione del palmo in 2D)
    PINCH_ACTIVATE_THRESHOLD = 0.18
    PINCH_DEACTIVATE_THRESHOLD = 0.35  # Isteresi molto ampia per non spezzare il tratto

    # Quanti frame il pinch "sopravvive" anche se le dita si allontanano per sbaglio
    # Questo previene micro-interruzioni del tratto se la webcam perde un frame
    DRAWING_GRACE_FRAMES = 3

    # Soglia per gesto cancella (velocità orizzontale molto alta)
    ERASE_SPEED_THRESHOLD = 1.0
    ERASE_HISTORY_FRAMES = 8

    # Eraser: quanti frame il gesto deve essere stabile per attivarsi
    ERASER_ACTIVATE_FRAMES = 3
    # Grace period: non attivare l'eraser se si stava disegnando meno di N frame fa
    ERASER_POST_DRAW_GRACE = 8

    # Thumbs Down: quanti frame il gesto deve essere stabile per attivarsi
    THUMBS_DOWN_ACTIVATE_FRAMES = 5

    # Smoothing (Filtro EMA: Alpha più basso = più fluido ma più lag)
    EMA_ALPHA = 0.35

    # Margini della zona attiva (percentuale, 0.0-0.5)
    # Permette di mappare solo la zona centrale della webcam ai LED
    ACTIVE_MARGIN_X = 0.10  # 10% margine a sinistra e destra
    ACTIVE_MARGIN_Y = 0.10  # 10% margine sopra e sotto

    MODEL_FILENAME = "hand_landmarker.task"

    def __init__(self, canvas_width: int, canvas_height: int,
                 min_detection_confidence: float = 0.6,
                 min_tracking_confidence: float = 0.5):
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height

        script_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(script_dir, self.MODEL_FILENAME)

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Modello MediaPipe non trovato: {model_path}")

        self._latest_result = None
        self._frame_timestamp_ms = 0

        def _result_callback(result, output_image, timestamp_ms):
            self._latest_result = result

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=RunningMode.LIVE_STREAM,
            num_hands=2,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_tracking_confidence,
            min_tracking_confidence=min_tracking_confidence,
            result_callback=_result_callback,
        )
        self.detector = HandLandmarker.create_from_options(options)

        # Stato interno per mano (storico) — chiave: "Left" o "Right"
        self._hand_histories = {}

    def _get_history(self, hand_label: str) -> dict:
        if hand_label not in self._hand_histories:
            self._hand_histories[hand_label] = {
                'was_drawing': False,
                'drawing_grace_counter': 0,
                'smoothed_pos': None,
                'last_fist_time': 0.0,
                'fist_confidence_counter': 0,
                'eraser_confidence_counter': 0,
                'was_erasing': False,
                'frames_since_drawing': 999,  # grande = non stava disegnando
                'prev_wrist_pos': None,  # Per calcolo velocità polso
                'thumbs_down_counter': 0,
                'last_thumbs_down_time': 0.0,
            }
        return self._hand_histories[hand_label]

    def _distance2d(self, p1, p2) -> float:
        """Distanza 2D tra due landmark normalizzati."""
        return math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)

    def _get_hand_size(self, landmarks) -> float:
        """Stima la dimensione della mano in 2D."""
        return self._distance2d(landmarks[WRIST], landmarks[MIDDLE_MCP])

    def _is_finger_extended(self, landmarks, tip_idx: int, pip_idx: int) -> bool:
        """Un dito è esteso se la punta è sensibilmente più lontana dal polso rispetto alla nocca centrale."""
        dist_tip = self._distance2d(landmarks[WRIST], landmarks[tip_idx])
        dist_pip = self._distance2d(landmarks[WRIST], landmarks[pip_idx])
        return dist_tip > dist_pip * 1.15

    def _detect_pinch(self, landmarks, hand_size: float, history: dict) -> bool:
        """Rilevamento Pinch con Isteresi in 2D."""
        thumb = landmarks[THUMB_TIP]
        index = landmarks[INDEX_TIP]
        
        dist = self._distance2d(thumb, index)
        normalized_dist = dist / max(hand_size, 0.001)

        if history['was_drawing']:
            # Per smettere di disegnare devi allontanare le dita più della soglia
            is_close = normalized_dist < self.PINCH_DEACTIVATE_THRESHOLD
            
            if is_close:
                history['drawing_grace_counter'] = self.DRAWING_GRACE_FRAMES
            else:
                history['drawing_grace_counter'] -= 1
                
            history['was_drawing'] = history['drawing_grace_counter'] > 0
        else:
            history['was_drawing'] = normalized_dist < self.PINCH_ACTIVATE_THRESHOLD
            if history['was_drawing']:
                history['drawing_grace_counter'] = self.DRAWING_GRACE_FRAMES

        return history['was_drawing']

    def _detect_middle_finger(self, landmarks) -> bool:
        """Rileva se c'è solo il dito medio alzato."""
        index_up = self._is_finger_extended(landmarks, INDEX_TIP, INDEX_PIP)
        middle_up = self._is_finger_extended(landmarks, MIDDLE_TIP, MIDDLE_PIP)
        ring_up = self._is_finger_extended(landmarks, RING_TIP, RING_PIP)
        pinky_up = self._is_finger_extended(landmarks, PINKY_TIP, PINKY_PIP)
        return middle_up and not index_up and not ring_up and not pinky_up

    def _detect_precision_eraser_raw(self, landmarks) -> bool:
        """Rileva se c'è SOLO il dito indice alzato (Cancellino di precisione).
        Ora richiede anche che il pollice sia piegato per evitare falsi positivi."""
        index_up = self._is_finger_extended(landmarks, INDEX_TIP, INDEX_PIP)
        middle_up = self._is_finger_extended(landmarks, MIDDLE_TIP, MIDDLE_PIP)
        ring_up = self._is_finger_extended(landmarks, RING_TIP, RING_PIP)
        pinky_up = self._is_finger_extended(landmarks, PINKY_TIP, PINKY_PIP)
        # Il pollice deve essere piegato (non esteso) per distinguersi da gesto "pistola"
        thumb_dist_tip = self._distance2d(landmarks[WRIST], landmarks[THUMB_TIP])
        thumb_dist_ip = self._distance2d(landmarks[WRIST], landmarks[THUMB_IP])
        thumb_curled = thumb_dist_tip < thumb_dist_ip * 1.3
        return index_up and not middle_up and not ring_up and not pinky_up and thumb_curled

    def _detect_precision_eraser(self, landmarks, history: dict) -> bool:
        """Eraser con isteresi multi-frame + grace period post-drawing."""
        raw = self._detect_precision_eraser_raw(landmarks)

        # Grace period: non attivare l'eraser se si stava disegnando poco fa
        if history['frames_since_drawing'] < self.ERASER_POST_DRAW_GRACE:
            history['eraser_confidence_counter'] = 0
            history['was_erasing'] = False
            return False

        if raw:
            history['eraser_confidence_counter'] += 1
        else:
            history['eraser_confidence_counter'] = max(0, history['eraser_confidence_counter'] - 1)

        if history['was_erasing']:
            # Per smettere di cancellare: contatore deve scendere a 0
            history['was_erasing'] = history['eraser_confidence_counter'] > 0
        else:
            # Per attivare: serve stabilità multi-frame
            history['was_erasing'] = history['eraser_confidence_counter'] >= self.ERASER_ACTIVATE_FRAMES

        return history['was_erasing']

    def _detect_thumbs_down(self, landmarks, history: dict) -> bool:
        """Rileva il gesto 'pollice in giù' per cancellare la lavagna.
        Requisiti: pollice esteso verso il basso, tutte le altre 4 dita piegate.
        Con isteresi multi-frame per evitare falsi positivi."""
        # 1. Il pollice deve puntare verso il basso: thumb_tip.y > wrist.y
        #    (nelle coordinate normalizzate, y cresce verso il basso)
        thumb_tip = landmarks[THUMB_TIP]
        wrist = landmarks[WRIST]
        thumb_points_down = thumb_tip.y > wrist.y + 0.05  # margine minimo

        # 2. Il pollice deve essere esteso (non piegato)
        thumb_extended = self._distance2d(wrist, thumb_tip) > self._distance2d(wrist, landmarks[THUMB_IP]) * 1.1

        # 3. Tutte le altre 4 dita devono essere piegate
        index_curled = not self._is_finger_extended(landmarks, INDEX_TIP, INDEX_PIP)
        middle_curled = not self._is_finger_extended(landmarks, MIDDLE_TIP, MIDDLE_PIP)
        ring_curled = not self._is_finger_extended(landmarks, RING_TIP, RING_PIP)
        pinky_curled = not self._is_finger_extended(landmarks, PINKY_TIP, PINKY_PIP)
        all_curled = index_curled and middle_curled and ring_curled and pinky_curled

        raw_thumbs_down = thumb_points_down and thumb_extended and all_curled

        # Isteresi multi-frame
        if raw_thumbs_down:
            history['thumbs_down_counter'] += 1
        else:
            history['thumbs_down_counter'] = max(0, history['thumbs_down_counter'] - 1)

        # Trigger solo se stabile per N frame e fuori cooldown (1.5 secondi)
        if (history['thumbs_down_counter'] >= self.THUMBS_DOWN_ACTIVATE_FRAMES
                and (time.time() - history['last_thumbs_down_time'] > 1.5)):
            history['last_thumbs_down_time'] = time.time()
            history['thumbs_down_counter'] = 0
            return True

        return False

    def _detect_fist(self, landmarks) -> bool:
        """Rileva se tutte e 4 le dita principali sono piegate verso il palmo in modo molto serrato (Pugno 100%)."""
        
        def is_tightly_curled(tip_idx, pip_idx, mcp_idx):
            dist_tip = self._distance2d(landmarks[WRIST], landmarks[tip_idx])
            dist_pip = self._distance2d(landmarks[WRIST], landmarks[pip_idx])
            dist_mcp = self._distance2d(landmarks[WRIST], landmarks[mcp_idx])
            
            # Un vero pugno ha la punta del dito ripiegata all'interno. Quindi la punta 
            # sarà molto più vicina al polso rispetto alla nocca media (PIP), ed a una distanza
            # paragonabile a quella della nocca base (MCP).
            return (dist_tip < dist_pip * 0.85) and (dist_tip < dist_mcp * 1.35)

        index_curled = is_tightly_curled(INDEX_TIP, INDEX_PIP, INDEX_MCP)
        middle_curled = is_tightly_curled(MIDDLE_TIP, MIDDLE_PIP, MIDDLE_MCP)
        ring_curled = is_tightly_curled(RING_TIP, RING_PIP, RING_MCP)
        pinky_curled = is_tightly_curled(PINKY_TIP, PINKY_PIP, PINKY_MCP)
        
        # Aggiungiamo il pollice piegato per una sicurezza assoluta al 99.9%
        thumb_tip = self._distance2d(landmarks[WRIST], landmarks[THUMB_TIP])
        thumb_ip = self._distance2d(landmarks[WRIST], landmarks[THUMB_IP])
        thumb_curled = thumb_tip < thumb_ip * 1.15

        return index_curled and middle_curled and ring_curled and pinky_curled and thumb_curled

    def _smooth_point(self, new_x: float, new_y: float, history: dict) -> tuple:
        """Filtro esponenziale per azzerare il tremolio (Jitter)."""
        if history['smoothed_pos'] is None:
            history['smoothed_pos'] = (new_x, new_y)
        else:
            sx = history['smoothed_pos'][0] + self.EMA_ALPHA * (new_x - history['smoothed_pos'][0])
            sy = history['smoothed_pos'][1] + self.EMA_ALPHA * (new_y - history['smoothed_pos'][1])
            history['smoothed_pos'] = (sx, sy)
        return history['smoothed_pos']

    def _to_canvas_coords(self, norm_x: float, norm_y: float) -> tuple:
        """Converte in coordinate pixel del canvas LED.
        Applica margini della zona attiva e compensazione.
        """
        # Rimappa da [margin, 1-margin] → [0, 1]
        mx = self.ACTIVE_MARGIN_X
        my = self.ACTIVE_MARGIN_Y
        remapped_x = (norm_x - mx) / (1.0 - 2.0 * mx)
        remapped_y = (norm_y - my) / (1.0 - 2.0 * my)

        # Clamp a [0, 1]
        remapped_x = max(0.0, min(1.0, remapped_x))
        remapped_y = max(0.0, min(1.0, remapped_y))

        cx = int(remapped_x * self.canvas_width)
        cy = int(remapped_y * self.canvas_height)

        cx = max(0, min(cx, self.canvas_width - 1))
        cy = max(0, min(cy, self.canvas_height - 1))

        return cx, cy

    def process_frame(self, frame_bgr) -> list[HandState]:
        # In MediaPipe i frames RGB servono per la detection
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        self._frame_timestamp_ms += 33
        try:
            self.detector.detect_async(mp_image, self._frame_timestamp_ms)
        except Exception:
            pass

        result = self._latest_result
        if result is None or not result.hand_landmarks:
            # Resetta le mani non più rilevate
            for h in self._hand_histories.values():
                h['smoothed_pos'] = None
                h['was_drawing'] = False
            return []

        hand_states = []
        # BUG-2 FIX: Traccia quali chiavi sono attive in questo frame
        active_keys = set()
        
        for i, landmarks in enumerate(result.hand_landmarks):
            state = HandState()
            
            # Identifica se mano Destra o Sinistra (per separare lo storico)
            hand_label = "Unknown"
            if result.handedness and len(result.handedness) > i:
                hand_label = result.handedness[i][0].category_name  # Es. "Left" o "Right"
                state.confidence = result.handedness[i][0].score
            
            # BUG-2 FIX: Usa solo il label della mano come chiave stabile.
            # Se MediaPipe restituisce due mani con lo stesso label (raro bug),
            # aggiungiamo un suffisso solo per la seconda occorrenza.
            hand_key = hand_label
            if hand_key in active_keys:
                hand_key = f"{hand_label}_dup"
            active_keys.add(hand_key)
            state.hand_label = hand_key
            
            history = self._get_history(hand_key)
            
            state.detected = True
            state.landmarks = [(lm.x, lm.y, lm.z) for lm in landmarks]

            hand_size = self._get_hand_size(landmarks)
            is_pinching = self._detect_pinch(landmarks, hand_size, history)
            # BUG-4 FIX: eraser con isteresi multi-frame
            is_precision_erase = self._detect_precision_eraser(landmarks, history)
            is_thumbs_down = self._detect_thumbs_down(landmarks, history)
            is_fist = self._detect_fist(landmarks)

            # Contatore multi-frame per il pugno chiuso (evita sfarfallii o glitch mentre disegni)
            if is_fist:
                history['fist_confidence_counter'] += 1
            else:
                # Diminuisci gradualmente in caso di perdita frame temporanea
                history['fist_confidence_counter'] = max(0, history['fist_confidence_counter'] - 1)

            # Trigger del cambio colore solo se il pugno è stabile per ~5 frame e fuori cooldown
            if history['fist_confidence_counter'] >= 5 and (time.time() - history['last_fist_time'] > 1.0):
                state.fist_closed = True
                history['last_fist_time'] = time.time()
                history['fist_confidence_counter'] = 0  # Resetta per limitare trigger multipli

            # Thumbs down → cancella tutto
            if is_thumbs_down:
                state.thumbs_down = True

            if is_pinching:
                state.drawing = True
                history['frames_since_drawing'] = 0  # BUG-4: traccia quando si stava disegnando
                thumb, index = landmarks[THUMB_TIP], landmarks[INDEX_TIP]
                raw_x, raw_y = (thumb.x + index.x) / 2.0, (thumb.y + index.y) / 2.0
                sm_x, sm_y = self._smooth_point(raw_x, raw_y, history)
                state.raw_x, state.raw_y = sm_x, sm_y
                state.canvas_x, state.canvas_y = self._to_canvas_coords(sm_x, sm_y)
            elif is_precision_erase:
                state.precision_erasing = True
                idx_tip = landmarks[INDEX_TIP]
                sm_x, sm_y = self._smooth_point(idx_tip.x, idx_tip.y, history)
                state.raw_x, state.raw_y = sm_x, sm_y
                state.canvas_x, state.canvas_y = self._to_canvas_coords(sm_x, sm_y)
            else:
                history['smoothed_pos'] = None
                history['frames_since_drawing'] += 1  # BUG-4: incrementa contatore

            # Salva posizione polso per calcoli velocità (clap)
            wrist = landmarks[WRIST]
            history['prev_wrist_pos'] = (wrist.x, wrist.y)

            hand_states.append(state)

        # BUG-2 FIX: Pulisci history di mani non più rilevate
        stale_keys = [k for k in self._hand_histories if k not in active_keys]
        for k in stale_keys:
            h = self._hand_histories[k]
            h['smoothed_pos'] = None
            h['was_drawing'] = False
            h['was_erasing'] = False
            h['eraser_confidence_counter'] = 0
            # Non eliminiamo la history, la resettiamo per evitare re-allocazioni

        return hand_states

    def draw_overlay(self, frame_bgr, state: HandState):
        """Disegna uno scheletro sci-fi professionale della mano."""
        h, w = frame_bgr.shape[:2]

        if not state.detected or not state.landmarks:
            cv2.putText(frame_bgr, "Mostra la mano", (10, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 2)
            cv2.circle(frame_bgr, (w//2, h//2), 30, (50, 50, 50), 2)
            return

        # Colori sci-fi (Verde per tracking normale, Azzurro/Rosso per dita)
        base_color = (0, 255, 0) if not state.drawing else (0, 100, 255) # Arancione se disegna
        joint_color = (255, 200, 0) if not state.drawing else (0, 200, 255) # Azzurro se disegna
        
        connections = [
            (WRIST, THUMB_CMC), (THUMB_CMC, THUMB_MCP), (THUMB_MCP, THUMB_IP), (THUMB_IP, THUMB_TIP),
            (WRIST, INDEX_MCP), (INDEX_MCP, INDEX_PIP), (INDEX_PIP, INDEX_DIP), (INDEX_DIP, INDEX_TIP),
            (INDEX_MCP, MIDDLE_MCP), (MIDDLE_MCP, MIDDLE_PIP), (MIDDLE_PIP, MIDDLE_DIP), (MIDDLE_DIP, MIDDLE_TIP),
            (MIDDLE_MCP, RING_MCP), (RING_MCP, RING_PIP), (RING_PIP, RING_DIP), (RING_DIP, RING_TIP),
            (RING_MCP, PINKY_MCP), (PINKY_MCP, PINKY_PIP), (PINKY_PIP, PINKY_DIP), (PINKY_DIP, PINKY_TIP),
            (WRIST, PINKY_MCP)
        ]

        # 1. Disegna le connessioni
        for (i, j) in connections:
            p1 = state.landmarks[i]
            p2 = state.landmarks[j]
            px1, py1 = int(p1[0] * w), int(p1[1] * h)
            px2, py2 = int(p2[0] * w), int(p2[1] * h)
            thickness = 3 if state.drawing and (i in (THUMB_TIP, THUMB_IP, INDEX_TIP, INDEX_DIP) or j in (THUMB_TIP, THUMB_IP, INDEX_TIP, INDEX_DIP)) else 1
            cv2.line(frame_bgr, (px1, py1), (px2, py2), base_color, thickness)

        # 2. Disegna i nodi (joints)
        for i, lm in enumerate(state.landmarks):
            px, py = int(lm[0] * w), int(lm[1] * h)
            radius = 4 if i in (THUMB_TIP, INDEX_TIP) else 2
            cv2.circle(frame_bgr, (px, py), radius, joint_color, -1)

        # 3. Effetto Pinch Ecoscandaglio
        if state.drawing:
            # Mostra la posizione stabilizzata
            sm_x = int(state.raw_x * w)
            sm_y = int(state.raw_y * h)
            cv2.circle(frame_bgr, (sm_x, sm_y), 15, (0, 0, 255), 2)
            cv2.circle(frame_bgr, (sm_x, sm_y), 3, (0, 0, 255), -1)
            cv2.putText(frame_bgr, f"REC [{state.canvas_x},{state.canvas_y}]", 
                        (sm_x + 20, sm_y - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            
        # Feedback visivo del Pugno Chiuso (Cambio Colore)
        history = self._get_history(state.hand_label)
        if time.time() - history['last_fist_time'] < 0.5:
            cv2.putText(frame_bgr, "COLOR CHANGE!", 
                        (w//2 - 120, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 0), 3)
            
        elif state.precision_erasing:
            sm_x = int(state.raw_x * w)
            sm_y = int(state.raw_y * h)
            cv2.circle(frame_bgr, (sm_x, sm_y), 15, (255, 255, 255), 2)
            cv2.putText(frame_bgr, "ERASER", 
                        (sm_x + 20, sm_y - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

    def release(self):
        self.detector.close()
