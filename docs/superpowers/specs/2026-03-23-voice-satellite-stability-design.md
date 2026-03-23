# Voice Satellite Stability Design

**Date:** 2026-03-23
**Status:** Approved

## Problem

The living room voice satellite (Pi Zero 2W + ReSpeaker 2-Mic HAT) has three stability issues:

1. **Wake word unreliable** — `hey_jarvis` triggers erratically: too sensitive in some environments, unresponsive in others. Root causes: weak training data for that model, and TTS audio reflecting off walls back into the mic (echo feedback).

2. **No way to interrupt TTS** — the `--stop-model stop` flag is set in the service, but it only aborts a voice command in progress; it does not kill active TTS audio. Long or wrong responses can't be cut short.

3. **Volume = 0 on restart** — WirePlumber defaulted to `analog-output-speaker` route (mutes headphone jack). Fixed in commit `100839f`, but echo cancellation disabled during that same investigation, leaving the echo problem unresolved.

## Scope

In scope: wake word reliability, TTS interrupt, echo cancellation.
Out of scope: LLM tooling quality, Spotify integration, voice cloning.

---

## Design

### 1. Switch Wake Word: `hey_jarvis` → `okay_nabu`

`okay_nabu` is Home Assistant's flagship micro wake word model with substantially more training data. The user is open to changing the phrase; "nabu" has no phonetic overlap with names in the household ("Alex", "Boo").

**Changes:**

- **`ansible/roles/linux-voice-satellite/files/`**: Add `okay_nabu.json` (micro wake word descriptor pointing to `okay_nabu.tflite`). Remove `hey_jarvis.json`.
- **`ansible/roles/linux-voice-satellite/templates/linux-voice-assistant.service.j2`**: Change `--wake-model hey_jarvis` → `--wake-model okay_nabu`.
- **`ansible/roles/linux-voice-satellite/tasks/main.yaml`**: Update the deploy task (currently copies `hey_jarvis.json`) to copy `okay_nabu.json` instead.
- **`ansible/inventory/host_vars/voice-satellite.yaml`**: No change needed; wake model is in the service template.
- **HA UI** (manual): Update the voice pipeline's wake word selection from `hey_jarvis` to `okay_nabu`.
- **`home-assistant/SETUP.md`**: Update wake word references.

