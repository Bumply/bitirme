/*
================================================================================
NEURODRIVE — NODE 3 | ARDUINO MEGA 2560 MOTOR CONTROL
================================================================================
Receives single-byte commands from Node 2 (Pi 5) via Serial, runs a state
machine with smooth acceleration/deceleration, and drives two wheelchair motors
via H-bridge (L298N or BTS7960).

Serial Protocol (115200 baud):
    Receive: 'F' = forward, 'L' = left, 'R' = right, 'S' = stop, 'E' = e-stop
    Send:    "STATE:<state> SPD:<speed> BAT:<voltage>\n"  (ack after each cmd)

Pin Mapping (Arduino Mega 2560 + L298N dual H-bridge):
    Left motor:   ENA=2 (PWM), IN1=22, IN2=23
    Right motor:  ENB=3 (PWM), IN3=24, IN4=25
    E-stop input: pin 18 (hardware interrupt, active LOW, pulled HIGH)
    E-stop LED:   pin 13 (built-in LED, ON when e-stopped)
    Battery ADC:  A0 (voltage divider: Vbat * R2/(R1+R2), max 5V)

Safety:
    - Hardware e-stop button bypasses all software (wired to motor driver enable)
    - Software watchdog: auto-stop if no serial command for 2 seconds
    - Battery voltage monitor: warning at 11V, auto-stop at 10.5V (for 12V battery)
    - Smooth acceleration ramp prevents sudden jerks
    - State machine rejects invalid transitions

================================================================================
*/

// =============================================================================
// PIN DEFINITIONS
// =============================================================================

// Left motor (L298N channel A)
#define LEFT_EN    2    // PWM speed control (ENA)
#define LEFT_FWD   22   // IN1 — HIGH = forward
#define LEFT_REV   23   // IN2 — HIGH = reverse

// Right motor (L298N channel B)
#define RIGHT_EN   3    // PWM speed control (ENB)
#define RIGHT_FWD  24   // IN3 — HIGH = forward
#define RIGHT_REV  25   // IN4 — HIGH = reverse

// E-stop hardware button (normally open, pulled HIGH, press = LOW)
#define ESTOP_PIN  18   // External interrupt (INT3 on Mega)
#define ESTOP_LED  13   // Built-in LED — ON when e-stopped

// Battery voltage monitoring
#define BAT_PIN    A0   // Voltage divider output
// Voltage divider: 47k (R1) + 10k (R2) -> ratio = 10/(47+10) = 0.1754
// At 12V battery: ADC reads 12 * 0.1754 = 2.105V -> (2.105/5.0)*1023 = 431
#define BAT_DIVIDER_RATIO  5.7   // (R1+R2)/R2 = 57k/10k = 5.7
#define BAT_WARN_V         11.0  // Warning voltage
#define BAT_CUTOFF_V       10.5  // Auto-stop voltage


// =============================================================================
// CONFIGURATION
// =============================================================================

#define SERIAL_BAUD       115200
#define WATCHDOG_TIMEOUT  2000   // ms — auto-stop if no command received
#define RAMP_INTERVAL     20     // ms — time between PWM steps during ramp
#define RAMP_STEP          5     // PWM units per ramp interval (0-255)
#define MAX_SPEED        200     // Max PWM value (0-255), adjustable from Node 2
#define TURN_SPEED_INNER  50     // Inner wheel speed during turn (slight rotation)
#define TURN_SPEED_OUTER 150     // Outer wheel speed during turn
#define BAT_CHECK_INTERVAL 5000  // ms — check battery every 5s
#define ACK_INTERVAL       200   // ms — send state ack to Pi


// =============================================================================
// STATE MACHINE
// =============================================================================

enum State {
    STATE_IDLE,           // Motors off, waiting for command
    STATE_FORWARD,        // Both motors forward, ramping to target speed
    STATE_TURNING_LEFT,   // Right motor forward, left motor slow
    STATE_TURNING_RIGHT,  // Left motor forward, right motor slow
    STATE_STOPPING,       // Ramping down to stop
    STATE_ESTOP           // Emergency stop — motors killed, requires reset
};

const char* STATE_NAMES[] = {
    "IDLE", "FORWARD", "TURN_L", "TURN_R", "STOPPING", "ESTOP"
};


// =============================================================================
// GLOBAL STATE
// =============================================================================

volatile State currentState = STATE_IDLE;
volatile bool eStopTriggered = false;

// Current PWM values (what the motors are actually doing)
int leftPWM  = 0;
int rightPWM = 0;

// Target PWM values (what we're ramping toward)
int leftTarget  = 0;
int rightTarget = 0;

// Speed limit from Node 2 (0-255)
int maxSpeed = MAX_SPEED;

// Timing
unsigned long lastCommandTime = 0;
unsigned long lastRampTime    = 0;
unsigned long lastBatCheck    = 0;
unsigned long lastAckTime     = 0;

