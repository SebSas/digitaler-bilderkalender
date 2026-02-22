"""
Application that polls CPU temperature and controls the PWM fan.
Terminate with CTRL + C.
"""

import argparse
import logging
import time

from pwm_fan_control import PwmFanControl

DEFAULT_POLL_SECONDS = 30.0


def read_cpu_temp_c() -> float:
  with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as temp_file:
    return int(temp_file.read().strip()) / 1000.0


def parse_args():
  parser = argparse.ArgumentParser(description="Temperature-based PWM fan control app")
  parser.add_argument(
    "--poll-seconds",
    type=float,
    default=DEFAULT_POLL_SECONDS,
    help=f"Temperature polling interval in seconds (default: {DEFAULT_POLL_SECONDS})",
  )
  return parser.parse_args()


def main():
  args = parse_args()
  poll_seconds = max(0.1, float(args.poll_seconds))

  logging.basicConfig(level=logging.INFO, format="%(asctime)s %(threadName)s %(message)s")
  controller = None

  try:
    controller = PwmFanControl()
    print(f"PWM adapter in use: {controller.get_pwm_adapter_name()}")
    logging.info("Temperature control app started (poll every %.1fs)", poll_seconds)

    while True:
      try:
        cpu_temp = read_cpu_temp_c()
        controller.set_cpu_temp(cpu_temp)
      except Exception as exc:
        logging.warning("Temp read failed (%s).", exc)
        controller.set_fail_safe()

      time.sleep(poll_seconds)

  except KeyboardInterrupt:
    logging.info("CTRL + C pressed, program terminating")
  finally:
    if controller is not None:
      controller.close()


if __name__ == "__main__":
  main()
