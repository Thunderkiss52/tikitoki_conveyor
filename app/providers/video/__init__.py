from app.providers.video.comfyui import ComfyUIVideoProvider
from app.providers.video.reference import ReferenceVideoProvider
from app.providers.video.stub import StubVideoProvider


SYNTHETIC_VIDEO_PROVIDERS = {"stub", "synthetic"}


def is_synthetic_video_provider(name: str) -> bool:
    return name.lower() in SYNTHETIC_VIDEO_PROVIDERS


def get_video_provider(name: str):
    providers = {
        "stub": StubVideoProvider,
        "synthetic": StubVideoProvider,
        "comfyui": ComfyUIVideoProvider,
        "reference": ReferenceVideoProvider,
        "remix": ReferenceVideoProvider,
        "runway": StubVideoProvider,
        "luma": StubVideoProvider,
    }
    provider_cls = providers.get(name.lower())
    if provider_cls is None:
        raise ValueError(f"Unsupported video provider: {name}")
    return provider_cls()