// Battery
float batteryVoltage = 12.0;
bool  batteryLow     = false;


// =============================================================================
// E-STOP INTERRUPT (hardware button)
// =============================================================================

void eStopISR() {
    // Immediately kill motors — this runs in interrupt context
    analogWrite(LEFT_EN, 0);
    analogWrite(RIGHT_EN, 0);
    digitalWrite(LEFT_FWD, LOW);
    digitalWrite(LEFT_REV, LOW);
    digitalWrite(RIGHT_FWD, LOW);
    digitalWrite(RIGHT_REV, LOW);

    eStopTriggered = true;
    currentState = STATE_ESTOP;
}


// =============================================================================
// MOTOR CONTROL
// =============================================================================

void setMotorLeft(int speed, bool forward) {
    // speed: 0-255 PWM value
    if (speed == 0) {
        // Brake: both pins LOW
        digitalWrite(LEFT_FWD, LOW);
        digitalWrite(LEFT_REV, LOW);
        analogWrite(LEFT_EN, 0);
    } else if (forward) {
        digitalWrite(LEFT_FWD, HIGH);
        digitalWrite(LEFT_REV, LOW);
        analogWrite(LEFT_EN, speed);
    } else {
        digitalWrite(LEFT_FWD, LOW);
        digitalWrite(LEFT_REV, HIGH);
        analogWrite(LEFT_EN, speed);
    }
}

void setMotorRight(int speed, bool forward) {
    if (speed == 0) {
        digitalWrite(RIGHT_FWD, LOW);
        digitalWrite(RIGHT_REV, LOW);
        analogWrite(RIGHT_EN, 0);
    } else if (forward) {
        digitalWrite(RIGHT_FWD, HIGH);
        digitalWrite(RIGHT_REV, LOW);
        analogWrite(RIGHT_EN, speed);
    } else {
        digitalWrite(RIGHT_FWD, LOW);
        digitalWrite(RIGHT_REV, HIGH);
        analogWrite(RIGHT_EN, speed);
    }
}

void killMotors() {
    leftPWM = 0;
    rightPWM = 0;
    leftTarget = 0;
    rightTarget = 0;
    setMotorLeft(0, true);
    setMotorRight(0, true);
}


// =============================================================================
// RAMP ENGINE — smooth acceleration / deceleration
// =============================================================================

void updateRamp() {
    unsigned long now = millis();
    if (now - lastRampTime < RAMP_INTERVAL) return;
    lastRampTime = now;

    // Ramp left motor toward target
    if (leftPWM < leftTarget) {
        leftPWM = min(leftPWM + RAMP_STEP, leftTarget);
    } else if (leftPWM > leftTarget) {
        leftPWM = max(leftPWM - RAMP_STEP, leftTarget);
    }

    // Ramp right motor toward target
    if (rightPWM < rightTarget) {
        rightPWM = min(rightPWM + RAMP_STEP, rightTarget);
    } else if (rightPWM > rightTarget) {
        rightPWM = max(rightPWM - RAMP_STEP, rightTarget);
    }

    // Apply to motors (always forward for wheelchair — no reverse)
    setMotorLeft(leftPWM, true);
    setMotorRight(rightPWM, true);

    // If stopping and both motors reached zero, go to idle
    if (currentState == STATE_STOPPING && leftPWM == 0 && rightPWM == 0) {
        currentState = STATE_IDLE;
    }
}


// =============================================================================
// COMMAND HANDLER
// =============================================================================

void handleCommand(char cmd) {
    lastCommandTime = millis();

    // E-stop overrides everything
    if (currentState == STATE_ESTOP && cmd != 'S') {
        // In e-stop, only 'S' (reset) is accepted
        sendAck();
        return;
    }

    switch (cmd) {
        case 'F':  // Forward
            currentState = STATE_FORWARD;
            leftTarget  = min((int)maxSpeed, 255);
            rightTarget = min((int)maxSpeed, 255);
            break;

        case 'L':  // Turn left (right motor fast, left motor slow)
            currentState = STATE_TURNING_LEFT;
            leftTarget  = TURN_SPEED_INNER;
            rightTarget = TURN_SPEED_OUTER;
            break;

        case 'R':  // Turn right (left motor fast, right motor slow)
            currentState = STATE_TURNING_RIGHT;
            leftTarget  = TURN_SPEED_OUTER;
            rightTarget = TURN_SPEED_INNER;
            break;

        case 'S':  // Stop (or reset from e-stop)
            if (currentState == STATE_ESTOP) {
                // Reset e-stop only if hardware button is released
                if (digitalRead(ESTOP_PIN) == HIGH) {
                    eStopTriggered = false;
                    currentState = STATE_IDLE;
                    digitalWrite(ESTOP_LED, LOW);
                }
                // If button still pressed, stay in ESTOP
            } else {
                currentState = STATE_STOPPING;
                leftTarget  = 0;
                rightTarget = 0;
            }
            break;

        case 'E':  // Software e-stop from dashboard
            killMotors();
            currentState = STATE_ESTOP;
            eStopTriggered = true;
            digitalWrite(ESTOP_LED, HIGH);
            break;

        case 'V':  // Set max speed (next byte is speed 0-255)
            // Wait for speed byte
            if (Serial.available()) {
                maxSpeed = constrain(Serial.read(), 0, 255);
            }
            break;

        default:
            // Unknown command — ignore
            break;
    }

    sendAck();
}


