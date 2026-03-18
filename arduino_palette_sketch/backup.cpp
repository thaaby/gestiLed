#include <FastLED.h>

// --- CONFIGURAZIONE MATRICE ---
#define LED_PIN     6
#define NUM_LEDS    1024    // 4x Matrice 8x32
#define BRIGHTNESS  40      // Sicurezza alimentazione
#define LED_TYPE    WS2812B
#define COLOR_ORDER GRB
#define MAX_PALETTE 49      // Max colori (7x7 griglia)

CRGB leds[NUM_LEDS];

// --- CALIBRAZIONE COLORE LOEFL1RGB/6024 (CMN Group) ---
const float RED_FACTOR   = 1.00; 
const float GREEN_FACTOR = 0.75; 
const float BLUE_FACTOR  = 0.90;

// === COLORI ===
bool paletteMode = false;
int paletteSize = 0;
int paletteR[MAX_PALETTE];
int paletteG[MAX_PALETTE];
int paletteB[MAX_PALETTE];

// Vecchia palette (per crossfade)
int oldPaletteR[MAX_PALETTE];
int oldPaletteG[MAX_PALETTE];
int oldPaletteB[MAX_PALETTE];
int oldPaletteSize = 0;
bool oldPaletteMode = false;

int currentR = 0;
int currentG = 0;
int currentB = 0;

// --- ANIMAZIONE FILL/SWEEP ---
float fillPos = 0.0;           // Posizione corrente del cursore (0.0 -> NUM_LEDS)
bool filling = false;          // Animazione in corso?
#define FILL_SPEED  16.0       // LED per frame (più alto = più veloce, 16 = ~130ms per 256 LED)
#define FADE_WIDTH  12         // Larghezza della sfumatura sulla "testa" dell'onda

// Flag: nuovi dati da mostrare
bool needsUpdate = false;

// Buffer seriale
char inputBuffer[512];
int bufferPos = 0;

void setup() {
  Serial.begin(500000);
  Serial.setTimeout(100);  // Timeout per ricevere frame video completi
  pinMode(13, OUTPUT);
  
  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS).setCorrection(TypicalLEDStrip);
  FastLED.setBrightness(BRIGHTNESS);
  FastLED.clear();
  FastLED.show();
}

// Converte 2 caratteri HEX in byte
int hexToByte(char hi, char lo) {
  int val = 0;
  if (hi >= '0' && hi <= '9') val = (hi - '0') << 4;
  else if (hi >= 'A' && hi <= 'F') val = (hi - 'A' + 10) << 4;
  else if (hi >= 'a' && hi <= 'f') val = (hi - 'a' + 10) << 4;
  if (lo >= '0' && lo <= '9') val |= (lo - '0');
  else if (lo >= 'A' && lo <= 'F') val |= (lo - 'A' + 10);
  else if (lo >= 'a' && lo <= 'f') val |= (lo - 'a' + 10);
  return val;
}

// Colore target per un dato LED in base alla palette corrente
CRGB getTargetColor(int ledIdx) {
  if (paletteMode && paletteSize > 0) {
    int ledsPerBlock = NUM_LEDS / paletteSize;
    int idx = ledIdx / ledsPerBlock;
    if (idx >= paletteSize) idx = paletteSize - 1;
    return CRGB(paletteR[idx], paletteG[idx], paletteB[idx]);
  }
  return CRGB(currentR, currentG, currentB);
}

// Colore della VECCHIA palette per un dato LED (per crossfade)
CRGB getOldColor(int ledIdx) {
  if (oldPaletteMode && oldPaletteSize > 0) {
    int ledsPerBlock = NUM_LEDS / oldPaletteSize;
    int idx = ledIdx / ledsPerBlock;
    if (idx >= oldPaletteSize) idx = oldPaletteSize - 1;
    return CRGB(oldPaletteR[idx], oldPaletteG[idx], oldPaletteB[idx]);
  }
  return CRGB(0, 0, 0);
}

// Parse "P:N:RRGGBB:RRGGBB:..."
void parsePalette(char* data) {
  char* ptr = data + 2;
  int n = atoi(ptr);
  if (n < 1 || n > MAX_PALETTE) return;
  
  ptr = strchr(ptr, ':');
  if (!ptr) return;
  ptr++;
  
  // Leggi i nuovi colori in buffer temporanei per confronto
  int newR[MAX_PALETTE], newG[MAX_PALETTE], newB[MAX_PALETTE];
  for (int i = 0; i < n; i++) {
    if (strlen(ptr) < 6) return;
    newR[i] = (int)(hexToByte(ptr[0], ptr[1]) * RED_FACTOR);
    newG[i] = (int)(hexToByte(ptr[2], ptr[3]) * GREEN_FACTOR);
    newB[i] = (int)(hexToByte(ptr[4], ptr[5]) * BLUE_FACTOR);
    ptr += 6;
    if (*ptr == ':') ptr++;
  }
  
  // Controlla se la palette è cambiata (evita di resettare il fill inutilmente)
  bool changed = (n != paletteSize) || (!paletteMode);
  if (!changed) {
    for (int i = 0; i < n; i++) {
      if (abs(newR[i] - paletteR[i]) > 5 || abs(newG[i] - paletteG[i]) > 5 || abs(newB[i] - paletteB[i]) > 5) {
        changed = true;
        break;
      }
    }
  }
  
  if (!changed) return;  // Stessi colori: non fare nulla
  
  // Salva la palette corrente come "vecchia" per il crossfade
  oldPaletteSize = paletteSize;
  oldPaletteMode = paletteMode;
  for (int i = 0; i < paletteSize; i++) {
    oldPaletteR[i] = paletteR[i];
    oldPaletteG[i] = paletteG[i];
    oldPaletteB[i] = paletteB[i];
  }
  
  // Applica nuovi colori
  for (int i = 0; i < n; i++) {
    paletteR[i] = newR[i];
    paletteG[i] = newG[i];
    paletteB[i] = newB[i];
  }
  
  paletteSize = n;
  paletteMode = true;
  
  // Riavvia il fill da sinistra
  fillPos = 0.0;
  filling = true;
}

