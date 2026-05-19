// --- PIN CONFIGURATIONS ---
const int potPin = A0;
const int ledPins[] = {2, 3, 4, 5, 6};
const int numLeds = 5;
const int segPins[] = {7, 8, 9, 10, 11, 12, 13};

const byte digits[10][7] = {
  {1,1,1,1,1,1,0}, {0,1,1,0,0,0,0}, {1,1,0,1,1,0,1}, {1,1,1,1,0,0,1}, {0,1,1,0,0,1,1},
  {1,0,1,1,0,1,1}, {1,0,1,1,1,1,1}, {1,1,1,0,0,0,0}, {1,1,1,1,1,1,1}, {1,1,1,1,0,1,1}
};

// --- TUNING CONSTANTS ---
const float EMA_ALPHA          = 0.25;
const int   OVERRIDE_THRESHOLD = 20;
const int   DEADZONE_LOW       = 30;
const int   DEADZONE_HIGH      = 993;

// --- STATE TRACKING ---
int   lastVolume  = -1;
float smoothedPot = 0;
int   lastRawPot  = -1;
bool  pcOverride  = false;
bool  ledsEnabled = true;

void setup() {
  Serial.begin(9600);
  Serial.setTimeout(10);

  for (int i = 0; i < numLeds; i++) pinMode(ledPins[i], OUTPUT);
  for (int i = 0; i < 7;       i++) pinMode(segPins[i], OUTPUT);

  lastRawPot  = analogRead(potPin);
  smoothedPot = lastRawPot;
  lastVolume  = potToVolume(smoothedPot);
}

int potToVolume(float adcVal) {
  if (adcVal <= DEADZONE_LOW)  return 100;
  if (adcVal >= DEADZONE_HIGH) return 0;
  int vol = (int)(100.0 - (((adcVal - DEADZONE_LOW) / (float)(DEADZONE_HIGH - DEADZONE_LOW)) * 100.0) + 0.5);
  return constrain(vol, 0, 100);
}

void loop() {
  // --- 1. LISTEN TO THE PC GUI ---
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    int  val  = Serial.parseInt();
    while (Serial.available() > 0) Serial.read();

    if (cmd == 'V' && val >= 0 && val <= 100) {
      lastVolume = val;
      pcOverride = true;
      lastRawPot = analogRead(potPin);
      updateVisuals(val);
    }
    else if (cmd == 'L') {
      ledsEnabled = (val == 1);
      updateVisuals(lastVolume);
    }
  }

  // --- 2. READ & SMOOTH THE KNOB ---
  int rawPot = analogRead(potPin);

  if (pcOverride) {
    if (abs(rawPot - lastRawPot) >= OVERRIDE_THRESHOLD) {
      pcOverride  = false;
      smoothedPot = rawPot;
    }
  }

  // --- 3. SEND TO PC IF KNOB IS IN CONTROL ---
  if (!pcOverride) {
    smoothedPot = EMA_ALPHA * rawPot + (1.0 - EMA_ALPHA) * smoothedPot;

    int currentVolume = potToVolume(smoothedPot);

    if (currentVolume != lastVolume) {
      lastVolume = currentVolume;

      // FIX: Send "V47\n" instead of "47\n" so Python can never
      // misread a partial multi-digit number as a valid value
      Serial.print("V");
      Serial.print(currentVolume);
      Serial.print("\n");

      updateVisuals(currentVolume);
    }

    lastRawPot = rawPot;
  }

  delay(10);
}

void updateVisuals(int vol) {
  if (!ledsEnabled) {
    for (int i = 0; i < numLeds; i++) digitalWrite(ledPins[i], LOW);
    for (int i = 0; i < 7;       i++) digitalWrite(segPins[i], LOW);
    return;
  }

  int ledLevel = map(vol, 0, 100, 0, numLeds);
  for (int i = 0; i < numLeds; i++)
    digitalWrite(ledPins[i], i < ledLevel ? HIGH : LOW);

  int displayDigit = constrain(vol / 10, 0, 9);
  for (int i = 0; i < 7; i++)
    digitalWrite(segPins[i], digits[displayDigit][i]);
}