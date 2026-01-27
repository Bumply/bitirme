#include <Arduino.h>
#include "Pins.h"
#include "SteeringController.h"
#include "CommManager.h"
#include "ThrottleController.h"

SteeringController steeringController(DIR_PIN, STEP_PIN, ENDSTOP_PIN);
CommManager commManager;
ThrottleController throttleController;

void setup()
{
    steeringController.init();
    commManager.init(&Serial, false);
    pinMode(LED_BUILTIN, OUTPUT);
    while (!throttleController.init())
    {
        digitalWrite(LED_BUILTIN, HIGH);
        delay(100);
        digitalWrite(LED_BUILTIN, LOW);
        delay(100);
    }
    // throttleController.testSweep();
    digitalWrite(LED_BUILTIN, HIGH);
}

void loop()
{
    steeringController.eventLoop();

    if (steeringController.isHomed())
    {
        commManager.eventLoop();

        if (commManager.homeSteering)
        {
            steeringController.homed = false;
            commManager.homeSteering = false;
            return;
        }

        throttleController.setThrottlePosition(commManager.getSpeed());
        steeringController.setPosition(commManager.getSteeringPosition());
    }
}