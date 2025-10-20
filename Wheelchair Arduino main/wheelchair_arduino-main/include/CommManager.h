#ifndef COMM_MANAGER_H
#define COMM_MANAGER_H

#include <Arduino.h>

class CommManager
{
private:
    HardwareSerial *serial;
    bool echo = false;
    unsigned long messageLastRecieved = 0;
    int16_t steeringPosition = 0;
    uint8_t speed = 0;

    void parseData(String &data);

public:
    CommManager();
    void init(HardwareSerial *serial, bool echo = false);

    bool homeSteering = false;

    uint8_t getSpeed();
    int16_t getSteeringPosition();

    void sendObstacleStatus(bool pObstacleDetected);
    void eventLoop();
};

#endif // COMM_MANAGER_H