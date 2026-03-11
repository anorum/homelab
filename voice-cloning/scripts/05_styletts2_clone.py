#!/usr/bin/env python3
"""
Voice cloning with StyleTTS2 — supports style/prosody/expressiveness controls.

Unlike XTTS v2, StyleTTS2 exposes explicit knobs for tone and personality:
  --alpha           style blend (0=base model, 1=full reference voice)
  --beta            prosody blend (0=base, 1=reference rhythm/intonation)
  --diffusion-steps quality vs speed (5=fast, 20=best)
  --expressiveness  emotional intensity (1.0=neutral, 2.0+=expressive/upbeat)

Prerequisites (system):
    brew install espeak-ng

Usage:
    uv run scripts/05_styletts2_clone.py --speaker-wav data/raw/my_voice_sample.wav
    uv run scripts/05_styletts2_clone.py --speaker-wav data/raw/sample.wav --expressiveness 1.8 --diffusion-steps 20
"""

import argparse
import sys
from pathlib import Path


SAMPLE_TEXTS = [
    "I'm an assistant here to help. Tell me what you want me to do.",
]


def clone_voice(
    speaker_wav: Path,
    text: str,
    output_path: Path,
    alpha: float = 0.3,
    beta: float = 0.7,
    diffusion_steps: int = 10,
    expressiveness: float = 1.0,
):
    import nltk
    import soundfile as sf
    from styletts2 import tts as styletts2_tts

    nltk.download("punkt_tab", quiet=True)
    nltk.download("averaged_perceptron_tagger_eng", quiet=True)

    print("Loading StyleTTS2 model (downloads ~500MB on first run)...")
    model = styletts2_tts.StyleTTS2()

    print(f"Cloning voice from: {speaker_wav.name}")
    print(f"  alpha={alpha}  beta={beta}  steps={diffusion_steps}  expressiveness={expressiveness}")

    wav = model.inference(
        text=text,
        target_voice_path=str(speaker_wav),
        alpha=alpha,
        beta=beta,
        diffusion_steps=diffusion_steps,
        embedding_scale=expressiveness,
    )

    sf.write(str(output_path), wav, 24000)
    print(f"Saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Voice cloning with StyleTTS2")
    parser.add_argument("--speaker-wav", type=Path, required=True,
                        help="Reference audio of the voice to clone")
    parser.add_argument("--text", type=str, default=None,
                        help="Text to speak (default: sample phrase)")
    parser.add_argument("--output-dir", type=Path, default=Path("output/styletts2"),
                        help="Output directory")
    parser.add_argument("--alpha", type=float, default=0.3,
                        help="Style blend: 0=base model voice, 1=full reference voice (default: 0.3)")
    parser.add_argument("--beta", type=float, default=0.7,
                        help="Prosody blend: 0=base rhythm, 1=reference rhythm (default: 0.7)")
    parser.add_argument("--diffusion-steps", type=int, default=10,
                        help="Quality vs speed: 5=fast, 20=best (default: 10)")
    parser.add_argument("--expressiveness", type=float, default=1.0,
                        help="Emotional intensity: 1.0=neutral, 1.5=upbeat, 2.0+=very expressive (default: 1.0)")
    parser.add_argument("--batch", action="store_true",
                        help="Generate samples sweeping expressiveness from 1.0 to 2.0")

    args = parser.parse_args()

    if not args.speaker_wav.exists():
        print(f"Error: Speaker WAV not found: {args.speaker_wav}")
        sys.exit(1)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    text = args.text or SAMPLE_TEXTS[0]

    if args.batch:
        # Sweep expressiveness so you can hear the difference
        for exp in [1.0, 1.3, 1.6, 2.0]:
            out = output_dir / f"expressiveness_{exp}.wav"
            clone_voice(args.speaker_wav, text, out,
                        args.alpha, args.beta, args.diffusion_steps, exp)
        print(f"\nAll samples saved to: {output_dir}")
        print("Compare expressiveness_1.0.wav (neutral) → expressiveness_2.0.wav (most expressive)")
    else:
        out = output_dir / "cloned_output.wav"
        clone_voice(args.speaker_wav, text, out,
                    args.alpha, args.beta, args.diffusion_steps, args.expressiveness)


if __name__ == "__main__":
    main()
