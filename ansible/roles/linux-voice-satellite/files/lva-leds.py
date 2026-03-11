#!/usr/bin/env python3
"""
ReSpeaker 2-Mic HAT LED companion for linux-voice-assistant.

Tails the systemd journal and drives 3 APA102 LEDs based on INFO-level logs.

LED states:
  Wake word   → blue pulse then solid green (listening)
  TTS playing → solid amber (auto-off 10s after last chunk)
  Connected   → white flash
  Disconnected→ dim red

Requires: apa102-pi, spidev  (run as root for SPI access)
"""

import subprocess
import sys
import time
import threading

try:
    from apa102_pi.driver.apa102 import APA102
except ImportError:
    print("apa102-pi not installed. Run: pip install apa102-pi", file=sys.stderr)
    sys.exit(1)

NUM_LEDS = 3
BRIGHTNESS = 8  # 0-31; keep low so it's not blinding

strip = APA102(num_led=NUM_LEDS, global_brightness=BRIGHTNESS, mosi=10, sclk=11)

_off_timer = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def all_off():
    strip.clear_strip()
    strip.show()


def set_all(r, g, b):
    for i in range(NUM_LEDS):
        strip.set_pixel(i, r, g, b)
    strip.show()


def pulse(r, g, b, times=3, on_ms=120, off_ms=80):
    for _ in range(times):
        set_all(r, g, b)
        time.sleep(on_ms / 1000)
        all_off()
        time.sleep(off_ms / 1000)


def schedule_off(delay=10):
    """Turn LEDs off after delay seconds of no new TTS activity."""
    global _off_timer
    if _off_timer:
        _off_timer.cancel()
    _off_timer = threading.Timer(delay, all_off)
    _off_timer.daemon = True
    _off_timer.start()


# ── State machine ─────────────────────────────────────────────────────────────
# LVA only emits INFO-level logs without --debug. Patterns based on actual output:
#   INFO:MpvMediaPlayer:Playing 1 URL(s): .../sounds/wake_word_triggered.flac
#   INFO:MpvMediaPlayer:Playing 1 URL(s): http://.../api/tts_proxy/...
#   INFO:linux_voice_assistant.satellite:Connected to Home Assistant
#   INFO:linux_voice_assistant.satellite:Disconnected from Home Assistant

def handle_line(line: str):
    # Wake word chime → blue pulse, then green (listening)
    if "wake_word_triggered" in line:
        pulse(0, 0, 255)
        set_all(0, 128, 0)

    # HA TTS response chunk playing → amber; auto-off 10s after last chunk
    elif "tts_proxy" in line:
        set_all(128, 96, 0)
        schedule_off(10)

    # Connected to HA → quick white flash
    elif "Connected to Home Assistant" in line:
        pulse(200, 200, 200, times=1, on_ms=300)

    # Disconnected → dim red
    elif "Disconnected from Home Assistant" in line:
        set_all(64, 0, 0)


def main():
    all_off()

    cmd = [
        "journalctl", "-u", "linux-voice-assistant",
        "-f", "--no-pager", "-o", "cat",
        "--lines=0",  # only new lines from now on
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:
            line = line.strip()
            if line:
                handle_line(line)
    except KeyboardInterrupt:
        pass
    finally:
        all_off()
        strip.cleanup()
        proc.terminate()


if __name__ == "__main__":
    main()
