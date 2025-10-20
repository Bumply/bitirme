#ifndef THROTTLE_CONTROLLER_H
#define THROTTLE_CONTROLLER_H

#include "Arduino.h"
#include "Adafruit_MCP4725.h"

class ThrottleController
{
private:
  Adafruit_MCP4725 *dac = nullptr;

  const double minVoltage = 1.0;
  const double lowVoltageThreshold = 1.3;
  const double highVoltageThreshold = 3.5;

  uint16_t calculateDacValueFromVoltage(double pVoltage);

public:
  ThrottleController();
  bool init();
  void setThrottlePosition(uint8_t pThrottlePosition);
  void testSweep();
};

#endif // THROTTLE_CONTROLLER_H
