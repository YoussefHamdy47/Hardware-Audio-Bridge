# Hardware Audio Bridge

Zero-jitter physical volume controller for Windows. 

It features two-way synchronization, dynamic audio endpoint detection (Bluetooth switching), and a custom Windows 11-style On-Screen Display (OSD).

## Key Features
* **Two-Way Synchronization:** If you change the volume using your mouse or keyboard keys, the Arduino's 7-segment display and LED bar graph update instantly. 
* **Loop Protection:** Custom lockout timers prevent the infamous "infinite feedback loop" between physical potentiometers and Windows audio rounding.
* **Dynamic Device Switching:** Seamlessly swaps control when a Bluetooth headset is connected or disconnected.
* **Hardware & Software Filtering:** Uses a 10uF RC filter on the wiper, an Exponential Moving Average (EMA) algorithm, and ±2% hysteresis to completely eliminate capacitive hand noise and phantom drift.
* **Background GUI:** Runs silently in the system tray with a built-in live volume graph and an OSD overlay.

---

## Bill of Materials (Hardware)
* 1x Arduino Uno (or Nano)
* 1x 10 or 20kΩ Potentiometer
* 5x LEDs & 1x 7-Segment Display (Common Cathode)
* Resistors for all LEDs (e.g., 220Ω or 330Ω)
* 1x 470uF Polarized Capacitor (Power Rail Buffer)
* 1x 10uF Polarized Capacitor (Analog Wiper RC Filter)

## Circuit Diagram
*(Ensure capacitors are oriented correctly to ground!)*

<img width="1079" height="606" alt="Screenshot 2026-05-18 023650" src="https://github.com/user-attachments/assets/e20b58df-28e3-40ea-84de-7dd71204cb8f" />

---

## 💻 Software Setup

### 1. The Arduino
1. Open `VolControlAVR.ino` in the Arduino IDE.
2. Upload the code to your Arduino.
3. **Close the Arduino IDE** (Python cannot connect if the Serial Monitor is open).

### 2. The Python App
You will need Python 3 installed on your Windows machine.
1. Clone this repository or download the files.
2. Open your terminal in the project folder and install the required audio and serial libraries:
   ```bash
   pip install pyserial pycaw
   ```

Designed and Tested by Youssef