// =============================================================================
// SERIAL ACKNOWLEDGMENT
// =============================================================================

void sendAck() {
    Serial.print("STATE:");
    Serial.print(STATE_NAMES[currentState]);
    Serial.print(" SPD:");
    Serial.print((leftPWM + rightPWM) / 2);
    Serial.print(" BAT:");
    Serial.print(batteryVoltage, 1);
    Serial.println();
}


// =============================================================================
// BATTERY MONITORING
// =============================================================================

void checkBattery() {
    unsigned long now = millis();
    if (now - lastBatCheck < BAT_CHECK_INTERVAL) return;
    lastBatCheck = now;

    // Read ADC (average 10 samples for stability)
    long sum = 0;
    for (int i = 0; i < 10; i++) {
        sum += analogRead(BAT_PIN);
    }
    float adcAvg = sum / 10.0;

    // Convert to voltage
    batteryVoltage = (adcAvg / 1023.0) * 5.0 * BAT_DIVIDER_RATIO;

    if (batteryVoltage < BAT_CUTOFF_V) {
        // Critical — auto stop
        if (!batteryLow) {
            Serial.println("WARN:BAT_CRITICAL");
            batteryLow = true;
        }
        killMotors();
        currentState = STATE_STOPPING;
        leftTarget = 0;
        rightTarget = 0;
    } else if (batteryVoltage < BAT_WARN_V) {
        if (!batteryLow) {
            Serial.println("WARN:BAT_LOW");
            batteryLow = true;
        }
    } else {
        batteryLow = false;
    }
}


// =============================================================================
// WATCHDOG — auto-stop if Pi goes silent
// =============================================================================

void checkWatchdog() {
    if (currentState == STATE_ESTOP || currentState == STATE_IDLE) return;

    unsigned long now = millis();
    if (now - lastCommandTime > WATCHDOG_TIMEOUT) {
        Serial.println("WARN:WATCHDOG");
        currentState = STATE_STOPPING;
        leftTarget  = 0;
        rightTarget = 0;
    }
}


// =============================================================================
// SETUP
// =============================================================================

void setup() {
    Serial.begin(SERIAL_BAUD);

    // Motor pins
    pinMode(LEFT_EN,   OUTPUT);
    pinMode(LEFT_FWD,  OUTPUT);
    pinMode(LEFT_REV,  OUTPUT);
    pinMode(RIGHT_EN,  OUTPUT);
    pinMode(RIGHT_FWD, OUTPUT);
    pinMode(RIGHT_REV, OUTPUT);

    // E-stop
    pinMode(ESTOP_PIN, INPUT_PULLUP);
    pinMode(ESTOP_LED, OUTPUT);
    attachInterrupt(digitalPinToInterrupt(ESTOP_PIN), eStopISR, FALLING);

    // Battery ADC
    pinMode(BAT_PIN, INPUT);

    // Start with motors off
    killMotors();
    digitalWrite(ESTOP_LED, LOW);

    // Init timing
    lastCommandTime = millis();
    lastRampTime    = millis();
    lastBatCheck    = millis();
    lastAckTime     = millis();

    Serial.println("NODE3:READY");
    Serial.print("STATE:");
    Serial.println(STATE_NAMES[STATE_IDLE]);
}


// =============================================================================
// MAIN LOOP
// =============================================================================

void loop() {
    // 1. Read serial commands from Pi
    while (Serial.available()) {
        char cmd = Serial.read();
        if (cmd >= 'A' && cmd <= 'Z') {
            handleCommand(cmd);
        }
    }

    // 2. E-stop check (hardware button)
    if (eStopTriggered && currentState == STATE_ESTOP) {
        killMotors();
        digitalWrite(ESTOP_LED, HIGH);
    }

    // 3. Update motor ramp (smooth acceleration)
    if (currentState != STATE_ESTOP) {
        updateRamp();
    }

    // 4. Watchdog — auto-stop if Pi is silent
    checkWatchdog();

    // 5. Battery monitoring
    checkBattery();

    // 6. Periodic ack to Pi (so dashboard knows Arduino is alive)
    unsigned long now = millis();
    if (now - lastAckTime > ACK_INTERVAL) {
        lastAckTime = now;
        sendAck();
    }
}
