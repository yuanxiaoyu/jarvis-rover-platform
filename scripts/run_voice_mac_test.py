"""macOS-only local TTS bridge for exercising the voice gateway with a USB DAC."""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

import httpx


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:18000/api/v1/voice")
    parser.add_argument("--token", default=os.environ.get("ROVER_VOICE_GATEWAY_TOKEN", "local-test-token"))
    parser.add_argument("--model", default="models/tts/zh_CN-huayan-medium.onnx")
    parser.add_argument("--config", default="models/tts/zh_CN-huayan-medium.onnx.json")
    parser.add_argument("--audio-device-index", type=int, default=None)
    args = parser.parse_args()
    headers = {"X-Rover-Voice-Token": args.token}
    async with httpx.AsyncClient(timeout=10) as client:
        print("Mac TTS worker ready; submit text from the Web console.")
        while True:
            await client.post(f"{args.api}/heartbeat", headers=headers, json={"state": "wake_listening", "enabled": True, "component_latency_ms": {}})
            response = await client.get(f"{args.api}/tts/next", headers=headers)
            if response.status_code == 200:
                text = response.json().get("text")
                if text:
                    with tempfile.TemporaryDirectory(prefix="jarvis-tts-") as temp_dir:
                        wav = Path(temp_dir) / "reply.wav"
                        subprocess.run([".venv-voice/bin/piper", "-m", args.model, "-c", args.config, "-f", str(wav)], input=(text + "\n").encode(), check=True)
                        if args.audio_device_index is None:
                            subprocess.run(["afplay", str(wav)], check=False)
                        else:
                            subprocess.run(["/opt/homebrew/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(wav), "-f", "audiotoolbox", "-audio_device_index", str(args.audio_device_index), "-"], check=False)
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
