#include "CommManager.h"

CommManager::CommManager()
{
}

void CommManager::init(HardwareSerial *serial, bool echo)
{
    this->serial = serial;
    this->echo = echo;
    this->serial->begin(115200);
}

void CommManager::sendObstacleStatus(bool pObstacleDetected)
{
    this->serial->println(pObstacleDetected ? F("OD") : F("OC"));
}

void CommManager::parseData(String &data)
{
    // S:100,P:-50
    this->speed = data.substring(data.indexOf(F("S:")) + 2).toInt();
    this->steeringPosition = data.substring(data.indexOf(F("P:")) + 2).toInt();
    this->steeringPosition = map(this->steeringPosition, -35, 35, -100, 100);

    if (this->echo)
    {
        this->serial->print(F("Recieved: "));
        this->serial->println(data);
        this->serial->print(F("Speed: "));
        this->serial->println(this->speed);
        this->serial->print(F("Steering position: "));
        this->serial->println(this->steeringPosition);
    }
}

void CommManager::eventLoop()
{
    if (millis() - this->messageLastRecieved >= 400)
    {
        this->speed = 0;
        this->steeringPosition = 0;
    }

    Serial.setTimeout(10);
    static String data = "";
    static bool dataReady = false;

    int tChar = this->serial->read();

    if (tChar != -1 && tChar != 0 && (isAlphaNumeric(tChar) || tChar == ',' || tChar == ':' || tChar == '-'))
        data += (char)tChar;

    if ((char)tChar == '\n')
        dataReady = true;

    if (dataReady) // if data is recieved
    {
        this->messageLastRecieved = millis();
        data.toUpperCase();

        if (data == "CHK")
        {
            for (uint8_t i = 0; i < 3; i++)
                Serial.print(F("OK\n"));
        }

        else if (data == "HOME")
        {
            this->homeSteering = true;
        }

        else
            this->parseData(data);

        data = "";
        dataReady = false;
    }
}

uint8_t CommManager::getSpeed()
{
    return this->speed;
}

int16_t CommManager::getSteeringPosition()
{
    return this->steeringPosition;
}
