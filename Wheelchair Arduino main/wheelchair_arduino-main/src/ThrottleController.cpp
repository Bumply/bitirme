#include "ThrottleController.h"

ThrottleController::ThrottleController()
{
  if (this->dac == nullptr)
  {
    this->dac = new Adafruit_MCP4725();
  }
}

bool ThrottleController::init()
{
  bool retVal = this->dac->begin(0x60);
  if (retVal)
    this->dac->setVoltage(calculateDacValueFromVoltage(minVoltage), true);
  return retVal;
}

uint16_t ThrottleController::calculateDacValueFromVoltage(double pVoltage)
{
  double voltage = 0;
  if (pVoltage <= 0)
  {
    voltage = minVoltage;
  }
  else if ((pVoltage + lowVoltageThreshold) < this->highVoltageThreshold)
  {
    voltage = pVoltage + lowVoltageThreshold;
  }
  else
  {
    voltage = this->highVoltageThreshold;
  }

  return (voltage / 5.0) * 4095;
}

void ThrottleController::setThrottlePosition(uint8_t pThrottlePosition)
{
  uint8_t throttlePosition = (pThrottlePosition > 20) ? 20 : pThrottlePosition; // Limit pitch to 20 degrees
  long voltageX100 = map(throttlePosition, 0, 25, 0, 45); // 0-20 degrees of pitch to 0-1.75 volts
  double voltage = voltageX100 / 100.0;

  this->dac->setVoltage(calculateDacValueFromVoltage(voltage), false);
}

void ThrottleController::testSweep()
{
  for (uint16_t i = 0; i < 4095; i++)
  {
    this->dac->setVoltage(i, false);
    delay(5);
  }

  delay(1000);

  for (uint16_t i = 4095; i > 0; i--)
  {
    this->dac->setVoltage(i, false);
    delay(5);
  }
}