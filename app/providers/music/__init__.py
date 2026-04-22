from app.providers.music.stub import FallbackMusicProvider


def get_music_provider(name: str):
    providers = {
        "stub": FallbackMusicProvider,
        "library": FallbackMusicProvider,
        "generate": FallbackMusicProvider,
        "hybrid": FallbackMusicProvider,
    }
    provider_cls = providers.get(name.lower())
    if provider_cls is None:
        raise ValueError(f"Unsupported music provider: {name}")
    return provider_cls()
