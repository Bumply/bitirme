/*
================================================================================
NEURODRIVE -- NODE 3 | MOTOR CONTROLLER (Arduino Mega 2560)
================================================================================
Receives single-byte drive commands from Node 2 (Raspberry Pi) over USB serial
@ 115200 and drives the wheelchair. Built directly on the user's proven
`full_test (1).ino` -- the hub / steering / brake primitives below are VERBATIM
from that working sketch (do not "improve" them). This file only adds the
NeuroDrive F/L/R/S/E protocol, an E-STOP latch, and hold-to-drive safety.

PROTOCOL (one ASCII byte from Node 2):
    F = FORWARD  -> release brake, hub full throttle (HOLD-TO-DRIVE)
    L = LEFT     -> steer one notch left   (position-limited)
    R = RIGHT    -> steer one notch right
    S = STOP     -> hub off, steer off, COAST (no brake); clears an E-STOP
    E = E-STOP   -> hub off, steer off, ENGAGE brake + latch until an S

SAFETY:
  * HOLD-TO-DRIVE: F only keeps rolling while F bytes keep arriving; if none
    arrive for DRIVE_TIMEOUT_MS the hub is cut. EEG streams ~4/s; the phone
    FORWARD button auto-repeats while held and sends S on release.
  * STOP just coasts (throttle off). The brake is used ONLY by E-STOP; clearing
    an E-STOP (an S after an E) releases it again.
  * Brake is a TIMED PULSE (not a continuous hold) so it can't over-travel.
  * Everything off at boot, brake released.

The lowercase bench keys from full_test (a/d/w/x/q/e/f/g/b/0/1/2/3/+/-/i/v/?)
still work from a serial monitor. Node 2 only ever sends uppercase F/L/R/S/E.

WIRING (Mega 2560): MCP4725 @0x60 SDA20/SCL21; STEER BTS7960 R_EN11 L_EN12
RPWM9 LPWM10; BRAKE BTS7960 R_EN7 L_EN8 RPWM5 LPWM6.
================================================================================
*/

#include <Wire.h>
#include <Adafruit_MCP4725.h>

// =============================================================================
// HUB MOTOR (MCP4725 DAC -> hub controller throttle)   [verbatim from full_test]
// =============================================================================
Adafruit_MCP4725 dac;

const uint16_t THROTTLE_OFF = 933;    // ~0.5 V (below controller's min)
const uint16_t DAC_MIN      = 1900;   // ~2.0 V (controller starts here)
const uint16_t DAC_MAX      = 2100;   // ~3.5 V (controller maxes here)
const int      HUB_STEPS    = 1;

int  currentStep = 0;
bool dac_found   = false;

// Soft-start ramp: hubSetStep() sets a TARGET; rampTick() walks the live DAC
// value toward it a little each tick so the chair eases in/out instead of
// lurching to full throttle. E-STOP bypasses the ramp via hubKill() (snaps to
// idle instantly). Restored from the earlier sketch -- the full_test rewrite
// dropped the ramp, which made F = instant full throttle.
uint16_t dacTarget          = THROTTLE_OFF;
uint16_t dacCurrent         = THROTTLE_OFF;
const uint16_t      RAMP_STEP = 20;   // DAC counts per ramp tick (~ accel rate)
const unsigned long RAMP_MS   = 20;   // ramp tick interval
unsigned long lastRampMs = 0;

void dacWrite(uint16_t v) {
    if (dac_found) dac.setVoltage(v, false);
}

uint16_t getStepValue(int step) {
    if (step <= 0) return DAC_MIN;
    if (step >= HUB_STEPS) return DAC_MAX;
    return DAC_MIN + (uint16_t)((DAC_MAX - DAC_MIN) * (step / (float)HUB_STEPS));
}

// Set the hub TARGET (ramped). step 0 = coast down to idle, step>=1 = drive.
void hubSetStep(int step) {
    if (!dac_found) { Serial.println("[HUB] DAC not found, send 'i' to scan"); return; }
    if (step < 0)         step = 0;
    if (step > HUB_STEPS) step = HUB_STEPS;
    currentStep = step;
    if (step == 0) {
        dacTarget = THROTTLE_OFF;
        Serial.println("[HUB] OFF (ramping down)");
    } else {
        dacTarget = getStepValue(step);
        Serial.print("[HUB] step="); Serial.print(step);
        Serial.print("/"); Serial.print(HUB_STEPS);
        Serial.print("  target="); Serial.println(dacTarget);
    }
}

// Emergency: snap the hub to idle NOW, bypassing the ramp (E-STOP path only).
void hubKill() {
    currentStep = 0;
    dacTarget   = THROTTLE_OFF;
    dacCurrent  = THROTTLE_OFF;
    dacWrite(THROTTLE_OFF);
}

