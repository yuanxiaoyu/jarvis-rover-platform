from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .config import load_config


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Jarvis Rover host-local voice service")
    parser.add_argument("command", nargs="?", choices=("run", "check"), default="run")
    args = parser.parse_args(argv)
    config = load_config()
    try:
        config.validate_prerequisites()
    except (OSError, ValueError) as exc:
        print(f"voice unavailable: {exc}")
        return 2
    if args.command == "check":
        print("voice prerequisites available")
        return 0

    try:
        from .asr import SherpaOnnxRecognizer
        from .audio import AlsaAudioInput
        from .gateway_client import GatewayClient
        from .service import VoiceService
        from .tts import PocketTtsPlayer, SherpaVitsTtsPlayer
        from .wakeword import OpenWakeWordDetector, SherpaKeywordSpotterDetector
    except ImportError as exc:
        print(f"voice unavailable: optional dependency is missing ({type(exc).__name__})")
        return 2

    if config.gateway_token is None:
        print("voice unavailable: gateway token is missing")
        return 2

    async def run_service() -> None:
        if config.tts_engine == "sherpa_vits":
            tts = SherpaVitsTtsPlayer(
                config.tts_model_dir,
                config.playback_device,
                config.tts_device,
                config.tts_playback_sample_rate,
                config.tts_speaker_id,
                config.tts_rule_fsts,
                max_audio_seconds=config.tts_max_audio_seconds,
            )
        else:
            tts = PocketTtsPlayer(
                config.tts_model_dir,
                config.tts_checkpoint,
                config.tts_voice_state,
                config.playback_device,
                config.tts_device,
                config.tts_playback_sample_rate,
                max_audio_seconds=config.tts_max_audio_seconds,
                config_path=config.tts_config,
            )
        asr = SherpaOnnxRecognizer(config.asr_model_dir, config.min_confidence, config.sample_rate)
        service = VoiceService(
            config,
            AlsaAudioInput(config.capture_device, config.sample_rate, config.channels),
            (
                SherpaKeywordSpotterDetector(
                    config.wakeword_model,
                    config.wakeword_threshold,
                    config.wakeword_cooldown_seconds,
                    phrase=config.wakeword_phrase,
                    keywords_file=config.wakeword_keywords_file,
                    keywords_score=config.wakeword_score,
                    fallback_asr=asr,
                )
                if Path(config.wakeword_model).is_dir()
                else OpenWakeWordDetector(
                    config.wakeword_model,
                    config.wakeword_threshold,
                    config.wakeword_cooldown_seconds,
                    wakeword_phrase=config.wakeword_phrase,
                )
            ),
            asr,
            tts,
            GatewayClient(config.gateway_url, config.gateway_token.get_secret_value()),
        )
        try:
            await service.run()
        finally:
            service.stop()

    try:
        asyncio.run(run_service())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
