#!/usr/bin/env python3
"""
Step 2: Train (fine-tune) a custom Piper TTS voice.

This script automates:
1. Downloading a pre-trained Piper checkpoint (for fine-tuning)
2. Preprocessing your LJSpeech dataset
3. Running the Piper training loop
4. Exporting the trained model to ONNX

Usage:
    # Fine-tune from a pre-trained voice (recommended)
    python 02_train_piper.py --dataset-dir ../data/dataset --output-dir ../models

    # Train from scratch (much slower, needs more data)
    python 02_train_piper.py --dataset-dir ../data/dataset --output-dir ../models --from-scratch

Prerequisites:
    1. Clone piper: git clone https://github.com/rhasspy/piper.git /opt/piper
    2. Install: cd /opt/piper/src/python && pip install -e .
    3. pip install onnx onnxruntime
    4. Run 01_prepare_audio.py first to create the dataset
"""

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

# Pre-trained checkpoint URLs (from Piper releases)
PRETRAINED_CHECKPOINTS = {
    "lessac-medium": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/epoch%3D2164-step%3D1355540.ckpt",
        "quality": "medium",
        "description": "US English female (lessac) - good base for fine-tuning",
    },
    "ryan-medium": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/epoch%3D4478-step%3D2803840.ckpt",
        "quality": "medium",
        "description": "US English male (ryan) - good base for fine-tuning",
    },
    "arctic-medium": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/arctic/medium/epoch%3D6131-step%3D2605712.ckpt",
        "quality": "medium",
        "description": "US English multi-speaker (arctic)",
    },
}

PIPER_REPO = "/opt/piper"


def check_prerequisites():
    """Verify piper training code is available."""
    piper_python = Path(PIPER_REPO) / "src" / "python"
    if not piper_python.exists():
        print("Error: Piper repo not found at /opt/piper")
        print("Run: git clone https://github.com/rhasspy/piper.git /opt/piper")
        print("Then: cd /opt/piper/src/python && pip install -e .")
        sys.exit(1)
    return piper_python


def detect_accelerator() -> tuple[str, int]:
    """Detect the best available accelerator."""
    # Check for Apple Silicon MPS
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            import torch
            if torch.backends.mps.is_available():
                print("Detected: Apple Silicon with MPS support")
                return "mps", 1
        except (ImportError, AttributeError):
            pass

    # Check for CUDA GPU
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            print(f"Detected: CUDA GPU ({gpu_name})")
            return "gpu", 1
    except (ImportError, AttributeError):
        pass

    print("No GPU detected, using CPU (this will be slow)")
    return "cpu", 1


def download_checkpoint(checkpoint_name: str, output_dir: Path) -> Path:
    """Download a pre-trained checkpoint for fine-tuning."""
    if checkpoint_name not in PRETRAINED_CHECKPOINTS:
        print(f"Unknown checkpoint: {checkpoint_name}")
        print(f"Available: {', '.join(PRETRAINED_CHECKPOINTS.keys())}")
        sys.exit(1)

    info = PRETRAINED_CHECKPOINTS[checkpoint_name]
    ckpt_path = output_dir / f"{checkpoint_name}.ckpt"

    if ckpt_path.exists():
        print(f"Checkpoint already downloaded: {ckpt_path}")
        return ckpt_path

    print(f"Downloading {checkpoint_name}: {info['description']}")
    output_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["curl", "-L", "-o", str(ckpt_path), info["url"]],
        check=True,
    )
    print(f"Downloaded: {ckpt_path}")
    return ckpt_path


def preprocess_dataset(piper_python: Path, dataset_dir: Path, training_dir: Path,
                       quality: str = "medium", sample_rate: int = 22050):
    """Run Piper preprocessing on the LJSpeech dataset."""
    print("\n=== Preprocessing dataset ===")
    training_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "piper_train.preprocess",
        "--language", "en",
        "--input-dir", str(dataset_dir),
        "--output-dir", str(training_dir),
        "--dataset-format", "ljspeech",
        "--single-speaker",
        "--sample-rate", str(sample_rate),
    ]

    subprocess.run(cmd, check=True, cwd=str(piper_python))
    print(f"Preprocessing complete: {training_dir}")


def train(piper_python: Path, training_dir: Path, accelerator: str, devices: int,
          checkpoint_path: Path | None = None, quality: str = "medium",
          batch_size: int = 16, max_epochs: int = 5000,
          checkpoint_epochs: int = 50, validation_split: float = 0.05):
    """Run the Piper training loop."""
    print("\n=== Starting training ===")
    print(f"  Accelerator: {accelerator}")
    print(f"  Batch size: {batch_size}")
    print(f"  Max epochs: {max_epochs}")
    print(f"  Quality: {quality}")
    if checkpoint_path:
        print(f"  Fine-tuning from: {checkpoint_path}")
    else:
        print("  Training from scratch")

    cmd = [
        sys.executable, "-m", "piper_train",
        "--dataset-dir", str(training_dir),
        "--accelerator", accelerator,
        "--devices", str(devices),
        "--batch-size", str(batch_size),
        "--validation-split", str(validation_split),
        "--max-epochs", str(max_epochs),
        "--checkpoint-epochs", str(checkpoint_epochs),
        "--quality", quality,
    ]

    if checkpoint_path:
        cmd.extend(["--resume_from_checkpoint", str(checkpoint_path)])

    print(f"\nRunning: {' '.join(cmd)}")
    print("Monitor with: tensorboard --logdir", training_dir / "lightning_logs")
    print()

    subprocess.run(cmd, check=True, cwd=str(piper_python))


