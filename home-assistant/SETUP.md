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
