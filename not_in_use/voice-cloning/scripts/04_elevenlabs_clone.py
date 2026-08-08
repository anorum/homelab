#!/usr/bin/env python3
"""
Voice cloning with ElevenLabs API.

ElevenLabs offers the highest quality voice cloning available.
- Instant clone: ~1-5 min of audio, good quality
- Professional clone: ~30+ min of audio, near-indistinguishable ($99/mo plan)

Usage:
    # Set your API key
    export ELEVENLABS_API_KEY="your-api-key-here"

    # Clone your voice (instant clone)
    python 04_elevenlabs_clone.py clone \
        --name "My Voice" \
        --audio-files ../data/raw/sample1.wav ../data/raw/sample2.wav

    # Generate speech with a cloned voice
    python 04_elevenlabs_clone.py speak \
        --voice-id "abc123" \
        --text "Hello from my cloned voice"

    # List your available voices
    python 04_elevenlabs_clone.py list

    # Generate samples with all your voices for comparison
    python 04_elevenlabs_clone.py demo

Prerequisites:
    pip install elevenlabs
    Sign up at https://elevenlabs.io — Starter plan ($5/mo) includes instant cloning
"""

import argparse
import os
import sys
from pathlib import Path


def get_client():
    """Get authenticated ElevenLabs client."""
    from elevenlabs.client import ElevenLabs

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("Error: ELEVENLABS_API_KEY environment variable not set")
        print("Get your key at: https://elevenlabs.io/app/settings/api-keys")
        sys.exit(1)

    return ElevenLabs(api_key=api_key)


def clone_voice(args):
    """Create an instant voice clone from audio files."""
    client = get_client()

    audio_files = []
    for f in args.audio_files:
        p = Path(f).resolve()
        if not p.exists():
            print(f"Error: File not found: {p}")
            sys.exit(1)
        audio_files.append(open(p, "rb"))

    print(f"Cloning voice '{args.name}' from {len(audio_files)} file(s)...")

    voice = client.clone(
        name=args.name,
        description=args.description or f"Cloned voice: {args.name}",
        files=audio_files,
    )

    for f in audio_files:
        f.close()

    print(f"Voice cloned successfully!")
    print(f"  Name: {voice.name}")
    print(f"  Voice ID: {voice.voice_id}")
    print()
    print(f"Generate speech with:")
    print(f"  python 04_elevenlabs_clone.py speak --voice-id {voice.voice_id} --text \"Hello world\"")


def speak(args):
    """Generate speech with a cloned voice."""
    client = get_client()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "elevenlabs_output.mp3"

    print(f"Generating speech with voice {args.voice_id}...")
    print(f"Text: {args.text[:80]}{'...' if len(args.text) > 80 else ''}")

    audio = client.generate(
        text=args.text,
        voice=args.voice_id,
        model="eleven_multilingual_v2",
    )

    # Write audio bytes
    with open(output_path, "wb") as f:
        for chunk in audio:
            f.write(chunk)

    print(f"Saved: {output_path}")


def list_voices(args):
    """List all available voices."""
    client = get_client()
    response = client.voices.get_all()

    print(f"{'Name':<30} {'Voice ID':<25} {'Category':<15}")
    print("-" * 70)
    for voice in response.voices:
        category = voice.category or "unknown"
        print(f"{voice.name:<30} {voice.voice_id:<25} {category:<15}")


def demo(args):
    """Generate a demo sample with each of your cloned voices."""
    client = get_client()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    response = client.voices.get_all()
    cloned = [v for v in response.voices if v.category == "cloned"]

    if not cloned:
        print("No cloned voices found. Clone one first:")
        print("  python 04_elevenlabs_clone.py clone --name 'My Voice' --audio-files sample.wav")
        return

    text = "Hello, welcome to my smart home. How can I help you today?"
    print(f"Generating demos for {len(cloned)} cloned voice(s)...")

    for voice in cloned:
        output_path = output_dir / f"demo_{voice.name.lower().replace(' ', '_')}.mp3"
        print(f"  {voice.name} -> {output_path.name}")

        audio = client.generate(
            text=text,
            voice=voice.voice_id,
            model="eleven_multilingual_v2",
        )
        with open(output_path, "wb") as f:
            for chunk in audio:
                f.write(chunk)

    print(f"\nAll demos saved to: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="ElevenLabs voice cloning")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Clone command
    clone_parser = subparsers.add_parser("clone", help="Clone a voice from audio files")
    clone_parser.add_argument("--name", required=True, help="Name for the cloned voice")
    clone_parser.add_argument("--description", help="Voice description")
    clone_parser.add_argument("--audio-files", nargs="+", required=True,
                              help="Audio files (WAV/MP3, total ~1-5 min for instant clone)")
    clone_parser.set_defaults(func=clone_voice)

    # Speak command
    speak_parser = subparsers.add_parser("speak", help="Generate speech with a voice")
    speak_parser.add_argument("--voice-id", required=True, help="Voice ID to use")
    speak_parser.add_argument("--text", required=True, help="Text to speak")
    speak_parser.add_argument("--output-dir", default="../output/elevenlabs")
    speak_parser.set_defaults(func=speak)

    # List command
    list_parser = subparsers.add_parser("list", help="List available voices")
    list_parser.set_defaults(func=list_voices)

    # Demo command
    demo_parser = subparsers.add_parser("demo", help="Generate demo with all cloned voices")
    demo_parser.add_argument("--output-dir", default="../output/elevenlabs")
    demo_parser.set_defaults(func=demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