The `okay_nabu.tflite` model file ships with the `linux-voice-assistant` package; confirm it exists at `/opt/linux-voice-assistant/wakewords/okay_nabu.tflite` after install. If not, download it from the [ESPHome micro-wake-word-models repo](https://github.com/esphome/micro-wake-word-models).

The `okay_nabu.json` descriptor must match the model's expected parameters. Get the canonical values from the same repo (`models/okay_nabu/manifest.json` or similar). The fields required (from `hey_jarvis.json`) are: `probability_cutoff`, `tensor_arena_size`, `sliding_window_size`, `feature_step_size`, `minimum_esphome_version`. Do not guess these values — use the official manifest.

---

### 2. Re-enable Echo Cancellation (with correct device name)

Echo cancel was previously removed because PipeWire creates a virtual source named differently from the physical mic, breaking `--audio-input-device`. The fix is to re-enable the module *and* update the device name to match the virtual source.

**Changes:**

- **`ansible/roles/linux-voice-satellite/tasks/main.yaml`**: Replace the "Remove PipeWire echo-cancel config" block with a task that deploys `60-echo-cancel.conf.j2` to `/etc/pipewire/pipewire.conf.d/60-echo-cancel.conf`. Add a restart trigger for PipeWire when this file changes.

- **`ansible/roles/linux-voice-satellite/templates/60-echo-cancel.conf.j2`**: Already exists. The virtual source name is confirmed as `"Echo-Cancel Source"` (set via `capture.props.node.name` in the template). No changes needed to this file.

- **`ansible/inventory/host_vars/voice-satellite.yaml`**: Change `audio_input_device` from `"Built-in Audio Stereo"` to `"Echo-Cancel Source"`. Verify after deploy by running `pactl list sources short` on the satellite (`pactl` works here because `pipewire-pulse` is enabled in the role).

- **`ansible/roles/linux-voice-satellite/tasks/main.yaml`**: Remove the existing "Remove PipeWire echo-cancel config if present" + restart block. Replace with deploy + conditional restart.

---

### 3. TTS Interrupt ("Stop" voice command)

The `--stop-model stop` flag is already set in the service. LVA already loads `stop.tflite` (micro/TFLite format, probability cutoff 0.30) and detects the stop command. However, the stop detection only aborts the STT pipeline — it does not kill active TTS audio being played to the speaker.

**Design: patch `satellite.py` to kill audio on stop**

LVA already processes stop detection internally. Rather than a separate process, patch `satellite.py` to also kill active PipeWire sink inputs when stop fires:

- Inspect `/opt/linux-voice-assistant/linux_voice_assistant/satellite.py` on the device to locate the stop command handler (search for `stop_model`, `stop_command`, or where `wake_word` events are dispatched).
- Add a `subprocess.run` call at that point to kill all active sink inputs:
  ```
  pactl list short sink-inputs | awk '{print $1}' | xargs -r pactl kill-sink-input
  ```
- Deploy via an additional `ansible.builtin.replace` patch task in `main.yaml`, similar to the existing `media_player_patch`.
- Trigger LVA service restart when the patch changes.

**Fallback:** If the stop handler in `satellite.py` is not easily patchable (e.g., it's deeply nested or async), use a lightweight Vosk keyword-spotting daemon instead (not `openwakeword` — the stop model is TFLite micro format, incompatible with the `openwakeword` pip package).

**Note on `stop.json`:** This file is already deployed correctly. No changes to it are needed.

**New files (only if fallback Vosk path is taken):**
- `ansible/roles/linux-voice-satellite/files/stop-word-daemon.py`
- `ansible/roles/linux-voice-satellite/templates/stop-word.service.j2`

---

### 4. Service Stability

Already in good shape:
- `linux-voice-assistant.service` has `Restart=always` + `RestartSec=5` ✓
- Volume routing fixed in `100839f` ✓

No changes needed here.

---

## Files to Modify

| File | Change |
|------|--------|
| `ansible/roles/linux-voice-satellite/tasks/main.yaml` | Wake word task (hey_jarvis→okay_nabu); swap remove→deploy for echo cancel; update restart condition register var (`hey_jarvis_json` → `okay_nabu_json`); add satellite.py stop patch task |
| `ansible/roles/linux-voice-satellite/templates/linux-voice-assistant.service.j2` | `--wake-model okay_nabu` |
| `ansible/roles/linux-voice-satellite/files/okay_nabu.json` | New file (micro wake word descriptor — get values from ESPHome repo manifest) |
| `ansible/roles/linux-voice-satellite/files/hey_jarvis.json` | Delete |
| `ansible/inventory/host_vars/voice-satellite.yaml` | `audio_input_device: "Echo-Cancel Source"` |
| `home-assistant/SETUP.md` | Update wake word references |
| `ansible/roles/linux-voice-satellite/files/stop-word-daemon.py` | New file (only if satellite.py patch is not feasible) |
| `ansible/roles/linux-voice-satellite/templates/stop-word.service.j2` | New file (only if satellite.py patch is not feasible) |

---

## Verification

1. **Wake word**: Deploy, say "okay nabu" 5 times from normal conversation distance. Confirm LED pulses blue each time. Say unrelated speech for 30 seconds — confirm no false triggers.

2. **Echo feedback test**: Trigger a long TTS response. While audio is playing, confirm the wake word does NOT fire from the speaker output. This validates the echo cancellation is working.

3. **Echo cancel source**: Run `pactl list sources short` on the satellite (works because `pipewire-pulse` is active). Confirm `Echo-Cancel Source` is listed. Confirm `audio_input_device` in host_vars is `"Echo-Cancel Source"`.

4. **TTS interrupt**: Trigger a response that generates a long TTS reply. While audio is playing, say "stop". Confirm audio cuts off within ~1 second.

5. **Memory**: Run `free -m` on the satellite with all services running. Confirm available memory > 80MB.

6. **Restart stability**: Reboot the satellite. Confirm linux-voice-assistant and lva-leds start and reach active state within 30 seconds. Confirm audio plays correctly (not muted).