// Walk dacCurrent toward dacTarget by RAMP_STEP every RAMP_MS. Call each loop().
void rampTick() {
    if (millis() - lastRampMs < RAMP_MS) return;
    lastRampMs = millis();
    if (dacCurrent == dacTarget) return;
    if (dacCurrent < dacTarget)
        dacCurrent = min((uint16_t)(dacCurrent + RAMP_STEP), dacTarget);
    else
        dacCurrent = max((uint16_t)(dacCurrent - RAMP_STEP), dacTarget);
    dacWrite(dacCurrent);
}

// =============================================================================
// STEERING MOTOR (BTS7960 #1)                          [verbatim from full_test]
// =============================================================================
#define STEER_R_EN  11
#define STEER_L_EN  12
#define STEER_RPWM  9
#define STEER_LPWM  10

const uint8_t SPEED_LOW  = 150;
const uint8_t SPEED_MID  = 200;
const uint8_t SPEED_FULL = 255;

uint8_t  steerSpeed   = SPEED_LOW;
uint16_t steerPulseMs = 900;
const uint16_t MIN_PULSE = 100;
const uint16_t MAX_PULSE = 2000;

unsigned long steerEndMs  = 0;
bool          steerActive = false;
int           steeringPosition = 0;    // -1 left, 0 center, 1 right

void stopSteering() {
    analogWrite(STEER_RPWM, 0);
    analogWrite(STEER_LPWM, 0);
    steerActive = false;
}

void steerLeft() {
    analogWrite(STEER_LPWM, 0);
    analogWrite(STEER_LPWM, steerSpeed);
    steerActive = true;
    steerEndMs  = millis() + steerPulseMs;
    Serial.print("[STEER] LEFT  speed="); Serial.print(steerSpeed);
    Serial.print("  dur="); Serial.print(steerPulseMs); Serial.println(" ms");
}

void steerRight() {
    analogWrite(STEER_RPWM, 0);
    analogWrite(STEER_RPWM, steerSpeed);
    steerActive = true;
    steerEndMs  = millis() + steerPulseMs;
    Serial.print("[STEER] RIGHT speed="); Serial.print(steerSpeed);
    Serial.print("  dur="); Serial.print(steerPulseMs); Serial.println(" ms");
}

// =============================================================================
// BRAKE MOTOR (BTS7960 #2)                             [verbatim from full_test]
// =============================================================================
#define BRAKE_R_EN  7
#define BRAKE_L_EN  8
#define BRAKE_RPWM  5
#define BRAKE_LPWM  6

const uint8_t brakeSpeed   = 255;
uint16_t brakeEngageMs     = 3000;   // engage (tighten) pulse duration
uint16_t brakeReleaseMs    = 2000;   // release (loosen) pulse duration

unsigned long brakeEndMs  = 0;
bool          brakeActive = false;
bool          brakeHold   = false;
int           brakePosition = 1;       // 0 = engaged, 1 = released

void stopBrake() {
    analogWrite(BRAKE_RPWM, 0);
    analogWrite(BRAKE_LPWM, 0);
    brakeActive = false;
    brakeHold   = false;
}

void brakeEngage(bool hold) {
    analogWrite(BRAKE_RPWM, 0);
    analogWrite(BRAKE_RPWM, brakeSpeed);
    brakeActive = true;
    brakeHold   = hold;
    brakeEndMs  = millis() + brakeEngageMs;
    Serial.print("[BRAKE] ENGAGE speed="); Serial.print(brakeSpeed);
    Serial.print(hold ? "  HOLD" : "  pulse=");
    if (!hold) { Serial.print(brakeEngageMs); Serial.println(" ms"); } else Serial.println();
}

void brakeRelease(bool hold) {
    analogWrite(BRAKE_LPWM, 0);
    analogWrite(BRAKE_LPWM, brakeSpeed);
    brakeActive = true;
    brakeHold   = hold;
    brakeEndMs  = millis() + brakeReleaseMs;
    Serial.print("[BRAKE] RELEASE speed="); Serial.print(brakeSpeed);
    Serial.print(hold ? "  HOLD" : "  pulse=");
    if (!hold) { Serial.print(brakeReleaseMs); Serial.println(" ms"); } else Serial.println();
}

// =============================================================================
// PROTOCOL STATE + SAFETY
// =============================================================================
bool          eStop       = false;
bool          driveActive = false;        // hub currently commanded forward
unsigned long lastDriveMs = 0;            // last F (or L/R while driving)
unsigned long lastCmdMs   = 0;            // last byte of any kind

const unsigned long DRIVE_TIMEOUT_MS = 800;   // hold-to-drive: cut hub
const unsigned long WATCHDOG_MS      = 2000;  // total silence backstop

