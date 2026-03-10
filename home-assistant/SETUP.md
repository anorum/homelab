# Home Assistant Custom Configuration

Backup of custom HA configs for easy reload/restore.

## STYRBAR Bedroom Light Selector

Controls `light.alex`, `light.globe`, and `light.mel` with an IKEA STYRBAR remote.

### Button mapping

| Button | Action |
|---|---|
| Left arrow | Select previous light, stops at Light 1 (flashes to confirm) |
| Right arrow | Select next light, stops at Light 3 (flashes to confirm) |
| On (top) | Turn on selected light |
| Off (bottom) | Turn off selected light |
| Hold On | Brightness up on selected light (continuous while held) |
| Hold Off | Brightness down on selected light (continuous while held, min 1%) |
| Hold Left arrow | Turn ALL lights off |
| Hold Right arrow | Turn ALL lights on |

### Setup steps

1. **Create the helper**: Go to Settings > Devices & Services > Helpers > Create Helper > Number. Name it `Bedroom Light Selector`, set min=0, max=2, step=1.

2. **Install the blueprint**: Using the File editor add-on, copy the contents of `blueprints/styrbar_bedroom_lights.yaml` into `blueprints/automation/homeassistant/styrbar_bedroom_lights.yaml` on HA, then reload automations via Developer Tools > YAML.

3. **Create automations**: Go to Settings > Automations > Create Automation > Use Blueprint > "STYRBAR Bedroom Light Selector". Create one automation per remote:
   - Select your STYRBAR device
   - Set Light 1 = `light.alex`, Light 2 = `light.globe`, Light 3 = `light.mel`
   - Set the helper to `input_number.bedroom_light_selector`
   - Set brightness step (default 20%)

4. **Repeat** step 3 for the second STYRBAR remote (same helper, same lights).

### Verify your button events

ZHA event names can vary by firmware. Before setup, go to **Developer Tools > Events**, subscribe to `zha_event`, and press each button on your STYRBAR. Confirm the commands match:

- On button: `on`
- Off button: `off`
- Right arrow: `press` with args `[256, 13, 0]`
- Left arrow: `press` with args `[257, 13, 0]`
- Hold on: `move_with_on_off`
- Hold off: `move`

If your events differ, update the conditions in the blueprint YAML accordingly.

---

## Wyoming Voice Satellite

### Hardware
- Raspberry Pi 4B (hostname: `voice-satellite`)
- ReSpeaker 2-Mic HAT (seeed-voicecard driver)
- Edifier R1280DB speakers (3.5mm jack on ReSpeaker HAT)

Deployment is automated via Ansible — see [ansible/playbook/deploy-voice-satellite.yaml](../ansible/playbook/deploy-voice-satellite.yaml).

### Wyoming Integration Setup

1. In HA, go to **Settings > Devices & Services > Add Integration**.
2. Search for **Wyoming Protocol** and add an entry for each service:

| Service | Host | Port |
|---------|------|------|
| Satellite (voice-satellite) | `voice-satellite.local` | `10700` |
| Whisper STT (Mac Mini) | `192.168.1.105` | `10300` |
| Piper TTS (Mac Mini) | `192.168.1.105` | `10200` |

3. HA will auto-discover the satellite and its local wake word detector.

### Voice Pipeline Configuration

Go to **Settings > Voice Assistants > Add Assistant** (or edit existing):

| Field | Value |
|-------|-------|
| Name | Homelab |
| Language | English (en) |
| Conversation agent | Ollama (or Home Assistant) |
| Speech-to-text | faster-whisper (Mac Mini, port 10300) |
| Text-to-speech | Piper (Mac Mini, port 10200), voice: `en_US-lessac-medium` |
| Wake word engine | openWakeWord (satellite) |
| Wake word | `hey_jarvis` |

### Assign Pipeline to Satellite

1. **Settings > Devices & Services > Wyoming Protocol**
2. Find the "Living Room Satellite" device → click **Configure**
3. Set **Voice assistant pipeline** to "Homelab"

### Adding More Satellites

For each additional Pi satellite:
1. Add a host entry to `ansible/inventory/hosts.yaml` under `voice_satellite`
2. Create `ansible/inventory/host_vars/<hostname>.yaml` with a unique `satellite_name` and `satellite_port`
3. Run `ansible-playbook playbook/deploy-voice-satellite.yaml --limit <hostname>`
4. Add a new Wyoming integration in HA pointing to the new satellite's IP and port
5. Assign the "Homelab" pipeline to the new satellite device

### Audio Testing (SSH to satellite)

```bash
# Test microphone (5 second recording)
arecord -D plughw:CARD=seeed2micvoicec,DEV=0 -f cd -t wav -d 5 test.wav
aplay test.wav

# Adjust mic gain
alsamixer -c 1

# Save ALSA mixer state
sudo alsactl store
```

### Troubleshooting

```bash
# Check service status
systemctl status wyoming-satellite wyoming-openwakeword

# Stream logs
journalctl -u wyoming-satellite -f

# Verify satellite is reachable from network
nc -zv voice-satellite.local 10700
```
