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

## Voice Satellite

### Hardware
- Raspberry Pi Zero 2 W (hostname: `voice-satellite`)
- ReSpeaker 2-Mic HAT (seeed-voicecard driver, APA102 LEDs)
- Edifier R1280DB speakers (3.5mm jack on ReSpeaker HAT)

### Architecture

```
Pi Zero 2 W
  linux-voice-assistant (ESPHome, port 6053)  ← primary
  wyoming-satellite (Wyoming, port 10700)      ← fallback

Mac Mini (192.168.1.105)
  Wyoming Whisper :10300  — STT
  Wyoming Piper   :10200  — TTS
  Homelab MCP     :8080   — tools for Ollama

HA: ESPHome integration → satellite (auto-discovered)
    Wyoming integrations → Whisper + Piper
    MCP Client integration → Mac Mini:8080
    Ollama conversation agent → Mac Mini:11434
```

### Deployment

**Primary (linux-voice-assistant — ESPHome protocol):**
```bash
cd ansible
ansible-playbook playbook/deploy-linux-voice-satellite.yaml
```
HA discovers the satellite automatically via mDNS — no manual Wyoming integration needed for the satellite itself.

**Fallback (wyoming-satellite):**
```bash
cd ansible
ansible-playbook playbook/deploy-voice-satellite.yaml
```
The wyoming role is preserved intact. To roll back: re-run it and remove the ESPHome device from HA.

**Note (first deploy):** The first run installs the ReSpeaker kernel driver and reboots (up to 5 min on Pi Zero 2 W). Run the playbook a second time to complete setup.

### MCP Homelab Tools Setup

1. Start MCP server on Mac Mini:
   ```bash
   cd mac-mini && docker compose up -d homelab-mcp
   ```
2. In HA: **Settings > Devices & Services > Add Integration > Model Context Protocol**
   - URL: `http://192.168.1.105:8080/mcp`
   - Name: `Homelab Tools`

To add new tools: edit `mac-mini/mcp-server/server.py`, add a `@mcp.tool()` function, restart the container. No HA config changes needed.

### Wyoming Integration Setup (STT + TTS on Mac Mini)

In HA, go to **Settings > Devices & Services > Add Integration > Wyoming Protocol**:

| Service | Host | Port |
|---------|------|------|
| Whisper STT | `192.168.1.105` | `10300` |
| Piper TTS | `192.168.1.105` | `10200` |

### Voice Pipeline Configuration

**Settings > Voice Assistants > Add Assistant** (or edit existing):

| Field | Value |
|-------|-------|
| Name | Homelab |
| Language | English (en) |
| Conversation agent | Ollama (`llama3.1:8b` recommended for tool calling) |
| Speech-to-text | faster-whisper (Mac Mini, port 10300) |
| Text-to-speech | Piper (Mac Mini, port 10200), voice: `en_US-lessac-medium` |
| Wake word engine | openWakeWord (auto-configured on satellite) |
| Wake word | `hey_jarvis` |

**Note:** Use `llama3.1:8b` or `qwen3:8b` for reliable tool calling. The 4B model may not consistently invoke MCP tools.

### Assign Pipeline to Satellite

1. **Settings > Devices & Services > ESPHome**
2. Find the "Living Room Satellite" device → **Configure**
3. Set **Voice assistant pipeline** to "Homelab"

### Adding More Satellites

1. Add host entry to `ansible/inventory/hosts.yaml` under `voice_satellite`
2. Create `ansible/inventory/host_vars/<hostname>.yaml` with a unique `satellite_name`
3. Run `ansible-playbook playbook/deploy-linux-voice-satellite.yaml --limit <hostname>`
4. HA auto-discovers via mDNS; assign the "Homelab" pipeline to the new device

### Audio Testing (SSH to satellite)

```bash
# Test microphone (5 second recording)
arecord -D plughw:CARD=seeed2micvoicec,DEV=0 -f cd -t wav -d 5 test.wav
aplay test.wav

# Adjust mic gain
alsamixer -c 1

# Save ALSA mixer state
sudo alsactl store

# List detected audio devices (linux-voice-assistant)
LIST_DEVICES=1 /opt/linux-voice-assistant/.venv/bin/python -m linux_voice_assistant
```

### Troubleshooting

```bash
# linux-voice-assistant
systemctl status linux-voice-assistant
journalctl -u linux-voice-assistant -f
nc -zv voice-satellite.local 6053

# Fallback wyoming services
systemctl status wyoming-satellite wyoming-openwakeword
journalctl -u wyoming-satellite -f
nc -zv voice-satellite.local 10700

# MCP server (on Mac Mini)
curl http://192.168.1.105:8080/mcp
docker logs homelab-mcp
```

### Known Limitations

**Barge-in / TTS interrupt**: Long TTS responses cannot be interrupted by speaking. Neither linux-voice-assistant nor wyoming-satellite implements barge-in as of early 2026. Track progress at [OHF-Voice/linux-voice-assistant issues](https://github.com/OHF-Voice/linux-voice-assistant/issues).
