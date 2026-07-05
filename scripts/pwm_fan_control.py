"""
Core PWM fan control class used by different applications.
"""

import json
import logging
import os
import time
import RPi.GPIO as GPIO

try:
  import pigpio  # Optional: hardware PWM backend (very low CPU)
except Exception:
  pigpio = None

# --- GPIO (BOARD numbering) ---
ON_OFF_PIN = 11
PWM_PIN = 12
ON_OFF_PIN_BCM = 17
PWM_PIN_BCM = 18

# --- PWM ---
PWM_FREQ_HZ = 1000
HW_PWM_FREQ_HZ = 25000
PWM_SIGNAL_INVERTED = False
ENABLE_SIGNAL_INVERTED = True

# --- Enable hysteresis (°C) ---
ENABLE_ON_C = 60.0
ENABLE_OFF_C = 52.0
ON_CONFIRM_SAMPLES = 2
OFF_CONFIRM_SAMPLES = 3

# --- Anti-chatter timing (seconds) ---
MIN_ON_SECONDS = 300.0
MIN_OFF_SECONDS = 120.0

# --- Start assist ---
START_BOOST_DUTY = 70
START_BOOST_SECONDS = 1.2
MIN_RUNNING_DUTY = 50

# --- Defaults ---
INIT_DUTY = 0
FAILSAFE_DUTY = 80
FAN_STATUS_PATH = os.environ.get(
  "DBK_FAN_STATUS_PATH",
  "/home/sebi/docker/dbk-api/cache/fan_status.json",
)


def _clamp_duty(duty_cycle: int) -> int:
  return max(0, min(100, int(duty_cycle)))


def _signal_duty_for_requested(duty_cycle: int) -> int:
  duty = _clamp_duty(duty_cycle)
  if PWM_SIGNAL_INVERTED:
    return 100 - duty
  return duty


def _write_requested_duty(pwm, duty_cycle: int) -> None:
  # Convert requested duty to the actual electrical PWM signal duty and write to the adapter.
  pwm.ChangeDutyCycle(_signal_duty_for_requested(duty_cycle))