// Parse "R,G,B"
void parseSingle(char* data) {
  int r = 0, g = 0, b = 0;
  if (sscanf(data, "%d,%d,%d", &r, &g, &b) == 3) {
    // Salva vecchio
    oldPaletteSize = paletteSize;
    oldPaletteMode = paletteMode;
    for (int i = 0; i < paletteSize; i++) {
      oldPaletteR[i] = paletteR[i];
      oldPaletteG[i] = paletteG[i];
      oldPaletteB[i] = paletteB[i];
    }
    
    currentR = (int)(constrain(r, 0, 255) * RED_FACTOR);
    currentG = (int)(constrain(g, 0, 255) * GREEN_FACTOR);
    currentB = (int)(constrain(b, 0, 255) * BLUE_FACTOR);
    paletteMode = false;
    
    fillPos = 0.0;
    filling = true;
  }
}

void loop() {
// Flag temporaneo per sapere se il frame è pronto
  bool videoFrameReady = false;

  // 0. MODALITÀ VIDEO: cerca il byte di sincronizzazione 'V'
  if (Serial.available() > 0 && Serial.peek() == 'V') {
    Serial.read(); // Consuma 'V'
    
    // Attendi i dati RGB del frame
    int bytesRead = Serial.readBytes((char*)leds, NUM_LEDS * 3);
    
    if (bytesRead == NUM_LEDS * 3) {
      digitalWrite(13, HIGH); // LED acceso: frame video OK
      FastLED.show();
    } else {
      digitalWrite(13, LOW);  // LED spento: frame incompleto o perso
      // Frame corrotto o frammentato, svuota il buffer per risincronizzare
      while(Serial.available() > 0) Serial.read();
    }
    return; // Completato o ignorato il frame video, ricomincia il loop
  }
  
  // 1. LEGGI seriale (modalità palette/colore singolo)
  while (Serial.available() > 0) {
    char c = Serial.read();
    
    if (c == '\n' || c == '\r') {
      if (bufferPos > 0) {
        inputBuffer[bufferPos] = '\0';
        digitalWrite(13, HIGH);
        
        if (inputBuffer[0] == 'P' && inputBuffer[1] == ':') {
          parsePalette(inputBuffer);
        } else {
          parseSingle(inputBuffer);
        }
      }
      bufferPos = 0;
    } else if (bufferPos < 510) {
      inputBuffer[bufferPos++] = c;
    }
  }
  
  digitalWrite(13, LOW);
  
  // 2. EFFETTO FILL: riempimento fluido da sinistra a destra
  if (filling) {
    int headPos = (int)fillPos;  // La "testa" del riempimento
    
    for (int i = 0; i < NUM_LEDS; i++) {
      CRGB target = getTargetColor(i);
      
      if (i < headPos - FADE_WIDTH) {
        // Zona GIÀ RIEMPITA: colore nuovo pieno
        leds[i] = target;
        
      } else if (i < headPos) {
        // ZONA DI BLEND (la sfumatura morbida sulla testa)
        // Più vicino alla testa = più vicino al vecchio colore
        float blend = (float)(headPos - i) / (float)FADE_WIDTH;
        // blend: 1.0 = completamente nuovo, 0.0 = completamente vecchio
        CRGB old = getOldColor(i);
        leds[i] = CRGB(
          old.r + (int)((float)(target.r - old.r) * blend),
          old.g + (int)((float)(target.g - old.g) * blend),
          old.b + (int)((float)(target.b - old.b) * blend)
        );
        
      } else {
        // ZONA NON ANCORA RAGGIUNTA: mantieni il vecchio colore
        leds[i] = getOldColor(i);
      }
    }
    
    // Avanza il cursore
    fillPos += FILL_SPEED;
    
    // Fine animazione
    if (fillPos >= NUM_LEDS + FADE_WIDTH) {
      filling = false;
      // Imposta tutti al colore finale
      for (int i = 0; i < NUM_LEDS; i++) {
        leds[i] = getTargetColor(i);
      }
    }
  }
  
  FastLED.show();
  delay(8); // ~120 FPS per animazione fluida
}
