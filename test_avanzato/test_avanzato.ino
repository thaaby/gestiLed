/*
 * TEST AVANZATO - Matrice LED 32x32 WS2812B
 * ==========================================
 * Comandi seriale (invia un carattere):
 *   '0' = Auto (cambia pattern ogni 8s)
 *   '1' = Rainbow Wave
 *   '2' = Color Wipe
 *   '3' = Fire Effect
 *   '4' = Matrix Rain (verde)
 *   '5' = Twinkle Stars
 *   '6' = Bouncing Plasma
 *   '7' = Color Chase
 *   '8' = Palette Cycle
 *
 * Oppure lascia in AUTO e osserva tutti i pattern.
 */

#include <FastLED.h>

// --- CONFIGURAZIONE ---
#define LED_PIN     6
#define NUM_LEDS    1024
#define MATRIX_W    32
#define MATRIX_H    32
#define BRIGHTNESS  35        // SICURO: mai alzare sopra 60 senza alimentatore dedicato
#define LED_TYPE    WS2812B
#define COLOR_ORDER GRB

CRGB leds[NUM_LEDS];

// --- STATO ---
int currentPattern = 0;   // 0=auto
unsigned long patternStart = 0;
#define AUTO_INTERVAL 8000  // ms per pattern in modalità auto

// Mapping XY per matrice serpentina (snake/zigzag wiring)
// Cambia serpentina a seconda del tuo cablaggio reale!
uint16_t XY(uint8_t x, uint8_t y) {
  if (y & 1) {
    // Righe dispari: da destra a sinistra
    return (y + 1) * MATRIX_W - 1 - x;
  } else {
    // Righe pari: da sinistra a destra
    return y * MATRIX_W + x;
  }
}

// =====================
// PATTERN 1: RAINBOW WAVE
// =====================
void patternRainbowWave() {
  static uint8_t hueOffset = 0;
  for (int y = 0; y < MATRIX_H; y++) {
    for (int x = 0; x < MATRIX_W; x++) {
      uint8_t hue = hueOffset + x * 8 + y * 4;
      leds[XY(x, y)] = CHSV(hue, 255, 220);
    }
  }
  hueOffset += 2;
  FastLED.show();
  delay(18);
}

// =====================
// PATTERN 2: COLOR WIPE
// =====================
void patternColorWipe() {
  static int pos = 0;
  static uint8_t hue = 0;
  static bool forward = true;

  CRGB color = CHSV(hue, 255, 220);

  if (forward) {
    leds[pos] = color;
  } else {
    leds[pos] = CRGB::Black;
  }

  pos += forward ? 1 : -1;

  if (pos >= NUM_LEDS) {
    pos = NUM_LEDS - 1;
    forward = false;
    hue += 40;
  } else if (pos < 0) {
    pos = 0;
    forward = true;
  }

  FastLED.show();
  delay(1);
}

// =====================
// PATTERN 3: FIRE EFFECT
// =====================
#define FIRE_COOLING  55
#define FIRE_SPARKING 120

byte fireHeat[MATRIX_W][MATRIX_H];

void patternFire() {
  for (int x = 0; x < MATRIX_W; x++) {
    // Step 1: Raffredda ogni cella
    for (int y = 0; y < MATRIX_H; y++) {
      int cool = random(0, ((FIRE_COOLING * 10) / MATRIX_H) + 2);
      fireHeat[x][y] = max(0, (int)fireHeat[x][y] - cool);
    }

    // Step 2: Calore sale dal basso
    for (int y = MATRIX_H - 1; y >= 2; y--) {
      fireHeat[x][y] = (fireHeat[x][y-1] + fireHeat[x][y-2] + fireHeat[x][y-2]) / 3;
    }

    // Step 3: Scintille casuali in basso
    if (random(255) < FIRE_SPARKING) {
      int sparky = random(3);
      fireHeat[x][sparky] = min(255, (int)fireHeat[x][sparky] + random(160, 255));
    }

    // Step 4: Converti calore in colore
    for (int y = 0; y < MATRIX_H; y++) {
      byte heat = fireHeat[x][MATRIX_H - 1 - y]; // Fuoco sale dal basso
      CRGB col;
      if (heat < 85) {
        col = CRGB(heat * 3, 0, 0);
      } else if (heat < 170) {
        col = CRGB(255, (heat - 85) * 3, 0);
      } else {
        col = CRGB(255, 255, (heat - 170) * 3);
      }
      leds[XY(x, y)] = col;
    }
  }

  FastLED.show();
  delay(25);
}

// =====================
// PATTERN 4: MATRIX RAIN
// =====================
#define TRAIL_LENGTH 8

struct Drop {
  int x;
  float y;
  float speed;
  bool active;
};

#define NUM_DROPS 18
Drop drops[NUM_DROPS];

void initMatrixRain() {
  for (int i = 0; i < NUM_DROPS; i++) {
    drops[i].x = random(MATRIX_W);
    drops[i].y = random(-MATRIX_H, 0);
    drops[i].speed = 0.3f + random(100) / 100.0f * 0.5f;
    drops[i].active = true;
  }
}

void patternMatrixRain() {
  // Dissolvenza lenta
  for (int i = 0; i < NUM_LEDS; i++) {
    leds[i].g = leds[i].g > 25 ? leds[i].g - 25 : 0;
    leds[i].r = 0;
    leds[i].b = 0;
  }

  for (int i = 0; i < NUM_DROPS; i++) {
    drops[i].y += drops[i].speed;

    int head = (int)drops[i].y;

    // Testa luminosa
    if (head >= 0 && head < MATRIX_H) {
      leds[XY(drops[i].x, head)] = CRGB(50, 255, 50);
    }

    // Reset
    if (drops[i].y > MATRIX_H + TRAIL_LENGTH) {
      drops[i].x = random(MATRIX_W);
      drops[i].y = random(-8, 0);
      drops[i].speed = 0.3f + random(100) / 100.0f * 0.5f;
    }
  }

  FastLED.show();
  delay(40);
}

