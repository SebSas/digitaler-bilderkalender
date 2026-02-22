"""
Project: Controlling the fan RPM with PWM depending on the CPU temperature.
Version: 1.3.0
Date:    2026-02-14
Copyright (c) Sebastian Sas

Design goals:
- Minimal CPU overhead (no vcgencmd process spawning)
- Deterministic fan OFF via power gating (enable pin)
- Hysteresis to avoid toggling around threshold
- Keep decomposition + worker thread style
- Conservative but quiet fan curve (Noctua-friendly)
"""

import logging
import threading
import argparse
import time
import RPi.GPIO as GPIO

try:
  import pigpio  # Optional: hardware PWM backend (very low CPU)
except Exception:
  pigpio = None

# --- GPIO (BOARD numbering) ---
ON_OFF_PIN = 11   # BOARD 11 = GPIO17 (power gating via MOSFET/transistor)
PWM_PIN    = 12   # BOARD 12 = GPIO18 (PWM output)
PWM_PIN_BCM = 18  # Same physical pin as BOARD 12, required for pigpio.hardware_PWM

# --- PWM ---
PWM_FREQ_HZ = 1000         # Lower software PWM frequency = lower CPU usage
HW_PWM_FREQ_HZ = 25000     # 4-wire fan-friendly hardware PWM frequency
PWM_SIGNAL_INVERTED = True # Your transistor stage inverts PWM (requested duty -> 100-duty on GPIO)
POLL_SECONDS = 30          # Long poll is fine due to thermal inertia
HEALTHCHECK_SECONDS = 5    # Main thread watchdog interval

# --- Enable hysteresis (°C) ---
ENABLE_ON_C  = 55.0        # Enable fan power at/above this temperature
ENABLE_OFF_C = 50.0        # Disable fan power at/below this temperature

# --- Fail-safe ---
INIT_DUTY = 0              # Deterministic initial duty at startup
FAILSAFE_DUTY = 80         # If temperature can't be read: run fan at 80%
TEST_SEQUENCE = [0, 30, 60, 100, 0]
TEST_STEP_SECONDS = 5.0


def _clamp_duty(duty_cycle: int) -> int:
  return max(0, min(100, int(duty_cycle)))


def _signal_duty_for_requested(duty_cycle: int) -> int:
  """
  Convert logical fan duty (0..100%) to electrical PWM duty on GPIO pin.
  Set PWM_SIGNAL_INVERTED=True for inverting transistor stages.
  """
  duty = _clamp_duty(duty_cycle)
  if PWM_SIGNAL_INVERTED:
    return 100 - duty
  return duty


def _write_requested_duty(pwm, duty_cycle: int) -> None:
  pwm.ChangeDutyCycle(_signal_duty_for_requested(duty_cycle))


class SoftwarePWMAdapter:
  """RPi.GPIO software PWM wrapper with the same API we use in this file."""
  def __init__(self, pwm_pin: int, freq_hz: int):
    GPIO.setup(pwm_pin, GPIO.OUT)
    self._pwm = GPIO.PWM(pwm_pin, freq_hz)
    self._pwm.start(0)

  def ChangeDutyCycle(self, duty_cycle: int) -> None:
    if self._pwm is not None:
      self._pwm.ChangeDutyCycle(duty_cycle)

  def stop(self) -> None:
    # Intentionally no-op for software PWM:
    # with some RPi.GPIO + lgpio builds, a manual stop() followed by __del__()
    # can cause a noisy "TypeError: ... NoneType and int" during interpreter exit.
    # We release the PWM object in close() before GPIO.cleanup() instead.
    return

  def close(self) -> None:
    # Drop the reference so the underlying PWM object is finalized
    # while GPIO is still initialized.
    self._pwm = None


class HardwarePWMAdapter:
  """pigpio hardware PWM wrapper (GPIO18 PWM0) for minimal CPU overhead."""
  def __init__(self, pi, bcm_pin: int, freq_hz: int):
    self._pi = pi
    self._bcm_pin = bcm_pin
    self._freq_hz = freq_hz
    self.ChangeDutyCycle(0)

  def ChangeDutyCycle(self, duty_cycle: int) -> None:
    duty = max(0, min(100, int(duty_cycle)))
    # pigpio duty range for hardware_PWM is 0..1_000_000
    self._pi.hardware_PWM(self._bcm_pin, self._freq_hz, duty * 10000)

  def stop(self) -> None:
    # freq=0 disables hardware PWM on this pin
    self._pi.hardware_PWM(self._bcm_pin, 0, 0)

  def close(self) -> None:
    self._pi.stop()


def init_pwm():
  """Initialize GPIO + PWM. Keep fan power OFF by default.

  Prefers pigpio hardware PWM (very low CPU), falls back to RPi.GPIO software PWM.
  """
  logging.info("Fan-Control: Init PWM")
  GPIO.setmode(GPIO.BOARD)

  # Fan power gate: default OFF (also supported by your pulldown hardware)
  GPIO.setup(ON_OFF_PIN, GPIO.OUT)
  GPIO.output(ON_OFF_PIN, GPIO.LOW)

  logging.info("Fan-Control: PWM inversion=%s", PWM_SIGNAL_INVERTED)

  if pigpio is not None:
    try:
      pi = pigpio.pi()
      if pi.connected:
        logging.info("Fan-Control: Using pigpio hardware PWM on BCM%d (%d Hz)", PWM_PIN_BCM, HW_PWM_FREQ_HZ)
        return HardwarePWMAdapter(pi, PWM_PIN_BCM, HW_PWM_FREQ_HZ)
      logging.warning("Fan-Control: pigpio import ok but daemon not reachable; falling back to software PWM")
      pi.stop()
    except Exception as e:
      logging.warning("Fan-Control: hardware PWM init failed (%s); falling back to software PWM", e)

  logging.info("Fan-Control: Using RPi.GPIO software PWM on BOARD%d (%d Hz)", PWM_PIN, PWM_FREQ_HZ)
  return SoftwarePWMAdapter(PWM_PIN, PWM_FREQ_HZ)

