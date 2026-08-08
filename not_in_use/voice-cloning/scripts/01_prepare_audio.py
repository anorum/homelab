#!/usr/bin/env python3
"""
Step 1: Prepare casual voice recordings for Piper TTS training.

This script:
1. Converts audio files to mono 22050Hz WAV
2. Uses Whisper to transcribe and segment into utterances
3. Splits audio into individual clips based on Whisper segments
4. Filters out clips that are too short/long or low quality
5. Outputs an LJSpeech-format dataset ready for Piper training

Usage:
    python 01_prepare_audio.py --input-dir ../data/raw --output-dir ../data/dataset

Prerequisites:
    pip install openai-whisper pydub soundfile numpy
    brew install ffmpeg  # or apt install ffmpeg
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf


def convert_to_wav(input_path: Path, output_path: Path, sample_rate: int = 22050) -> bool:
    """Convert any audio file to mono WAV at the target sample rate."""
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(input_path),
                "-ac", "1",           # mono
                "-ar", str(sample_rate),  # sample rate
                "-sample_fmt", "s16", # 16-bit
                str(output_path),
            ],
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [WARN] Failed to convert {input_path.name}: {e.stderr.decode()[:200]}")
        return False


def transcribe_with_whisper(wav_path: Path, model_name: str = "medium") -> list[dict]:
    """Transcribe a WAV file using Whisper, returning timestamped segments."""
    import whisper

    print(f"  Transcribing {wav_path.name} with Whisper ({model_name})...")
    model = whisper.load_model(model_name)
    result = model.transcribe(
        str(wav_path),
        language="en",
        word_timestamps=False,
        verbose=False,
    )
    return result.get("segments", [])


def split_audio(wav_path: Path, segments: list[dict], output_dir: Path,
                clip_prefix: str, sample_rate: int = 22050,
                min_duration: float = 1.0, max_duration: float = 15.0,
                min_rms: float = 0.005) -> list[dict]:
    """Split a WAV file into individual clips based on Whisper segments.

    Returns list of dicts with clip_id, text, and duration.
    """
    audio_data, sr = sf.read(str(wav_path))
    if sr != sample_rate:
        print(f"  [WARN] Sample rate mismatch: {sr} != {sample_rate}")

    clips = []
    for i, seg in enumerate(segments):
        start_sec = seg["start"]
        end_sec = seg["end"]
        text = seg["text"].strip()

        # Skip empty or very short text
        if len(text) < 3:
            continue

        duration = end_sec - start_sec
        if duration < min_duration or duration > max_duration:
            continue

        # Add small padding (100ms) to avoid cutting words
        start_sample = max(0, int((start_sec - 0.05) * sample_rate))
        end_sample = min(len(audio_data), int((end_sec + 0.05) * sample_rate))
        clip_audio = audio_data[start_sample:end_sample]

        # Check audio quality (skip very quiet clips)
        rms = np.sqrt(np.mean(clip_audio ** 2))
        if rms < min_rms:
            continue

        clip_id = f"{clip_prefix}_{i:04d}"
        clip_path = output_dir / f"{clip_id}.wav"
        sf.write(str(clip_path), clip_audio, sample_rate)

        clips.append({
            "id": clip_id,
            "text": text,
            "duration": duration,
            "rms": float(rms),
        })

    return clips


def main():
    parser = argparse.ArgumentParser(description="Prepare voice recordings for Piper training")
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="Directory containing raw audio files")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Output directory for LJSpeech dataset")
    parser.add_argument("--whisper-model", default="medium",
                        choices=["tiny", "base", "small", "medium", "large"],
                        help="Whisper model size (default: medium)")
    parser.add_argument("--sample-rate", type=int, default=22050,
                        help="Target sample rate (default: 22050)")
    parser.add_argument("--min-duration", type=float, default=1.0,
                        help="Minimum clip duration in seconds (default: 1.0)")
    parser.add_argument("--max-duration", type=float, default=15.0,
                        help="Maximum clip duration in seconds (default: 15.0)")
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    wav_dir = output_dir / "wav"

    if not input_dir.exists():
        print(f"Error: Input directory not found: {input_dir}")
        sys.exit(1)

    # Create output structure
    wav_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "_temp_converted"
    temp_dir.mkdir(exist_ok=True)

    # Find all audio files
    audio_extensions = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma"}
    audio_files = sorted(
        f for f in input_dir.iterdir()
        if f.suffix.lower() in audio_extensions
    )

    if not audio_files:
        print(f"No audio files found in {input_dir}")
        print(f"Supported formats: {', '.join(audio_extensions)}")
        sys.exit(1)

    print(f"Found {len(audio_files)} audio file(s) in {input_dir}")
    print(f"Output: {output_dir}")
    print(f"Whisper model: {args.whisper_model}")
    print()

    all_clips = []

    for file_idx, audio_file in enumerate(audio_files):
        print(f"[{file_idx + 1}/{len(audio_files)}] Processing: {audio_file.name}")

        # Step 1: Convert to WAV
        converted_wav = temp_dir / f"{audio_file.stem}.wav"
        if audio_file.suffix.lower() == ".wav":
            # Re-encode to ensure correct format
            if not convert_to_wav(audio_file, converted_wav, args.sample_rate):
                continue
        else:
            if not convert_to_wav(audio_file, converted_wav, args.sample_rate):
                continue

        # Step 2: Transcribe with Whisper
        segments = transcribe_with_whisper(converted_wav, args.whisper_model)
        print(f"  Found {len(segments)} segments")

        # Step 3: Split into clips
        clip_prefix = f"clip_{file_idx:03d}"
        clips = split_audio(
            converted_wav, segments, wav_dir, clip_prefix,
            sample_rate=args.sample_rate,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
        )
        print(f"  Kept {len(clips)} clips (filtered by duration/quality)")
        all_clips.extend(clips)

    # Step 4: Write metadata.csv (LJSpeech format: id|text)
    metadata_path = output_dir / "metadata.csv"
    with open(metadata_path, "w") as f:
        for clip in all_clips:
            # LJSpeech format: id|text (no header)
            f.write(f"{clip['id']}|{clip['text']}\n")

    # Write detailed manifest for review
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(all_clips, f, indent=2)

    # Cleanup temp files
    shutil.rmtree(temp_dir)

    # Summary
    total_duration = sum(c["duration"] for c in all_clips)
    print()
    print("=" * 60)
    print(f"Dataset ready: {output_dir}")
    print(f"  Total clips: {len(all_clips)}")
    print(f"  Total duration: {total_duration / 60:.1f} minutes")
    print(f"  Metadata: {metadata_path}")
    print(f"  Audio: {wav_dir}")
    print(f"  Manifest: {manifest_path}")
    print()
    if len(all_clips) < 500:
        print(f"  ⚠ Only {len(all_clips)} clips — Piper works best with 500+ clips.")
        print("    Consider adding more recordings!")
    else:
        print(f"  ✓ {len(all_clips)} clips should be enough for fine-tuning.")
    print()
    print("Next step: Review manifest.json, remove bad clips, then run:")
    print("  python 02_train_piper.py --dataset-dir", output_dir)


if __name__ == "__main__":
    main()