// Soft stop: hub off + steering off, COAST. Does NOT touch the brake -- the
// brake is reserved for E-STOP only.
void stopAll(const char* reason) {
    hubSetStep(0);
    stopSteering();
    driveActive = false;
    Serial.print("[ALL STOP] "); Serial.println(reason);
}

// =============================================================================
// PROTOCOL HANDLERS (F/L/R/S/E from Node 2)
// =============================================================================
void cmdForward() {
    if (eStop) { Serial.println("[F] ignored (E-STOP)"); return; }
    if (brakePosition == 0) { brakeRelease(false); brakePosition = 1; }  // release brake
    hubSetStep(HUB_STEPS);                 // full throttle (DAC_MAX)
    driveActive = true;
    lastDriveMs = millis();
}

void cmdLeft() {
    if (eStop) return;
    if (steeringPosition > -1) { steerLeft(); steeringPosition--; }
    else Serial.println("[STEER] Already at LEFT limit.");
    if (driveActive) lastDriveMs = millis();   // keep rolling through the turn
}

void cmdRight() {
    if (eStop) return;
    if (steeringPosition < 1) { steerRight(); steeringPosition++; }
    else Serial.println("[STEER] Already at RIGHT limit.");
    if (driveActive) lastDriveMs = millis();
}

void cmdStop() {
    stopAll("stop");
    if (eStop) {
        // recovering from E-STOP: release the brake it engaged
        if (brakePosition == 0) { brakeRelease(false); brakePosition = 1; }
        eStop = false;
        Serial.println("[E-STOP] cleared");
    }
}

void cmdEStop() {
    stopAll("E-STOP");
    hubKill();                                  // snap throttle to idle, no ramp
    if (brakePosition == 1) { brakeEngage(false); brakePosition = 0; }  // brake only here
    eStop = true;
    Serial.println("[E-STOP] latched -- send S to clear");
}

// =============================================================================
// DIAGNOSTICS                                          [from full_test]
// =============================================================================
void printHelp() {
    Serial.println();
    Serial.println("===== NeuroDrive NODE 3 =====");
    Serial.println("Protocol (Node 2): F=fwd L=left R=right S=stop E=estop");
    Serial.println("Bench: w/x hub, a/d steer, q/e brake, f/g/b brake override, 0 hub off");
    Serial.print("eStop="); Serial.print(eStop);
    Serial.print("  driving="); Serial.print(driveActive);
    Serial.print("  hub_step="); Serial.print(currentStep);
    Serial.print("  steerPos="); Serial.print(steeringPosition);
    Serial.print("  brakePos="); Serial.print(brakePosition);
    Serial.print("  dac_found="); Serial.println(dac_found ? "YES" : "NO");
    Serial.println("=============================");
}

void i2cScan() {
    Serial.println("[I2C] scanning...");
    int found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.print("  found 0x");
            if (addr < 16) Serial.print('0');
            Serial.println(addr, HEX);
            found++;
        }
    }
    Serial.print("[I2C] devices: "); Serial.println(found);
}

void readDacVoltage() {
    if (!dac_found) { Serial.println("[DAC] not found"); return; }
    Wire.requestFrom((uint8_t)0x60, (uint8_t)3);
    if (Wire.available() >= 3) {
        Wire.read();
        uint8_t b1 = Wire.read();
        uint8_t b2 = Wire.read();
        uint16_t raw = ((b1 << 4) | (b2 >> 4)) & 0x0FFF;
        Serial.print("[DAC] raw="); Serial.print(raw);
        Serial.print("  V="); Serial.println((raw / 4095.0) * 5.0, 3);
    } else {
        Serial.println("[DAC] read failed");
    }
}

// =============================================================================
// SETUP / LOOP
// =============================================================================
void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 3000) { /* brief wait */ }

    pinMode(STEER_R_EN, OUTPUT); pinMode(STEER_L_EN, OUTPUT);
    pinMode(STEER_RPWM, OUTPUT); pinMode(STEER_LPWM, OUTPUT);
    digitalWrite(STEER_R_EN, HIGH); digitalWrite(STEER_L_EN, HIGH);
    analogWrite(STEER_RPWM, 0); analogWrite(STEER_LPWM, 0);

    pinMode(BRAKE_R_EN, OUTPUT); pinMode(BRAKE_L_EN, OUTPUT);
    pinMode(BRAKE_RPWM, OUTPUT); pinMode(BRAKE_LPWM, OUTPUT);
    digitalWrite(BRAKE_R_EN, HIGH); digitalWrite(BRAKE_L_EN, HIGH);
    analogWrite(BRAKE_RPWM, 0); analogWrite(BRAKE_LPWM, 0);

    Wire.begin();
    Wire.beginTransmission(0x60);
    if (Wire.endTransmission() == 0) {
        dac_found = true;
        dac.begin(0x60);
        dac.setVoltage(THROTTLE_OFF, false);
        Serial.println("[BOOT] DAC 0x60 found, hub idle");
    } else {
        Serial.println("[BOOT] DAC 0x60 NOT found -- send 'i' to scan");
    }

    lastCmdMs = lastDriveMs = millis();
    printHelp();
}