// =====================
// PATTERN 5: TWINKLE STARS
// =====================
void patternTwinkle() {
  // Dissolvenza globale lenta
  fadeToBlackBy(leds, NUM_LEDS, 20);

  // Aggiungi stelle casuali
  int numNew = random(3, 8);
  for (int i = 0; i < numNew; i++) {
    int idx = random(NUM_LEDS);
    uint8_t hue = random(256);
    leds[idx] = CHSV(hue, 200, 220);
  }

  FastLED.show();
  delay(30);
}

// =====================
// PATTERN 6: BOUNCING PLASMA
// =====================
void patternPlasma() {
  static uint32_t t = 0;
  t += 3;

  for (int y = 0; y < MATRIX_H; y++) {
    for (int x = 0; x < MATRIX_W; x++) {
      int val = sin8((x * 20) + t) +
                sin8((y * 20) + t) +
                sin8(((x + y) * 12) + t / 2) +
                sin8(sqrt((x*x + y*y) * 2) + t / 3);

      leds[XY(x, y)] = CHSV(val / 2, 255, 200);
    }
  }

  FastLED.show();
  delay(20);
}

// =====================
// PATTERN 7: COLOR CHASE
// =====================
void patternColorChase() {
  static int pos = 0;
  static uint8_t hue = 0;

  fadeToBlackBy(leds, NUM_LEDS, 40);

  // 3 punti equidistanti che girano
  for (int i = 0; i < 3; i++) {
    int p = (pos + i * (NUM_LEDS / 3)) % NUM_LEDS;
    leds[p] = CHSV(hue + i * 80, 255, 255);
    if (p > 0)      leds[p - 1] = CHSV(hue + i * 80, 255, 160);
    if (p < NUM_LEDS - 1) leds[p + 1] = CHSV(hue + i * 80, 255, 160);
  }

  pos = (pos + 3) % NUM_LEDS;
  hue++;

  FastLED.show();
  delay(10);
}

// =====================
// PATTERN 8: PALETTE CYCLE
// =====================
CRGBPalette16 palettes[] = {
  RainbowColors_p,
  OceanColors_p,
  LavaColors_p,
  ForestColors_p,
  PartyColors_p,
};
#define NUM_PALETTES 5

void patternPaletteCycle() {
  static uint8_t paletteIdx = 0;
  static uint8_t startIndex = 0;
  static unsigned long lastSwitch = 0;

  if (millis() - lastSwitch > 3000) {
    paletteIdx = (paletteIdx + 1) % NUM_PALETTES;
    lastSwitch = millis();
  }

  startIndex++;

  for (int i = 0; i < NUM_LEDS; i++) {
    uint8_t colorIndex = startIndex + (i * 256 / NUM_LEDS);
    leds[i] = ColorFromPalette(palettes[paletteIdx], colorIndex, 220, LINEARBLEND);
  }

  FastLED.show();
  delay(15);
}

// ====================
// SETUP & LOOP
// ====================

void runPattern(int p) {
  switch (p) {
    case 1: patternRainbowWave(); break;
    case 2: patternColorWipe();   break;
    case 3: patternFire();        break;
    case 4: patternMatrixRain();  break;
    case 5: patternTwinkle();     break;
    case 6: patternPlasma();      break;
    case 7: patternColorChase();  break;
    case 8: patternPaletteCycle();break;
    default: patternRainbowWave(); break;
  }
}

void setup() {
  Serial.begin(500000);
  pinMode(13, OUTPUT);

  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS)
    .setCorrection(TypicalLEDStrip);
  FastLED.setBrightness(BRIGHTNESS);
  FastLED.clear();
  FastLED.show();

  initMatrixRain();
  patternStart = millis();

  // Segnale di avvio: lampeggia bianco
  for (int i = 0; i < 3; i++) {
    fill_solid(leds, NUM_LEDS, CRGB::White);
    FastLED.show();
    delay(100);
    FastLED.clear();
    FastLED.show();
    delay(100);
  }

  Serial.println("TEST AVANZATO PRONTO!");
  Serial.println("Invia 0=auto, 1-8=pattern singolo");
}

int autoPatterns[] = {1, 6, 3, 4, 5, 7, 8, 2};
int autoIdx = 0;
#define NUM_AUTO_PATTERNS 8

void loop() {
  // Leggi comando seriale
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd >= '0' && cmd <= '8') {
      int newPat = cmd - '0';
      if (newPat != currentPattern) {
        currentPattern = newPat;
        patternStart = millis();
        FastLED.clear();
        if (currentPattern == 4) initMatrixRain();
        Serial.print("Pattern: ");
        Serial.println(currentPattern);
        digitalWrite(13, currentPattern > 0);
      }
    }
  }

  // Modalità auto: cambia pattern ogni AUTO_INTERVAL ms
  if (currentPattern == 0) {
    if (millis() - patternStart > AUTO_INTERVAL) {
      autoIdx = (autoIdx + 1) % NUM_AUTO_PATTERNS;
      patternStart = millis();
      FastLED.clear();
      if (autoPatterns[autoIdx] == 4) initMatrixRain();
    }
    runPattern(autoPatterns[autoIdx]);
  } else {
    runPattern(currentPattern);
  }
}
