#ifndef STEERING_CONTROLLER_H
#define STEERING_CONTROLLER_H

#include <Arduino.h>

// TODO: determine step angle
// TODO: determine max/min steering position
// TODO: implement homing procedure

typedef enum
{
    LEFT,
    RIGHT
} SteeringDirection;

class SteeringController
{
private:
    int16_t currentPosition;
    uint16_t remainingStepCount;

    uint8_t dirPin, stepPin;
    uint8_t endStopPin;
    uint16_t periodMin = 250, periodMax = 3000;
    uint8_t steeringSpeed = 15;

    SteeringDirection direction;

    unsigned long speed2Period(uint8_t speed);

    void home();
    void step(uint16_t nrOfSteps, SteeringDirection dir);

public:
    bool homed = false;

    SteeringController(uint8_t dirPin, uint8_t stepPin, uint8_t endStopPin);
    void init();
    bool isHomed();
    void setPosition(int16_t position);
    void eventLoop();
};

#endif // STEERING_CONTROLLER_H