def cleanup_pwm(pwm):
  """Stop PWM and put GPIO into a safe state."""
  try:
    _write_requested_duty(pwm, 0)
    GPIO.output(ON_OFF_PIN, GPIO.LOW)
    pwm.stop()
  finally:
    try:
      pwm.close()
    except Exception:
      pass
    GPIO.cleanup()

def read_cpu_temp_c() -> float:
  """
  Read CPU temperature from sysfs.
  This avoids spawning vcgencmd (lower overhead, more robust in services).
  """
  with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
    return int(f.read().strip()) / 1000.0

def duty_for_temp_c(cpu_temp_c: float) -> int:
  """
  Step-based fan curve (quiet, stable, simple).
  Enabled-state only; OFF is controlled via enable hysteresis.
  """
  # Noctua-friendly defaults: mostly 50%, boost only when needed
  if cpu_temp_c < 70.0:
    return 50
  if cpu_temp_c < 78.0:
    return 80
  return 100

def set_fan_state(pwm, duty_cycle: int) -> None:
  """
  Apply fan state.
  - duty_cycle <= 0  -> real OFF via power gating (enable LOW)
  - duty_cycle > 0   -> set PWM first, then enable power
  """
  if duty_cycle <= 0:
    _write_requested_duty(pwm, 0)
    GPIO.output(ON_OFF_PIN, GPIO.LOW)
    return

  # Deterministic order: PWM first, then power on.
  _write_requested_duty(pwm, duty_cycle)
  GPIO.output(ON_OFF_PIN, GPIO.HIGH)

def control_fan_speed(stop_event: threading.Event, pwm) -> None:
  """
  Worker thread: reads CPU temperature and adjusts fan state.
  Uses enable hysteresis:
  - OFF at/below ENABLE_OFF_C
  - ON at/above ENABLE_ON_C
  """
  fan_enabled = False
  last_duty = None

  # Ensure deterministic initial state
  set_fan_state(pwm, INIT_DUTY)
  last_duty = INIT_DUTY

  while not stop_event.is_set():
    try:
      cpu_temp = read_cpu_temp_c()
    except Exception as e:
      # Fail-safe: if we cannot read temperature, run fan at FAILSAFE_DUTY.
      logging.warning("Temp read failed (%s). Running fan at %d%% (fail-safe).", e, FAILSAFE_DUTY)
      fan_enabled = True
      if last_duty != FAILSAFE_DUTY:
        set_fan_state(pwm, FAILSAFE_DUTY)
        last_duty = FAILSAFE_DUTY
      stop_event.wait(POLL_SECONDS)
      continue

    # Enable/disable hysteresis (power gating)
    if fan_enabled:
      if cpu_temp <= ENABLE_OFF_C:
        fan_enabled = False
        if last_duty != INIT_DUTY:
          logging.info("CPU temp = %.1f°C -> fan OFF (power gated)", cpu_temp)
        set_fan_state(pwm, INIT_DUTY)
        last_duty = INIT_DUTY
    else:
      if cpu_temp >= ENABLE_ON_C:
        fan_enabled = True
        # duty is applied below

    # Duty only when enabled
    if fan_enabled:
      duty = duty_for_temp_c(cpu_temp)
      if duty != last_duty:
        logging.info("CPU temp = %.1f°C -> duty = %d%%", cpu_temp, duty)
        set_fan_state(pwm, duty)
        last_duty = duty

    stop_event.wait(POLL_SECONDS)

  logging.info("Terminating control_fan_speed")

def run_test_sequence(pwm, step_seconds: float) -> None:
  """Manual functional test for power-enable + PWM mapping."""
  for duty in TEST_SEQUENCE:
    signal_duty = _signal_duty_for_requested(duty)
    logging.info(
      "TEST: requested=%d%%, signal=%d%%, power=%s",
      duty,
      signal_duty,
      "ON" if duty > 0 else "OFF",
    )
    set_fan_state(pwm, duty)
    time.sleep(step_seconds)

def parse_args():
  parser = argparse.ArgumentParser(description="Temperature-based PWM fan controller")
  parser.add_argument(
    "--test",
    action="store_true",
    help="Run one-shot test sequence (0,30,60,100,0) and exit",
  )
  parser.add_argument(
    "--test-step-seconds",
    type=float,
    default=TEST_STEP_SECONDS,
    help=f"Seconds per test step (default: {TEST_STEP_SECONDS})",
  )
  return parser.parse_args()

def main():
  args = parse_args()
  print("Running fan-control...")
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(threadName)s %(message)s"
  )

  pwm = None
  thread = None
  stop_event = threading.Event()

  try:
    pwm = init_pwm()

    if args.test:
      run_test_sequence(pwm, max(0.1, float(args.test_step_seconds)))
      return

    thread = threading.Thread(target=control_fan_speed, args=(stop_event, pwm), daemon=True)
    thread.start()

    while not stop_event.wait(HEALTHCHECK_SECONDS):
      if not thread.is_alive():
        logging.critical("control_fan_speed thread terminated unexpectedly")
        raise RuntimeError("control_fan_speed thread terminated unexpectedly")
  except KeyboardInterrupt:
    logging.info("CTRL + C pressed, program terminating")
    stop_event.set()
  finally:
    stop_event.set()
    if thread is not None and thread.is_alive():
      thread.join(timeout=5)
    if pwm is not None:
      cleanup_pwm(pwm)

if __name__ == "__main__":
  main()
