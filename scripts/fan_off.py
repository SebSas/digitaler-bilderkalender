#!/usr/bin/env python3
"""
DBK fan safe-off helper.

Sets a deterministic 'fan off' state on service stop:
- disable ON/OFF pin (BCM17)
- set PWM duty to 0% on hardware PWM (BCM18 @ 25kHz)

Note: This reduces 'fan runs full speed after stop' when PWM would otherwise float.
A hardware pulldown (e.g., 10k from PWM to GND) is still recommended for crash/boot safety.
"""

import time
import pigpio

PWM_GPIO = 18     # BCM18 hardware PWM
EN_GPIO = 17      # BCM17 ON/OFF

PWM_HZ = 25_000

def main() -> int:
  pi = pigpio.pi()
  if not pi.connected:
    print("fan_off: ERROR: pigpio not connected (is pigpiod running?)")
    return 1

  # Ensure deterministic output modes
  pi.set_mode(EN_GPIO, pigpio.OUTPUT)
  pi.set_mode(PWM_GPIO, pigpio.OUTPUT)

  # 1) Try to stop via enable pin (assume active-high enable)
  pi.write(EN_GPIO, 0)

  # 2) Force PWM duty to 0%
  # hardware_PWM range: duty is 0..1_000_000
  pi.hardware_PWM(PWM_GPIO, PWM_HZ, 0)

  time.sleep(0.2)

  pi.stop()
  print("fan_off: OK")
  return 0

if __name__ == "__main__":
  raise SystemExit(main())
