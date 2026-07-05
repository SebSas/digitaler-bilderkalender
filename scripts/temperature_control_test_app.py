"""
Manual test application for PWM fan control.
Enter simulated CPU temperatures in the console and terminate with CTRL + C.
"""

import logging

from pwm_fan_control import PwmFanControl


def main():
  logging.basicConfig(level=logging.INFO, format="%(asctime)s %(threadName)s %(message)s")
  controller = None

  try:
    # Use responsive settings for interactive/manual testing.
    # Production anti-chatter timing is intentionally slower.
    controller = PwmFanControl(
      on_confirm_samples=1,
      off_confirm_samples=1,
      min_on_seconds=0.0,
      min_off_seconds=0.0,
    )
    print(f"PWM adapter in use: {controller.get_pwm_adapter_name()}")
    print("Manual fan test started. Enter temperatures like: 40 or 40,60,70")
    print("Press CTRL + C to terminate.")

    while True:
      raw_input = input("CPU temp (°C): ").strip()
      if not raw_input:
        continue

      values = [token.strip() for token in raw_input.split(",") if token.strip()]
      try:
        for value in values:
          temp_c = float(value)
          duty = controller.set_cpu_temp(temp_c)
          print(f"Temp {temp_c:.1f}°C -> duty {duty}%")
      except ValueError:
        print("Invalid input. Enter a number or comma-separated numbers, e.g. 40,60,70")

  except KeyboardInterrupt:
    logging.info("CTRL + C pressed, program terminating")
  finally:
    if controller is not None:
      controller.close()


if __name__ == "__main__":
  main()
