"""
Core PWM fan control class used by different applications.
"""

import logging
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
PWM_SIGNAL_INVERTED = True

# --- Enable hysteresis (°C) ---
ENABLE_ON_C = 55.0
ENABLE_OFF_C = 50.0

# --- Defaults ---
INIT_DUTY = 0
FAILSAFE_DUTY = 80


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
    GPIO.output(self._board_pin, GPIO.LOW)

  def set_enabled(self, enabled: bool) -> None:
    GPIO.output(self._board_pin, GPIO.HIGH if enabled else GPIO.LOW)

  def close(self) -> None:
    return


class PigpioPowerAdapter:
  """Power-gate adapter using pigpio."""
  backend_name = "pigpio"

  def __init__(self, pi, bcm_pin: int):
    self._pi = pi
    self._bcm_pin = bcm_pin
    self._pi.set_mode(self._bcm_pin, pigpio.OUTPUT)
    self._pi.write(self._bcm_pin, 0)

  def set_enabled(self, enabled: bool) -> None:
    self._pi.write(self._bcm_pin, 1 if enabled else 0)

  def close(self) -> None:
    return


def _init_pwm():
  logging.info("Fan-Control: Init PWM")
  logging.info("Fan-Control: PWM inversion=%s", PWM_SIGNAL_INVERTED)

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
  if cpu_temp_c < 70.0:
    return 50
  if cpu_temp_c < 78.0:
    return 80
  return 100


class PwmFanControl:
  """Reusable fan controller that maps CPU temperature to PWM duty."""

  def __init__(
    self,
    enable_on_c: float = ENABLE_ON_C,
    enable_off_c: float = ENABLE_OFF_C,
    init_duty: int = INIT_DUTY,
    failsafe_duty: int = FAILSAFE_DUTY,
  ):
    self.enable_on_c = float(enable_on_c)
    self.enable_off_c = float(enable_off_c)
    self.init_duty = _clamp_duty(init_duty)
    self.failsafe_duty = _clamp_duty(failsafe_duty)

    self._pwm, self._power_adapter, self._uses_rpi_gpio = _init_pwm()
    self._fan_enabled = False
    self._last_duty = None
    self._set_fan_state(self.init_duty)
    self._last_duty = self.init_duty

  def _set_fan_state(self, duty_cycle: int) -> None:
    if duty_cycle <= 0:
      _write_requested_duty(self._pwm, 0)
      self._power_adapter.set_enabled(False)
      return

    _write_requested_duty(self._pwm, duty_cycle)
    self._power_adapter.set_enabled(True)

  def set_cpu_temp(self, current_temp: float) -> int:
    cpu_temp = float(current_temp)

    if self._fan_enabled:
      if cpu_temp <= self.enable_off_c:
        self._fan_enabled = False
        if self._last_duty != self.init_duty:
          logging.info("CPU temp = %.1f°C -> fan OFF (power gated)", cpu_temp)
        self._set_fan_state(self.init_duty)
        self._last_duty = self.init_duty
    else:
      if cpu_temp >= self.enable_on_c:
        self._fan_enabled = True

    if self._fan_enabled:
      duty = duty_for_temp_c(cpu_temp)
      if duty != self._last_duty:
        logging.info("CPU temp = %.1f°C -> duty = %d%%", cpu_temp, duty)
        self._set_fan_state(duty)
        self._last_duty = duty

    return self._last_duty

  def set_fail_safe(self) -> int:
    self._fan_enabled = True
    if self._last_duty != self.failsafe_duty:
      logging.warning("Running fan at %d%% (fail-safe)", self.failsafe_duty)
      self._set_fan_state(self.failsafe_duty)
      self._last_duty = self.failsafe_duty
    return self._last_duty

  def get_pwm_adapter_name(self) -> str:
    if self._pwm is None:
      return "not initialized"
    return getattr(self._pwm, "adapter_name", self._pwm.__class__.__name__)

  def close(self) -> None:
    if self._pwm is not None:
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
