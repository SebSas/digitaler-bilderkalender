#!/usr/bin/env python3
import time
import pigpio

GPIO = 17  # BCM17 enable (active-low in your setup)

pi = pigpio.pi()
assert pi.connected, "pigpio not connected (is pigpiod running?)"

pi.set_mode(GPIO, pigpio.INPUT)  # we only observe
pi.set_pull_up_down(GPIO, pigpio.PUD_OFF)

start = time.time()
last = pi.read(GPIO)

print(f"Watching BCM{GPIO} level changes. Initial level={last}. Press Ctrl+C to stop.")
print("ts(s)   level  dt(ms)")

last_t = start

def cbf(gpio, level, tick):
  global last_t
  now = time.time()
  dt_ms = (now - last_t) * 1000.0
  last_t = now
  print(f"{now - start:6.3f}   {level:>5}  {dt_ms:7.1f}")

cb = pi.callback(GPIO, pigpio.EITHER_EDGE, cbf)

try:
  while True:
    time.sleep(1)
except KeyboardInterrupt:
  pass
finally:
  cb.cancel()
  pi.stop()
