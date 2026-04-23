from app.providers.tts.piper import PiperTTSProvider
from app.providers.tts.stub import SilentTTSProvider


def get_tts_provider(name: str):
    providers = {
        "stub": SilentTTSProvider,
        "piper": PiperTTSProvider,
        "elevenlabs": SilentTTSProvider,
        "xtts": SilentTTSProvider,
    }
    provider_cls = providers.get(name.lower())
    if provider_cls is None:
        raise ValueError(f"Unsupported TTS provider: {name}")
    return provider_cls()
