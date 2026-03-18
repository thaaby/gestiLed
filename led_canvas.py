"""
led_canvas.py — Canvas virtuale per la Lavagna LED Interattiva.

Mantiene lo stato dei pixel LED come array numpy.
Supporta disegno, cancellazione, e interpolazione lineare (Bresenham).
"""

import numpy as np
import cv2
from datetime import datetime


# Palette colori predefinita — tasto 1-9
COLOR_PALETTE = [
    (255, 255, 255),  # 1 — Bianco
    (255, 0, 0),      # 2 — Rosso
    (0, 255, 0),      # 3 — Verde
    (0, 100, 255),    # 4 — Blu
    (255, 255, 0),    # 5 — Giallo
    (255, 0, 255),    # 6 — Magenta
    (0, 255, 255),    # 7 — Ciano
    (255, 128, 0),    # 8 — Arancione
    (255, 105, 180),  # 9 — Rosa
]

COLOR_NAMES_IT = [
    "Bianco", "Rosso", "Verde", "Blu", "Giallo",
    "Magenta", "Ciano", "Arancione", "Rosa",
]


class LEDCanvas:
    """Canvas virtuale che rappresenta lo stato dei pixel LED."""

    def __init__(self, width: int, height: int):
        """
        Args:
            width: Larghezza del canvas (numero di colonne LED)
            height: Altezza del canvas (numero di righe LED)
        """
        self.width = width
        self.height = height

        # Canvas: array (height, width, 3) uint8, inizializzato a nero (LED spenti)
        self.pixels = np.zeros((height, width, 3), dtype=np.uint8)

        # Colore corrente (indice nella palette)
        self._color_index = 0
        self.current_color = COLOR_PALETTE[0]

        # Dimensione pennello (1 = singolo pixel, 2 = 2x2, 3 = 3x3)
        self.brush_size = 1

        # Ultima posizione disegnata (per interpolazione Bresenham)
        self._last_x: int = -1
        self._last_y: int = -1
        self._was_drawing: bool = False

    def set_color_by_index(self, index: int):
        """Imposta il colore corrente dalla palette (indice 0-8).

        Args:
            index: Indice nella palette (0-8, corrispondente ai tasti 1-9)
        """
        if 0 <= index < len(COLOR_PALETTE):
            self._color_index = index
            self.current_color = COLOR_PALETTE[index]

    def get_color_name(self) -> str:
        """Restituisce il nome italiano del colore corrente."""
        return COLOR_NAMES_IT[self._color_index]

    def get_color_index(self) -> int:
        """Restituisce l'indice del colore corrente."""
        return self._color_index

    def set_brush_size(self, size: int):
        """Imposta la dimensione del pennello.

        Args:
            size: Dimensione (1, 2 o 3)
        """
        self.brush_size = max(1, min(3, size))

    def _paint_pixel(self, x: int, y: int):
        """Colora un pixel (o un blocco, in base al brush_size).

        Args:
            x: Coordinata X
            y: Coordinata Y
        """
        if self.brush_size == 1:
            if 0 <= x < self.width and 0 <= y < self.height:
                self.pixels[y, x] = self.current_color
        else:
            half = self.brush_size // 2
            for dy in range(-half, half + 1):
                for dx in range(-half, half + 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.width and 0 <= ny < self.height:
                        self.pixels[ny, nx] = self.current_color

    def draw_easter_egg(self, cx: int, cy: int):
        """Disegna una forma interattiva speciale (easter egg) centrata in (cx, cy)."""
        color = (int(self.current_color[0]), int(self.current_color[1]), int(self.current_color[2]))
        # Asta (colonna verticale al centro)
        cv2.rectangle(self.pixels, (cx - 1, cy - 3), (cx + 1, cy + 4), color, -1)
        # Basi (due cerchi/quadrati ai lati in basso)
        cv2.circle(self.pixels, (cx - 2, cy + 4), 2, color, -1)
        cv2.circle(self.pixels, (cx + 2, cy + 4), 2, color, -1)
        # Punta arrotondata in alto
        cv2.circle(self.pixels, (cx, cy - 3), 2, color, -1)
        
        # Resetta l'ultimo punto disegnato così non unisce i tratti via bresenham
        self._was_drawing = False
        self._last_x = -1
        self._last_y = -1

    def _bresenham_line(self, x0: int, y0: int, x1: int, y1: int):
        """Algoritmo di Bresenham per tracciare una linea tra due punti.
        Dipinge ogni pixel lungo la linea.
        """
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            self._paint_pixel(x0, y0)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def draw_at(self, x: int, y: int, is_drawing: bool):
        """Disegna sulla posizione indicata, con interpolazione.

        Chiamato ogni frame. Se il frame precedente era anch'esso in disegno,
        interpola una linea tra le due posizioni per evitare tratti spezzati.

        Args:
            x: Coordinata X sul canvas
            y: Coordinata Y sul canvas
            is_drawing: True se il gesto di disegno è attivo
        """
        if not is_drawing:
            # Il dito non sta disegnando — reset stato
            self._was_drawing = False
            self._last_x = -1
            self._last_y = -1
            return

        if self._was_drawing and self._last_x >= 0 and self._last_y >= 0:
            # Interpola una linea dall'ultima posizione a quella nuova
            self._bresenham_line(self._last_x, self._last_y, x, y)
        else:
            # Primo punto di un nuovo tratto
            self._paint_pixel(x, y)

        self._last_x = x
        self._last_y = y
        self._was_drawing = True

    def clear(self):
        """Cancella l'intero canvas (tutti i LED spenti)."""
        self.pixels[:] = 0
        self._was_drawing = False
        self._last_x = -1
        self._last_y = -1

    def get_frame_rgb(self) -> np.ndarray:
        """Restituisce il canvas come array numpy RGB (height, width, 3).

        Questo array è pronto per essere processato (gamma) e inviato ai LED.
        """
        return self.pixels.copy()

    def get_preview(self, scale: int = 15, cursor_x: int = -1, cursor_y: int = -1) -> np.ndarray:
        """Restituisce un'anteprima ingrandita del canvas per la finestra OpenCV.

        Usa INTER_NEAREST per mantenere i pixel nitidi e rispetta le proporzioni
        esatte della rete di LED. Disegna anche un reticolo di tracking.

        Args:
            scale: Moltiplicatore di ingrandimento (pixel reali per ogni LED)
            cursor_x: Coordinata X del tracking per disegnare il mirino
            cursor_y: Coordinata Y del tracking per disegnare il mirino

        Returns:
            Array BGR per OpenCV
        """
        # RGB → BGR per OpenCV
        bgr = cv2.cvtColor(self.pixels, cv2.COLOR_RGB2BGR)

        preview_width = self.width * scale
        preview_height = self.height * scale

        # Scala con nearest neighbor (pixel art)
        preview = cv2.resize(bgr, (preview_width, preview_height),
                             interpolation=cv2.INTER_NEAREST)

        # Disegna griglia sottile (che simula lo stacco tra i LED fisici)
        if scale >= 4:
            color_grid = (40, 40, 40)
            for col in range(1, self.width):
                x = col * scale
                cv2.line(preview, (x, 0), (x, preview_height), color_grid, 1)
            for row in range(1, self.height):
                y = row * scale
                cv2.line(preview, (0, y), (preview_width, y), color_grid, 1)

        # Disegna il reticolo/mirino di tracking e l'ingombro del pennello
        if 0 <= cursor_x < self.width and 0 <= cursor_y < self.height:
            half = self.brush_size // 2
            # Bordo del pennello
            for dy in range(-half, half + 1):
                for dx in range(-half, half + 1):
                    nx = cursor_x + dx
                    ny = cursor_y + dy
                    if 0 <= nx < self.width and 0 <= ny < self.height:
                        px = nx * scale
                        py = ny * scale
                        cv2.rectangle(preview, (px, py), (px + scale - 1, py + scale - 1), (200, 255, 200), 1)
            
            # Mirino a croce centrale
            cx_px = cursor_x * scale + scale // 2
            cy_px = cursor_y * scale + scale // 2
            cross_len = scale
            cv2.line(preview, (cx_px - cross_len, cy_px), (cx_px + cross_len, cy_px), (0, 0, 255), 2)
            cv2.line(preview, (cx_px, cy_px - cross_len), (cx_px, cy_px + cross_len), (0, 0, 255), 2)

        return preview

    def save_as_png(self, filename: str = None) -> str:
        """Salva il canvas come immagine PNG.

        Args:
            filename: Nome file opzionale. Se None, genera un timestamp.

        Returns:
            Il nome del file salvato.
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"lavagna_{timestamp}.png"

        # Salva in alta risoluzione (scala x10)
        scale = 10
        bgr = cv2.cvtColor(self.pixels, cv2.COLOR_RGB2BGR)
        big = cv2.resize(bgr, (self.width * scale, self.height * scale),
                         interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(filename, big)
        return filename

    def is_empty(self) -> bool:
        """Controlla se il canvas è completamente vuoto."""
        return not np.any(self.pixels)