def export_onnx(piper_python: Path, training_dir: Path, output_path: Path):
    """Export trained model to ONNX format for Piper inference."""
    print("\n=== Exporting to ONNX ===")

    # Find the latest checkpoint
    log_dir = training_dir / "lightning_logs"
    if not log_dir.exists():
        print(f"No training logs found in {log_dir}")
        sys.exit(1)

    # Find latest version directory
    versions = sorted(log_dir.glob("version_*"), key=lambda p: int(p.name.split("_")[1]))
    if not versions:
        print("No version directories found in lightning_logs")
        sys.exit(1)

    latest_version = versions[-1]
    checkpoints = sorted((latest_version / "checkpoints").glob("*.ckpt"))
    if not checkpoints:
        print(f"No checkpoints found in {latest_version / 'checkpoints'}")
        sys.exit(1)

    # Use last checkpoint
    last_ckpt = checkpoints[-1]
    print(f"Exporting checkpoint: {last_ckpt}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "piper_train.export_onnx",
        str(last_ckpt),
        str(output_path),
    ]

    subprocess.run(cmd, check=True, cwd=str(piper_python))
    print(f"\nExported: {output_path}")
    print(f"Config:   {output_path}.json")
    print()
    print("Deploy to Wyoming Piper:")
    print(f"  cp {output_path} {output_path}.json /path/to/piper/voices/")


def main():
    parser = argparse.ArgumentParser(description="Train a custom Piper TTS voice")
    parser.add_argument("--dataset-dir", type=Path, required=True,
                        help="LJSpeech dataset directory (from 01_prepare_audio.py)")
    parser.add_argument("--output-dir", type=Path, default=Path("../models"),
                        help="Output directory for models (default: ../models)")
    parser.add_argument("--quality", default="medium", choices=["low", "medium", "high"],
                        help="Voice quality (default: medium)")
    parser.add_argument("--base-voice", default="lessac-medium",
                        choices=list(PRETRAINED_CHECKPOINTS.keys()),
                        help="Pre-trained voice to fine-tune from (default: lessac-medium)")
    parser.add_argument("--from-scratch", action="store_true",
                        help="Train from scratch instead of fine-tuning")
    parser.add_argument("--batch-size", type=int, default=16,
                        help="Training batch size (default: 16, reduce if OOM)")
    parser.add_argument("--max-epochs", type=int, default=5000,
                        help="Maximum training epochs (default: 5000)")
    parser.add_argument("--export-only", action="store_true",
                        help="Skip training, just export the latest checkpoint to ONNX")
    parser.add_argument("--voice-name", default="my-voice",
                        help="Name for the exported voice (default: my-voice)")

    args = parser.parse_args()

    piper_python = check_prerequisites()
    dataset_dir = args.dataset_dir.resolve()
    output_dir = args.output_dir.resolve()
    training_dir = output_dir / "training"

    if not dataset_dir.exists():
        print(f"Error: Dataset directory not found: {dataset_dir}")
        print("Run 01_prepare_audio.py first.")
        sys.exit(1)

    if args.export_only:
        export_onnx(piper_python, training_dir, output_dir / f"{args.voice_name}.onnx")
        return

    # Detect accelerator
    accelerator, devices = detect_accelerator()

    # Download pre-trained checkpoint (unless training from scratch)
    checkpoint_path = None
    if not args.from_scratch:
        checkpoint_path = download_checkpoint(args.base_voice, output_dir / "checkpoints")

    # Preprocess
    preprocess_dataset(piper_python, dataset_dir, training_dir, args.quality)

    # Train
    train(
        piper_python, training_dir, accelerator, devices,
        checkpoint_path=checkpoint_path,
        quality=args.quality,
        batch_size=args.batch_size,
        max_epochs=args.max_epochs,
    )

    # Export
    export_onnx(piper_python, training_dir, output_dir / f"{args.voice_name}.onnx")

    print("\n" + "=" * 60)
    print("Training complete!")
    print(f"Voice model: {output_dir / args.voice_name}.onnx")
    print()
    print("To use with Wyoming Piper, copy the .onnx and .onnx.json files")
    print("to your Piper voices directory and update the configuration.")


if __name__ == "__main__":
    main()