def _write_fan_status(path: str, payload: dict) -> None:
  try:
    directory = os.path.dirname(path)
    if directory:
      os.makedirs(directory, exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as status_file:
      json.dump(payload, status_file, separators=(",", ":"))
    os.replace(temp_path, path)
  except Exception as exc:
    logging.debug("Fan status write failed: %s", exc)


def _gpio_level_for_enabled(enabled: bool) -> int:
  if ENABLE_SIGNAL_INVERTED:
    return 0 if enabled else 1
  return 1 if enabled else 0


def _analog_audio_pwm_conflict_active() -> bool:
  # GPIO18 hardware PWM conflicts with legacy analog audio (snd_bcm2835).
  if PWM_PIN_BCM != 18:
    return False
  try:
    with open("/proc/modules", "r", encoding="utf-8") as modules:
      return any(line.startswith("snd_bcm2835 ") for line in modules)
  except Exception:
    return False


class SoftwarePWMAdapter:
  """RPi.GPIO software PWM wrapper with the API used by this module."""
  adapter_name = "software (RPi.GPIO)"

  def __init__(self, pwm_pin: int, freq_hz: int):
    GPIO.setup(pwm_pin, GPIO.OUT)
    self._pwm = GPIO.PWM(pwm_pin, freq_hz)
    self._pwm.start(0)

  def ChangeDutyCycle(self, duty_cycle: int) -> None:
    if self._pwm is not None:
      self._pwm.ChangeDutyCycle(duty_cycle)

  def stop(self) -> None:
    # Keep as no-op to avoid noisy interpreter-shutdown issues seen with some builds.
    return

  def close(self) -> None:
    self._pwm = None


class HardwarePWMAdapter:
  """pigpio hardware PWM wrapper (GPIO18 PWM0)."""
  adapter_name = "hardware (pigpio)"

  def __init__(self, pi, bcm_pin: int, freq_hz: int):
    self._pi = pi
    self._bcm_pin = bcm_pin
    self._freq_hz = freq_hz
    self.ChangeDutyCycle(0)

  def ChangeDutyCycle(self, duty_cycle: int) -> None:
    duty = max(0, min(100, int(duty_cycle)))
    # pigpio hardware_PWM duty range is 0..1_000_000
    self._pi.hardware_PWM(self._bcm_pin, self._freq_hz, duty * 10000)

  def stop(self) -> None:
    self._pi.hardware_PWM(self._bcm_pin, 0, 0)

  def close(self) -> None:
    self._pi.stop()


class GpioPowerAdapter:
  """Power-gate adapter using RPi.GPIO."""
  backend_name = "RPi.GPIO"

  def __init__(self, board_pin: int):
    self._board_pin = board_pin
    GPIO.setup(self._board_pin, GPIO.OUT)
    GPIO.output(self._board_pin, GPIO.HIGH if _gpio_level_for_enabled(False) else GPIO.LOW)

  def set_enabled(self, enabled: bool) -> None:
    GPIO.output(self._board_pin, GPIO.HIGH if _gpio_level_for_enabled(enabled) else GPIO.LOW)

  def close(self) -> None:
    return


class PigpioPowerAdapter:
  """Power-gate adapter using pigpio."""
  backend_name = "pigpio"

  def __init__(self, pi, bcm_pin: int):
    self._pi = pi
    self._bcm_pin = bcm_pin
    self._pi.set_mode(self._bcm_pin, pigpio.OUTPUT)
    self._pi.write(self._bcm_pin, _gpio_level_for_enabled(False))

  def set_enabled(self, enabled: bool) -> None:
    self._pi.write(self._bcm_pin, _gpio_level_for_enabled(enabled))

  def close(self) -> None:
    return


def _init_pwm():
  logging.info("Fan-Control: Init PWM")
  logging.info("Fan-Control: PWM inversion=%s", PWM_SIGNAL_INVERTED)
  logging.info("Fan-Control: ENABLE inversion=%s", ENABLE_SIGNAL_INVERTED)
  if _analog_audio_pwm_conflict_active():
    logging.warning(
      "Fan-Control: snd_bcm2835 is active and may conflict with hardware PWM on BCM%d. "
      "Set dtparam=audio=off and reboot.",
      PWM_PIN_BCM,
    )

  if pigpio is not None:
    try:
      pi = pigpio.pi()
      if pi.connected:
        logging.info(
          "Fan-Control: Using pigpio hardware PWM on BCM%d (%d Hz)",
          PWM_PIN_BCM,
          HW_PWM_FREQ_HZ,
        )
        power_adapter = PigpioPowerAdapter(pi, ON_OFF_PIN_BCM)
        logging.info("Fan-Control: ON/OFF pin handled by pigpio on BCM%d", ON_OFF_PIN_BCM)
        return HardwarePWMAdapter(pi, PWM_PIN_BCM, HW_PWM_FREQ_HZ), power_adapter, False
      logging.warning(
        "Fan-Control: pigpio import ok but daemon not reachable; falling back to software PWM"
      )
      pi.stop()
    except Exception as exc:
      logging.warning("Fan-Control: hardware PWM init failed (%s); falling back to software PWM", exc)

  GPIO.setmode(GPIO.BOARD)
  power_adapter = GpioPowerAdapter(ON_OFF_PIN)
  logging.info("Fan-Control: ON/OFF pin handled by RPi.GPIO on BOARD%d", ON_OFF_PIN)
  logging.info("Fan-Control: Using RPi.GPIO software PWM on BOARD%d (%d Hz)", PWM_PIN, PWM_FREQ_HZ)
  return SoftwarePWMAdapter(PWM_PIN, PWM_FREQ_HZ), power_adapter, True


def _cleanup_pwm(pwm, power_adapter, uses_rpi_gpio: bool):
  try:
    _write_requested_duty(pwm, 0)
    power_adapter.set_enabled(False)
    pwm.stop()
  finally:
    try:
      power_adapter.close()
    except Exception:
      pass
    try:
      pwm.close()
    except Exception:
      pass
    if uses_rpi_gpio:
      GPIO.cleanup()


def duty_for_temp_c(cpu_temp_c: float) -> int:
  if cpu_temp_c < 75.0:
    return 50
  if cpu_temp_c < 82.0:
    return 70
  return 100


class PwmFanControl:
  """Reusable fan controller that maps CPU temperature to PWM duty."""

  def __init__(
    self,
    enable_on_c: float = ENABLE_ON_C,
    enable_off_c: float = ENABLE_OFF_C,
    on_confirm_samples: int = ON_CONFIRM_SAMPLES,
    off_confirm_samples: int = OFF_CONFIRM_SAMPLES,
    min_on_seconds: float = MIN_ON_SECONDS,
    min_off_seconds: float = MIN_OFF_SECONDS,
    start_boost_duty: int = START_BOOST_DUTY,
    start_boost_seconds: float = START_BOOST_SECONDS,
    min_running_duty: int = MIN_RUNNING_DUTY,
    fan_status_path: str = FAN_STATUS_PATH,
    init_duty: int = INIT_DUTY,
    failsafe_duty: int = FAILSAFE_DUTY,
  ):
    self.enable_on_c = float(enable_on_c)
    self.enable_off_c = float(enable_off_c)
    self.on_confirm_samples = max(1, int(on_confirm_samples))
    self.off_confirm_samples = max(1, int(off_confirm_samples))
    self.min_on_seconds = max(0.0, float(min_on_seconds))
    self.min_off_seconds = max(0.0, float(min_off_seconds))
    self.start_boost_duty = _clamp_duty(start_boost_duty)
    self.start_boost_seconds = max(0.0, float(start_boost_seconds))
    self.min_running_duty = _clamp_duty(min_running_duty)
    self.fan_status_path = str(fan_status_path)
    self.init_duty = _clamp_duty(init_duty)
    self.failsafe_duty = _clamp_duty(failsafe_duty)

    self._pwm, self._power_adapter, self._uses_rpi_gpio = _init_pwm()
    self._fan_enabled = False
    self._above_on_count = 0
    self._below_off_count = 0
    self._last_duty = None
    # Allow immediate ON decision after startup if temperature is already high.
    self._state_changed_at = time.monotonic() - self.min_off_seconds
    self._set_fan_state(self.init_duty)
    self._last_duty = self.init_duty
    self._publish_status(cpu_temp=None)

  def _publish_status(self, cpu_temp=None, error=None) -> None:
    duty = int(self._last_duty) if self._last_duty is not None else 0
    is_running = self._fan_enabled and duty > 0
    payload = {
      "status": "running" if is_running else "stopped",
      "duty_pct": duty,
      "cpu_temp_c": (round(float(cpu_temp), 1) if cpu_temp is not None else None),
      "error": (str(error) if error else None),
      "ts": int(time.time()),
    }
    _write_fan_status(self.fan_status_path, payload)

  def _set_fan_state(self, duty_cycle: int) -> None:
    if duty_cycle <= 0:
      _write_requested_duty(self._pwm, 0)
      self._power_adapter.set_enabled(False)
      return

    _write_requested_duty(self._pwm, duty_cycle)
    self._power_adapter.set_enabled(True)

  def set_cpu_temp(self, current_temp: float) -> int:
    cpu_temp = float(current_temp)
    now = time.monotonic()
    seconds_since_state_change = now - self._state_changed_at

    if self._fan_enabled:
      if cpu_temp <= self.enable_off_c:
        self._below_off_count += 1
      else:
        self._below_off_count = 0

      self._above_on_count = 0

      if (
        self._below_off_count >= self.off_confirm_samples
        and seconds_since_state_change >= self.min_on_seconds
      ):
        self._fan_enabled = False
        self._below_off_count = 0
        if self._last_duty != self.init_duty:
          logging.info("CPU temp = %.1f°C -> fan OFF (power gated)", cpu_temp)
        self._set_fan_state(self.init_duty)
        self._last_duty = self.init_duty
        self._state_changed_at = now
    else:
      if cpu_temp >= self.enable_on_c:
        self._above_on_count += 1
      else:
        self._above_on_count = 0

      self._below_off_count = 0

      if (
        self._above_on_count >= self.on_confirm_samples
        and seconds_since_state_change >= self.min_off_seconds
      ):
        self._fan_enabled = True
        self._above_on_count = 0
        self._state_changed_at = now
        if self.start_boost_duty > 0 and self.start_boost_seconds > 0:
          logging.info(
            "CPU temp = %.1f°C -> start boost %d%% for %.1fs",
            cpu_temp,
            self.start_boost_duty,
            self.start_boost_seconds,
          )
          self._set_fan_state(self.start_boost_duty)
          time.sleep(self.start_boost_seconds)
          self._last_duty = self.start_boost_duty

    if self._fan_enabled:
      duty = duty_for_temp_c(cpu_temp)
      if duty > 0:
        duty = max(self.min_running_duty, duty)
      if duty != self._last_duty:
        logging.info("CPU temp = %.1f°C -> duty = %d%%", cpu_temp, duty)
        self._set_fan_state(duty)
        self._last_duty = duty

    self._publish_status(cpu_temp=cpu_temp)
    return self._last_duty

  def set_fail_safe(self) -> int:
    self._fan_enabled = True
    self._above_on_count = 0
    self._below_off_count = 0
    if self._last_duty != self.failsafe_duty:
      logging.warning("Running fan at %d%% (fail-safe)", self.failsafe_duty)
      self._set_fan_state(self.failsafe_duty)
      self._last_duty = self.failsafe_duty
    self._publish_status(cpu_temp=None, error="fail_safe")
    return self._last_duty

  def get_pwm_adapter_name(self) -> str:
    if self._pwm is None:
      return "not initialized"
    return getattr(self._pwm, "adapter_name", self._pwm.__class__.__name__)

  def close(self) -> None:
    if self._pwm is not None:
      self._fan_enabled = False
      self._last_duty = 0
      self._publish_status(cpu_temp=None)
      _cleanup_pwm(self._pwm, self._power_adapter, self._uses_rpi_gpio)
      self._pwm = None
      self._power_adapter = None
      self._uses_rpi_gpio = False

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc, tb):
    self.close()
    return False


class pwm_fan_control(PwmFanControl):
  """Compatibility alias using the requested class name."""