void loop() {
    // ---- read all pending command bytes ----
    while (Serial.available()) {
        char c = Serial.read();
        lastCmdMs = millis();
        switch (c) {
            // ---- NeuroDrive protocol (Node 2) ----
            case 'F': cmdForward(); break;
            case 'L': cmdLeft();    break;
            case 'R': cmdRight();   break;
            case 'S': case 's': case ' ': cmdStop(); break;
            case 'E': cmdEStop();   break;

            // ---- bench keys (serial monitor only) ----
            case 'w':
                if (brakePosition == 0) { brakeRelease(false); brakePosition = 1; }
                hubSetStep(currentStep + 1); break;
            case 'x': hubSetStep(currentStep - 1); break;
            case '0': hubSetStep(0); break;
            case 'a':
                if (steeringPosition > -1) { steerLeft(); steeringPosition--; }
                else Serial.println("[STEER] Already at LEFT limit."); break;
            case 'd':
                if (steeringPosition < 1) { steerRight(); steeringPosition++; }
                else Serial.println("[STEER] Already at RIGHT limit."); break;
            case '1': steerSpeed = SPEED_LOW;  Serial.println("[STEER] speed=LOW");  break;
            case '2': steerSpeed = SPEED_MID;  Serial.println("[STEER] speed=MID");  break;
            case '3': steerSpeed = SPEED_FULL; Serial.println("[STEER] speed=FULL"); break;
            case '+': steerPulseMs = min((uint16_t)(steerPulseMs + 100), MAX_PULSE);
                      Serial.print("[STEER] pulse="); Serial.println(steerPulseMs); break;
            case '-': steerPulseMs = max((uint16_t)(steerPulseMs - 100), MIN_PULSE);
                      Serial.print("[STEER] pulse="); Serial.println(steerPulseMs); break;
            case 'q':
                if (brakePosition == 1) { brakeEngage(false); brakePosition = 0; }
                else Serial.println("[BRAKE] Already engaged."); break;
            case 'e':
                if (brakePosition == 0) { brakeRelease(false); brakePosition = 1; }
                else Serial.println("[BRAKE] Already released."); break;
            case 'z': stopBrake(); Serial.println("[BRAKE] stop"); break;
            case 'f': brakePosition = 0; stopBrake(); Serial.println("[BRAKE] OVERRIDE -> ENGAGED"); break;
            case 'g': brakePosition = 1; stopBrake(); Serial.println("[BRAKE] OVERRIDE -> RELEASED"); break;
            case 'b': Serial.print("[BRAKE] Position = ");
                      Serial.println(brakePosition == 0 ? "ENGAGED" : "RELEASED"); break;
            case 'i': i2cScan(); break;
            case 'v': readDacVoltage(); break;
            case '?': printHelp(); break;

            case '\n': case '\r': break;
            default:
                Serial.print("[?] unknown cmd '"); Serial.print(c); Serial.println("'");
                break;
        }
    }

    // ---- soft-start: walk the hub DAC toward its target every tick ----
    rampTick();

    // ---- hold-to-drive watchdog: cut hub if F stops arriving ----
    if (driveActive && (millis() - lastDriveMs > DRIVE_TIMEOUT_MS)) {
        stopAll("hold timeout");
    }

    // ---- steering pulse timeout ----
    if (steerActive && (long)(millis() - steerEndMs) >= 0) {
        stopSteering();
        Serial.println("[STEER] pulse done");
    }

    // ---- brake pulse timeout (held brake ignores this) ----
    if (brakeActive && !brakeHold && (long)(millis() - brakeEndMs) >= 0) {
        stopBrake();
        Serial.println("[BRAKE] pulse done");
    }

    // ---- comms watchdog: total silence -> ACTIVE stop ----
    // Losing comms while moving is a fail-safe condition: snap throttle off,
    // engage the brake, and latch like E-STOP so the chair holds until comms
    // return and an S re-arms it. driveActive may already be false here (hold-
    // to-drive coasts at 800 ms) but the chair can still be rolling at the 2 s
    // watchdog, so we brake if we were driving recently. Idle = nothing to do.
    if (!eStop && (millis() - lastCmdMs > WATCHDOG_MS)) {
        bool wasMoving = driveActive || steerActive ||
                         (millis() - lastDriveMs < WATCHDOG_MS + DRIVE_TIMEOUT_MS);
        if (wasMoving) {
            Serial.println("[WATCHDOG] comms lost while moving -- braking");
            cmdEStop();              // throttle snap-off + brake engage + latch
        } else {
            lastCmdMs = millis();    // idle: just keep watching
        }
    }
}
