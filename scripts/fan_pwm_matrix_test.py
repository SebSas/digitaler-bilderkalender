#!/usr/bin/env python3
"""
Interactive matrix test for a 4-pin PWM fan controlled via pigpio.

- Tests combinations of:
  * Enable state (EN): OFF/ON (mapped to GPIO level via polarity setting)
  * PWM duty (%): configurable list
- After each step, asks the user whether the fan is running (y/n), plus optional comment
- Prints a summary report and saves results to JSON.

Run:
  python3 fan_pwm_matrix_test.py
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional

import pigpio

from pwm_fan_control import (
  ENABLE_SIGNAL_INVERTED,
  HW_PWM_FREQ_HZ,
  ON_OFF_PIN_BCM,
  PWM_PIN_BCM,
  PWM_SIGNAL_INVERTED,
)


@dataclass
class TestCase:
  idx: int
  en_gpio: int
  pwm_gpio: int
  hz: int
  en_enabled: bool
  duty_percent: float
  duration_s: float
  note: str = ""


@dataclass
class TestResult:
  case: TestCase
  running: Optional[bool]  # True/False, None if skipped
  comment: str
  timestamp: str


def _prompt_running() -> tuple[Optional[bool], str]:
  while True:
    raw = input("Running? (y/n, s=skip) > ").strip().lower()
    if raw in ("y", "yes"):
      running = True
      break
    if raw in ("n", "no"):
      running = False
      break
    if raw in ("s", "skip"):
      running = None
      break
    print("Please enter y, n, or s.")
  comment = input("Comment (optional) > ").strip()
  return running, comment


def _gpio_level_for_enabled(enabled: bool) -> int:
  if ENABLE_SIGNAL_INVERTED:
    return 0 if enabled else 1
  return 1 if enabled else 0


def _signal_duty_for_requested(duty_percent: float) -> int:
  duty = max(0.0, min(100.0, float(duty_percent)))
  signal_duty_percent = 100.0 - duty if PWM_SIGNAL_INVERTED else duty
  return int(round(signal_duty_percent * 10_000))


def _apply(pi: pigpio.pi, case: TestCase) -> None:
  # Ensure deterministic output for EN
  pi.set_mode(case.en_gpio, pigpio.OUTPUT)
  pi.write(case.en_gpio, _gpio_level_for_enabled(case.en_enabled))

  # Apply hardware PWM (0..1_000_000)
  duty = _signal_duty_for_requested(case.duty_percent)
  duty = max(0, min(1_000_000, duty))
  pi.hardware_PWM(case.pwm_gpio, case.hz, duty)


def _cleanup(pi: pigpio.pi, en_gpio: int, pwm_gpio: int, hz: int) -> None:
  # Try to stop PWM and disable power (best effort)
  try:
    pi.set_mode(en_gpio, pigpio.OUTPUT)
    pi.write(en_gpio, _gpio_level_for_enabled(False))
  except Exception:
    pass
  try:
    # Fully disable hardware PWM output.
    pi.hardware_PWM(pwm_gpio, 0, 0)
  except Exception:
    pass


def main() -> int:
  EN_GPIO = ON_OFF_PIN_BCM
  PWM_GPIO = PWM_PIN_BCM
  HZ = HW_PWM_FREQ_HZ

  # Adjust to taste:
  DUTY_LIST = [0, 10, 25, 50, 80, 100]
  DURATION_S = 4.0

  print("=== Fan PWM Matrix Test (pigpio) ===")
  print(f"EN_GPIO={EN_GPIO}, PWM_GPIO={PWM_GPIO}, HZ={HZ}")
  print(f"Polarity: PWM inverted={PWM_SIGNAL_INVERTED}, ENABLE inverted={ENABLE_SIGNAL_INVERTED}")
  print(f"Duty list: {DUTY_LIST} %, duration per step: {DURATION_S} s")
  print("Tip: make sure dbk-fan.service is stopped to avoid contention.\n")

  pi = pigpio.pi()
  if not pi.connected:
    print("ERROR: Could not connect to pigpio. Is pigpiod running?")
    return 1

  started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  results: List[TestResult] = []

  # Pre: known safe state
  _cleanup(pi, EN_GPIO, PWM_GPIO, HZ)
  time.sleep(0.5)

  idx = 1
  try:
    for en_enabled in (False, True):
      for duty in DUTY_LIST:
        case = TestCase(
          idx=idx,
          en_gpio=EN_GPIO,
          pwm_gpio=PWM_GPIO,
          hz=HZ,
          en_enabled=en_enabled,
          duty_percent=float(duty),
          duration_s=DURATION_S,
          note="",
        )
        idx += 1

        en_level = _gpio_level_for_enabled(case.en_enabled)
        print("\n----------------------------------------")
        print(
          f"Test #{case.idx}: EN={'ON' if case.en_enabled else 'OFF'} "
          f"(GPIO={en_level}) | PWM requested={case.duty_percent:.1f}% @ {case.hz} Hz for {case.duration_s:.1f}s"
        )
        print("Applying...")

        _apply(pi, case)
        time.sleep(case.duration_s)

        running, comment = _prompt_running()
        results.append(
          TestResult(
            case=case,
            running=running,
            comment=comment,
            timestamp=datetime.now().isoformat(timespec="seconds"),
          )
        )

  except KeyboardInterrupt:
    print("\nInterrupted by user.")

  finally:
    _cleanup(pi, EN_GPIO, PWM_GPIO, HZ)
    pi.stop()

  # Report
  print("\n\n=== REPORT ===")
  print(f"Started: {started}")
  print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
  print(f"Total cases recorded: {len(results)}")

  # Compact table-like output
  header = f"{'Idx':>3} | {'EN':>3} | {'Duty%':>5} | {'Run':>3} | Comment"
  print(header)
  print("-" * len(header))
  for r in results:
    run_str = "YES" if r.running is True else ("NO" if r.running is False else "SKIP")
    en_str = "ON" if r.case.en_enabled else "OFF"
    print(f"{r.case.idx:>3} | {en_str:>3} | {r.case.duty_percent:>5.1f} | {run_str:>3} | {r.comment}")

  # Save JSON
  out = {
    "meta": {
      "started": started,
      "finished": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
      "en_gpio": EN_GPIO,
      "pwm_gpio": PWM_GPIO,
      "hz": HZ,
      "pwm_signal_inverted": PWM_SIGNAL_INVERTED,
      "enable_signal_inverted": ENABLE_SIGNAL_INVERTED,
    },
    "results": [
      {
        "case": asdict(r.case),
        "running": r.running,
        "comment": r.comment,
        "timestamp": r.timestamp,
      }
      for r in results
    ],
  }

  out_path = f"/home/sebi/scripts/fan_pwm_matrix_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
  with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)

  print(f"\nSaved JSON report to: {out_path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
