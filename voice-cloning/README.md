# Voice Cloning for Home Voice Satellite

Create custom TTS voices for the linux-voice-assistant (Wyoming Piper) setup.

## Quick Start

```bash
cd voice-cloning

# Create a venv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Scripts

| Script | Purpose | Time to Result |
|--------|---------|---------------|
| `01_prepare_audio.py` | Convert casual recordings → LJSpeech training dataset | ~10 min |
| `02_train_piper.py` | Fine-tune a Piper voice from your dataset | ~4-12 hours |
| `03_xtts_clone.py` | Instant voice cloning with XTTS v2 (no training!) | ~2 min |
| `04_elevenlabs_clone.py` | Cloud voice cloning via ElevenLabs API | ~1 min |

## Workflow

### Fastest: Try XTTS v2 first (2 minutes)

Hear your cloned voice instantly from just a short audio clip:

```bash
# Drop a ~10 second clean voice clip into data/raw/
python scripts/03_xtts_clone.py \
  --speaker-wav data/raw/my_voice_sample.wav \
  --batch

# Listen to samples in output/xtts/
```

### Production: Train a Piper voice

For real-time use on the Raspberry Pi satellite:

```bash
# 1. Put your recordings in data/raw/
# 2. Prepare the training dataset
python scripts/01_prepare_audio.py \
  --input-dir data/raw \
  --output-dir data/dataset

# 3. Review data/dataset/manifest.json — remove bad clips

# 4. Train (requires Piper repo at /opt/piper)
git clone https://github.com/rhasspy/piper.git /opt/piper
cd /opt/piper/src/python && pip install -e . && cd -

python scripts/02_train_piper.py \
  --dataset-dir data/dataset \
  --output-dir models \
  --base-voice lessac-medium

# 5. Deploy the .onnx model to Wyoming Piper
```

### ElevenLabs (best quality, cloud)

```bash
export ELEVENLABS_API_KEY="your-key"

# Clone your voice
python scripts/04_elevenlabs_clone.py clone \
  --name "My Voice" \
  --audio-files data/raw/sample1.wav data/raw/sample2.wav

# Generate speech
python scripts/04_elevenlabs_clone.py speak \
  --voice-id <your-voice-id> \
  --text "Hello from the smart home"
```

## Directory Structure

```
voice-cloning/
  scripts/           # All the tools
  data/
    raw/             # Your original voice recordings (any format)
    processed/       # Intermediate files
    dataset/         # LJSpeech-format dataset for Piper training
  models/            # Trained Piper models (.onnx)
  output/            # Generated audio samples
  notebooks/         # Jupyter notebooks for experimentation
```

## Tips for Good Voice Recordings

- **Quiet environment** — minimal background noise
- **Consistent volume** — don't whisper then shout
- **Clear speech** — enunciate naturally
- **Variety** — different sentences, questions, statements
- **Length** — 1-2 hours total for Piper training, 10 seconds for XTTS
