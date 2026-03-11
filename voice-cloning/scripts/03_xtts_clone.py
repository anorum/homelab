#!/usr/bin/env python3
"""
Quick voice cloning with Coqui XTTS v2.

Clone ANY voice from just 6-10 seconds of reference audio — no training needed!
Great for quick testing before committing to full Piper training.

Usage:
    # Clone from a single audio sample
    python 03_xtts_clone.py --speaker-wav ../data/raw/my_voice_sample.wav

    # Clone and say custom text
    python 03_xtts_clone.py --speaker-wav ../data/raw/sample.wav \
        --text "Hello, this is my cloned voice speaking"

    # Generate multiple samples for comparison
    python 03_xtts_clone.py --speaker-wav ../data/raw/sample.wav --batch

    # Use GPU (Apple Silicon MPS or CUDA)
    python 03_xtts_clone.py --speaker-wav ../data/raw/sample.wav --gpu

Prerequisites:
    pip install TTS soundfile
"""

import argparse
import sys
import tempfile
import time
from pathlib import Path

from pydub import AudioSegment


def trim_silence(wav_path: Path, trim_ms: int = 500) -> Path:
    """Trim leading/trailing silence from a WAV and return a temp file path."""
    audio = AudioSegment.from_wav(str(wav_path))
    trimmed = audio[trim_ms:-trim_ms]
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    trimmed.export(tmp.name, format="wav")
    return Path(tmp.name)

SAMPLE_TEXTS = [
    "I'm an assistant here to help. Tell me what you want me to do.",
]


def clone_voice(speaker_wav: Path, text: str, output_path: Path, use_gpu: bool = False):
    """Clone a voice and generate speech."""
    from TTS.api import TTS

    device = "cpu"
    if use_gpu:
        import torch
        if torch.backends.mps.is_available():
            # XTTS v2 MPS support can be spotty — fall back to CPU if it fails
            device = "cpu"  # MPS often has issues with XTTS, CPU is more reliable
            print("Note: MPS detected but using CPU for XTTS (more reliable)")
        elif torch.cuda.is_available():
            device = "cuda"
            print(f"Using CUDA: {torch.cuda.get_device_name(0)}")

    print(f"Loading XTTS v2 model (this may take a minute on first run)...")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

    trimmed_wav = trim_silence(speaker_wav)
    print(f"Cloning voice from: {speaker_wav.name} (silence-trimmed)")
    print(f"Output: {output_path}")

    start = time.time()
    tts.tts_to_file(
        text=text,
        speaker_wav=str(trimmed_wav),
        language="en",
        file_path=str(output_path),
    )
    trimmed_wav.unlink(missing_ok=True)
    elapsed = time.time() - start
    print(f"Generated in {elapsed:.1f}s")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Quick voice cloning with XTTS v2")
    parser.add_argument("--speaker-wav", type=Path, required=True,
                        help="Reference audio of the voice to clone (6-30 sec, clean speech)")
    parser.add_argument("--text", type=str, default=None,
                        help="Text to speak (default: sample smart home phrases)")
    parser.add_argument("--output-dir", type=Path, default=Path("../output/xtts"),
                        help="Output directory (default: ../output/xtts)")
    parser.add_argument("--gpu", action="store_true",
                        help="Use GPU if available")
    parser.add_argument("--batch", action="store_true",
                        help="Generate all sample texts for comparison")

    args = parser.parse_args()

    if not args.speaker_wav.exists():
        print(f"Error: Speaker WAV not found: {args.speaker_wav}")
        sys.exit(1)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.batch:
        # Generate all sample texts
        print(f"Generating {len(SAMPLE_TEXTS)} samples...")
        print()
        for i, text in enumerate(SAMPLE_TEXTS):
            output_path = output_dir / f"sample_{i:02d}.wav"
            clone_voice(args.speaker_wav.resolve(), text, output_path, args.gpu)
            print()
        print(f"All samples saved to: {output_dir}")
    else:
        text = args.text or SAMPLE_TEXTS[0]
        output_path = output_dir / "cloned_output.wav"
        clone_voice(args.speaker_wav.resolve(), text, output_path, args.gpu)

    print()
    print("Listen to the output and compare with your voice!")
    print("If it sounds good, consider training a full Piper voice for real-time use.")
    print("Run: python 02_train_piper.py --dataset-dir ../data/dataset")


if __name__ == "__main__":
    main()
