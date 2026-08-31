from __future__ import annotations
import argparse
import asyncio
from .config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=["run", "check"]); args = parser.parse_args()
    config = load_config()
    try: config.validate_prerequisites()
    except ValueError as exc:
        print(f"voice unavailable: {exc}"); return 2
    if args.command == "check": return 0
    from .audio import AlsaAudioInput
    from .asr import SherpaOnnxRecognizer
    from .gateway_client import GatewayClient
    from .tts import PiperTtsPlayer
    from .wakeword import OpenWakeWordDetector
    from .service import VoiceService
    async def run_service() -> None:
        service = VoiceService(config, AlsaAudioInput(config.capture_device), OpenWakeWordDetector(config.wakeword_model, config.wakeword_threshold, config.wakeword_cooldown_seconds), SherpaOnnxRecognizer(config.asr_model_dir), PiperTtsPlayer(config.tts_model, config.tts_config, config.playback_device), GatewayClient(config.gateway_url, config.gateway_token))
        try: await service.run()
        finally: service.stop()
    asyncio.run(run_service())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
